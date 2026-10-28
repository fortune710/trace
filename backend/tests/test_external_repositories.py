from __future__ import annotations

import asyncio
import base64
import io
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from email.message import Message
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from redis.exceptions import RedisError

from auth.config import AuthSettings
from auth.errors import (
    BranchConflict,
    GithubAuthorizationRequired,
    ProviderRateLimited,
    ProviderUnavailable,
    RepositoryInvalidRequest,
    RepositoryNotFound,
    UnsupportedSource,
)
from credentials.models import CredentialProvider
from db.types import RepositoryProvider
from external_repositories.routes import build_router
from external_repositories.service import (
    BranchRecord,
    CreatedBranch,
    GitHubClient,
    GitHubRequestLogContext,
    RepositoryPageResult,
    RepositoryProviderError,
    RepositoryRecord,
    RepositoryService,
    ReviewGitHubSourceAccess,
    ReviewSourceFileError,
    _is_safe_patch,
    invalidate_repository_catalog,
)


def test_remediation_patch_validation_rejects_unsafe_or_malformed_diffs() -> None:
    assert _is_safe_patch(
        "diff --git a/src/app.py b/src/app.py\n--- a/src/app.py\n+++ b/src/app.py\n@@ -1 +1 @@\n-old\n+new\n"
    )
    assert not _is_safe_patch("not a diff")
    assert not _is_safe_patch("diff --git a/.git/config b/.git/config\n")
    assert not _is_safe_patch("diff --git a/file b/file\nGIT binary patch\n")
    assert not _is_safe_patch("diff --git a/file b/file\nnew file mode 120000\n")


def _repository_payload() -> dict[str, object]:
    return {
        "id": 12345,
        "owner": {"login": "octocat"},
        "name": "hello-world",
        "full_name": "octocat/hello-world",
        "private": False,
        "visibility": "public",
        "default_branch": "main",
        "html_url": "https://github.com/octocat/hello-world",
    }


class _ReviewCredentialService:
    def __init__(self) -> None:
        self._settings = type(
            "Settings", (), {"github_api_url": "https://github.example.test"}
        )()
        self.access_token_calls = 0

    def _access_token(self, *, owner_id, provider) -> str:
        del owner_id, provider
        self.access_token_calls += 1
        return "review-token"


def _review_log_context() -> GitHubRequestLogContext:
    return GitHubRequestLogContext(
        review_id=uuid4(), review_agent_id=uuid4(), attempt_id=uuid4()
    )


def _tree_payload(*paths: str) -> dict[str, object]:
    return {
        "truncated": False,
        "tree": [{"type": "blob", "path": path} for path in paths],
    }


def _file_payload(content: str) -> dict[str, str]:
    return {
        "type": "file",
        "encoding": "base64",
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
    }


def _bytes_file_payload(content: bytes) -> dict[str, str]:
    return {
        "type": "file",
        "encoding": "base64",
        "content": base64.b64encode(content).decode("ascii"),
    }


def _review_access(handler, **kwargs) -> ReviewGitHubSourceAccess:
    client = httpx.Client(
        base_url="https://github.example.test",
        transport=httpx.MockTransport(handler),
    )
    return ReviewGitHubSourceAccess(
        repository_service=_ReviewCredentialService(),  # type: ignore[arg-type]
        owner_id=uuid4(),
        repository_identifier="12345",
        revision="a" * 40,
        client=client,
        sleep=kwargs.pop("sleep", lambda _seconds: None),
        jitter=kwargs.pop("jitter", lambda _low, high: high),
        **kwargs,
    )


def test_review_source_access_caches_repository_metadata_and_reuses_client() -> None:
    paths = ["backend/one.py", "backend/two.py"]
    requested_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.url.path == "/repositories/12345":
            return httpx.Response(200, json=_repository_payload())
        if request.url.path.endswith("/git/trees/" + "a" * 40):
            return httpx.Response(200, json=_tree_payload(*paths))
        return httpx.Response(200, json=_file_payload("contents"))

    access = _review_access(handler)
    context = _review_log_context()
    assert access.list_paths(path_prefix=".", max_results=50, log_context=context) == (
        paths,
        False,
    )
    assert access.list_paths(path_prefix="./", max_results=50, log_context=context) == (
        paths,
        False,
    )
    assert access.read_file(path=paths[0], log_context=context) == "contents"
    assert access.read_file(path=paths[1], log_context=context) == "contents"

    assert requested_paths.count("/repositories/12345") == 1
    assert len(requested_paths) == 5


def test_review_source_access_limits_concurrent_requests_to_two() -> None:
    active_requests = 0
    highest_active_requests = 0
    lock = threading.Lock()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active_requests, highest_active_requests
        with lock:
            active_requests += 1
            highest_active_requests = max(highest_active_requests, active_requests)
        try:
            time.sleep(0.03)
            if request.url.path == "/repositories/12345":
                return httpx.Response(200, json=_repository_payload())
            return httpx.Response(200, json=_file_payload("contents"))
        finally:
            with lock:
                active_requests -= 1

    access = _review_access(handler, max_concurrent_requests=2)
    context = _review_log_context()
    access.read_file(path="bootstrap.py", log_context=context)
    with ThreadPoolExecutor(max_workers=6) as pool:
        contents = list(
            pool.map(
                lambda index: access.read_file(
                    path=f"src/{index}.py", log_context=context
                ),
                range(6),
            )
        )

    assert contents == ["contents"] * 6
    assert highest_active_requests == 2


def test_review_source_access_retries_transient_get_failures_with_safe_logs(
    caplog,
) -> None:
    calls = 0
    retry_delays: list[float] = []
    secret_file_content = "do-not-log-this-file-body"

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("connection interrupted", request=request)
        if request.url.path == "/repositories/12345":
            return httpx.Response(200, json=_repository_payload())
        return httpx.Response(200, json=_file_payload(secret_file_content))

    access = _review_access(
        handler,
        sleep=retry_delays.append,
        jitter=lambda _low, high: high,
    )
    context = _review_log_context()
    with caplog.at_level("INFO", logger="trace.repositories"):
        assert (
            access.read_file(path="src/main.py", log_context=context)
            == secret_file_content
        )

    assert calls == 3
    assert retry_delays == [0.25]
    assert '"request_attempt": 2' in caplog.text
    assert str(context.review_id) in caplog.text
    assert "review-token" not in caplog.text
    assert secret_file_content not in caplog.text


def test_review_source_access_honors_retry_after_and_maps_exhausted_rate_limit() -> (
    None
):
    retry_delays: list[float] = []
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(429, headers={"Retry-After": "45"})

    access = _review_access(handler, sleep=retry_delays.append)
    with pytest.raises(ProviderRateLimited):
        access.read_file(path="src/main.py", log_context=_review_log_context())

    assert attempts == 3
    assert retry_delays == [30.0, 30.0]


@pytest.mark.parametrize(
    ("content", "expected_code"),
    [
        (b"\x80", "file_not_utf8"),
        (b"x" * (512 * 1024 + 1), "file_too_large"),
    ],
)
def test_review_source_access_reports_unsearchable_files_without_provider_failure(
    content: bytes,
    expected_code: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repositories/12345":
            return httpx.Response(200, json=_repository_payload())
        return httpx.Response(200, json=_bytes_file_payload(content))

    access = _review_access(handler)

    with pytest.raises(ReviewSourceFileError) as raised:
        access.read_file(path="src/file", log_context=_review_log_context())

    assert raised.value.code == expected_code


def test_review_source_access_reports_missing_file_as_tool_level_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repositories/12345":
            return httpx.Response(200, json=_repository_payload())
        return httpx.Response(404)

    access = _review_access(handler)

    with pytest.raises(ReviewSourceFileError) as raised:
        access.read_file(path="deleted.py", log_context=_review_log_context())

    assert raised.value.code == "path_not_found"


@pytest.mark.parametrize(
    ("status_code", "expected_error"),
    [
        (401, GithubAuthorizationRequired),
        (404, RepositoryNotFound),
        (409, BranchConflict),
        (422, ProviderUnavailable),
    ],
)
def test_review_source_access_does_not_retry_non_retryable_failures(
    status_code: int,
    expected_error: type[Exception],
) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(status_code)

    access = _review_access(handler)
    with pytest.raises(expected_error):
        access.read_file(path="src/main.py", log_context=_review_log_context())

    assert attempts == 1


def _response(payload: object, *, link: str | None = None):
    headers = Message()
    if link is not None:
        headers["Link"] = link

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return json.dumps(payload).encode("utf-8")

    response = Response()
    response.headers = headers
    return response


def test_github_client_lists_repositories_without_exposing_token(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["authorization"] = request.headers["Authorization"]
        captured["timeout"] = timeout
        return _response([_repository_payload()])

    monkeypatch.setattr("external_repositories.service.urlopen", fake_urlopen)

    result = GitHubClient(base_url="https://github.example.test").list_repositories(
        access_token="synthetic-token", page=1, page_size=50
    )

    assert result.next_page is None
    assert result.items[0].repository_id == "12345"
    assert result.items[0].full_name == "octocat/hello-world"
    assert "synthetic-token" not in str(result.items)
    assert captured["authorization"] == "Bearer synthetic-token"
    assert "affiliation=owner%2Ccollaborator%2Corganization_member" in captured["url"]


def test_github_api_logs_request_metadata_without_authorization(
    caplog, monkeypatch
) -> None:
    def fake_urlopen(_request, timeout):
        assert timeout == 10.0
        return _response([_repository_payload()])

    monkeypatch.setattr("external_repositories.service.urlopen", fake_urlopen)

    with caplog.at_level("INFO", logger="trace.repositories"):
        GitHubClient(base_url="https://github.example.test").list_repositories(
            access_token="synthetic-token",
            page=1,
            page_size=50,
        )

    assert '"event": "github_api_request"' in caplog.text
    assert '"method": "GET"' in caplog.text
    assert '"request_path": "/user/repos?' in caplog.text
    assert '"event": "github_api_response"' in caplog.text
    assert "synthetic-token" not in caplog.text
    assert "Authorization" not in caplog.text


def test_github_client_creates_branch_from_exact_commit(monkeypatch) -> None:
    requests: list[tuple[str, bytes | None]] = []
    commit_sha = "a" * 40

    def fake_urlopen(request, timeout):
        body = request.data
        requests.append((request.full_url, body))
        return _response(
            {
                "ref": "refs/heads/trace/remediation-1",
                "object": {"sha": commit_sha},
            }
        )

    monkeypatch.setattr("external_repositories.service.urlopen", fake_urlopen)
    client = GitHubClient(base_url="https://github.example.test")
    repository = client._repository_record(_repository_payload())

    created = client.create_branch(
        access_token="synthetic-token",
        repository=repository,
        branch_name="trace/remediation-1",
        base_revision=commit_sha,
    )

    assert created.commit_sha == commit_sha
    assert requests == [
        (
            "https://github.example.test/repos/octocat/hello-world/git/refs",
            json.dumps(
                {"ref": "refs/heads/trace/remediation-1", "sha": commit_sha},
                separators=(",", ":"),
            ).encode("utf-8"),
        )
    ]


def test_github_client_reads_paths_and_files_at_an_immutable_revision(
    monkeypatch,
) -> None:
    requests: list[str] = []

    def fake_urlopen(request, timeout):
        requests.append(request.full_url)
        if "/git/trees/" in request.full_url:
            return _response(
                {
                    "truncated": False,
                    "tree": [
                        {"path": "README.md", "type": "blob"},
                        {"path": "backend/main.py", "type": "blob"},
                        {"path": "backend", "type": "tree"},
                    ],
                }
            )
        return _response(
            {
                "type": "file",
                "encoding": "base64",
                "content": base64.b64encode(b"print('ready')\n").decode("ascii"),
            }
        )

    monkeypatch.setattr("external_repositories.service.urlopen", fake_urlopen)
    client = GitHubClient(base_url="https://github.example.test")
    repository = client._repository_record(_repository_payload())
    revision = "a" * 40

    paths, truncated = client.list_paths_at_revision(
        access_token="synthetic-token",
        repository=repository,
        revision=revision,
        path_prefix="backend",
        max_results=10,
    )
    contents = client.read_file_at_revision(
        access_token="synthetic-token",
        repository=repository,
        revision=revision,
        path="backend/main.py",
    )

    assert paths == ["backend/main.py"]
    assert truncated is False
    assert contents == "print('ready')\n"
    assert f"/git/trees/{revision}?recursive=1" in requests[0]
    assert f"/contents/backend/main.py?ref={revision}" in requests[1]


def test_repository_service_rejects_invalid_branch_base_revision() -> None:
    service = RepositoryService.__new__(RepositoryService)

    with pytest.raises(RepositoryInvalidRequest):
        service.create_branch(
            owner_id=uuid4(),
            source="github",
            repository_identifier="12345",
            branch_name="trace/remediation-1",
            base_revision="not-a-sha",
        )


def test_repository_service_rejects_unsupported_source_and_invalid_identifiers() -> (
    None
):
    service = RepositoryService.__new__(RepositoryService)

    with pytest.raises(UnsupportedSource):
        service.list_repositories(
            owner_id=uuid4(), source="gitlab", page=1, page_size=50
        )

    with pytest.raises(RepositoryInvalidRequest):
        service.create_branch(
            owner_id=uuid4(),
            source="github",
            repository_identifier="123abc",
            branch_name="trace/remediation-1",
            base_revision="a" * 40,
        )

    with pytest.raises(RepositoryInvalidRequest):
        service.create_branch(
            owner_id=uuid4(),
            source="github",
            repository_identifier="12345",
            branch_name="bad branch",
            base_revision="a" * 40,
        )


def test_github_client_maps_branch_conflict_without_provider_message(
    monkeypatch,
) -> None:
    from urllib.error import HTTPError

    headers = Message()

    def fake_urlopen(_request, timeout):
        raise HTTPError(
            "https://github.example.test",
            409,
            "synthetic provider details",
            headers,
            io.BytesIO(b"secret provider response"),
        )

    monkeypatch.setattr("external_repositories.service.urlopen", fake_urlopen)
    client = GitHubClient(base_url="https://github.example.test")
    repository = client._repository_record(_repository_payload())

    with pytest.raises(RepositoryProviderError) as raised:
        client.create_branch(
            access_token="synthetic-token",
            repository=repository,
            branch_name="trace/remediation-1",
            base_revision="a" * 40,
        )

    assert raised.value.args == ("conflict",)
    assert "synthetic provider details" not in str(raised.value)


def test_github_client_preserves_safe_retry_after_without_provider_details(
    monkeypatch,
) -> None:
    from urllib.error import HTTPError

    headers = Message()
    headers["Retry-After"] = "17"

    def fake_urlopen(_request, timeout):
        raise HTTPError(
            "https://github.example.test",
            429,
            "synthetic provider details",
            headers,
            io.BytesIO(b"secret provider response"),
        )

    monkeypatch.setattr("external_repositories.service.urlopen", fake_urlopen)

    with pytest.raises(RepositoryProviderError) as raised:
        GitHubClient(base_url="https://github.example.test").list_repositories(
            access_token="synthetic-token", page=1, page_size=50
        )

    assert raised.value.kind == "rate_limited"
    assert raised.value.retry_after_seconds == 17
    assert "synthetic" not in str(raised.value)


def test_repository_logs_contain_safe_provider_metadata_only(
    caplog, monkeypatch
) -> None:
    owner_id = uuid4()
    credential_id = uuid4()

    class FakeCredentialMetadata:
        provider = CredentialProvider.GITHUB

    class FakeCredentialService:
        def metadata(self, *, owner_id, credential_id):
            return FakeCredentialMetadata()

        def decrypt_for_provider_call(self, *, owner_id, credential_id):
            return {"access_token": "synthetic-token"}

    class FakeGitHubClient:
        def list_repositories(self, *, access_token, page, page_size, query=None):
            return RepositoryPageResult(items=[], next_page=None)

    monkeypatch.setattr(
        "external_repositories.service._active_connection",
        lambda *_args, **_kwargs: {"credential_id": credential_id},
    )
    service = RepositoryService(
        engine=object(),
        credential_service=FakeCredentialService(),
        settings=type("Settings", (), {"github_api_url": "https://github.example"})(),
        github_client=FakeGitHubClient(),
    )

    with caplog.at_level("INFO", logger="trace.repositories"):
        service.list_repositories(
            owner_id=owner_id, source="github", page=1, page_size=50
        )

    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.operation == "list_repositories"
    assert record.provider == "github"
    assert record.outcome == "accepted"
    assert '"operation": "list_repositories"' in caplog.text
    assert '"outcome": "accepted"' in caplog.text
    assert "synthetic-token" not in caplog.text
    assert "Authorization" not in caplog.text


def test_repository_failure_log_includes_only_safe_transport_metadata(caplog) -> None:
    from urllib.error import HTTPError

    from external_repositories.service import (
        RepositoryProviderError,
        _log_provider_call,
    )

    error = RepositoryProviderError(kind="unavailable")
    error.__cause__ = HTTPError(
        "https://github.example.test/private/path",
        502,
        "synthetic-provider-secret",
        {},
        None,
    )

    with caplog.at_level("INFO", logger="trace.repositories"):
        _log_provider_call("read_file", "unavailable", error=error)

    assert '"http_status": 502' in caplog.text
    assert "synthetic-provider-secret" not in caplog.text
    assert "private/path" not in caplog.text


def test_repository_service_refreshes_an_expired_github_access_token(
    monkeypatch,
) -> None:
    owner_id = uuid4()
    credential_id = uuid4()
    captured: dict[str, object] = {}

    class FakeCredentialMetadata:
        provider = CredentialProvider.GITHUB

    class FakeCredentialService:
        def metadata(self, *, owner_id, credential_id):
            return FakeCredentialMetadata()

        def decrypt_for_provider_call(self, *, owner_id, credential_id):
            return {
                "access_token": "expired-token",
                "access_token_expires_at": (
                    datetime.now(UTC) - timedelta(minutes=1)
                ).isoformat(),
            }

    class FakeGitHubClient:
        def list_repositories(self, *, access_token, page, page_size):
            captured["access_token"] = access_token
            return RepositoryPageResult(items=[], next_page=None)

    def fake_refresh(**kwargs):
        captured["refresh"] = kwargs
        return {"access_token": "refreshed-token"}

    monkeypatch.setattr(
        "external_repositories.service._active_connection",
        lambda *_args, **_kwargs: {"credential_id": credential_id},
    )
    monkeypatch.setattr("auth.oauth.refresh_github_credential", fake_refresh)
    credential_service = FakeCredentialService()
    settings = AuthSettings()
    service = RepositoryService(
        engine=object(),
        credential_service=credential_service,
        settings=settings,
        github_client=FakeGitHubClient(),
    )

    service.list_repositories(
        owner_id=owner_id,
        source="github",
        page=1,
        page_size=50,
    )

    assert captured["access_token"] == "refreshed-token"
    assert captured["refresh"] == {
        "service": credential_service,
        "settings": settings,
        "owner_id": owner_id,
        "credential_id": credential_id,
    }


def test_repository_service_create_branch_uses_owner_credential_and_base_sha(
    monkeypatch,
) -> None:
    owner_id = uuid4()
    credential_id = uuid4()
    base_sha = "b" * 40
    created_sha = "c" * 40
    captured: dict[str, object] = {}

    class FakeCredentialMetadata:
        provider = CredentialProvider.GITHUB

    class FakeCredentialService:
        def metadata(self, *, owner_id, credential_id):
            captured["metadata_owner"] = owner_id
            captured["metadata_credential"] = credential_id
            return FakeCredentialMetadata()

        def decrypt_for_provider_call(self, *, owner_id, credential_id):
            captured["decrypt_owner"] = owner_id
            captured["decrypt_credential"] = credential_id
            return {"access_token": "synthetic-token"}

    class FakeGitHubClient:
        def get_repository(self, *, access_token, repository_identifier):
            captured["token"] = access_token
            captured["repository_identifier"] = repository_identifier
            return RepositoryRecord(
                repository_id=repository_identifier,
                owner_login="octocat",
                name="hello-world",
                full_name="octocat/hello-world",
                visibility="public",
                private=False,
                default_branch="main",
                web_url="https://github.com/octocat/hello-world",
            )

        def create_branch(
            self, *, access_token, repository, branch_name, base_revision
        ):
            captured["create_token"] = access_token
            captured["create_repository"] = repository.repository_id
            captured["branch_name"] = branch_name
            captured["base_revision"] = base_revision
            return CreatedBranch(
                source="github",
                repository_id=repository.repository_id,
                name=branch_name,
                commit_sha=created_sha,
            )

    monkeypatch.setattr(
        "external_repositories.service._active_connection",
        lambda *_args, **_kwargs: {"credential_id": credential_id},
    )
    service = RepositoryService(
        engine=object(),
        credential_service=FakeCredentialService(),
        settings=type("Settings", (), {"github_api_url": "https://github.example"})(),
        github_client=FakeGitHubClient(),
    )

    result = service.create_branch(
        owner_id=owner_id,
        source="github",
        repository_identifier="12345",
        branch_name="trace/remediation-1",
        base_revision=base_sha,
    )

    assert result.commit_sha == created_sha
    assert captured == {
        "metadata_owner": owner_id,
        "metadata_credential": credential_id,
        "decrypt_owner": owner_id,
        "decrypt_credential": credential_id,
        "token": "synthetic-token",
        "repository_identifier": "12345",
        "create_token": "synthetic-token",
        "create_repository": "12345",
        "branch_name": "trace/remediation-1",
        "base_revision": base_sha,
    }


class _CatalogRedis:
    def __init__(self) -> None:
        self.values: dict[str, bytes | str] = {}
        self.expirations: dict[str, int] = {}

    async def get(self, key: str):
        return self.values.get(key)

    async def set(self, key: str, value: str, *, ex: int) -> None:
        self.values[key] = value
        self.expirations[key] = ex

    async def incr(self, key: str) -> int:
        value = self.values.get(key, b"0")
        if isinstance(value, bytes):
            value = value.decode("ascii")
        next_value = int(value) + 1
        self.values[key] = str(next_value).encode("ascii")
        return next_value

    async def expire(self, key: str, seconds: int) -> bool:
        self.expirations[key] = seconds
        return True


def _catalog_service(monkeypatch, github_client):
    owner_id = uuid4()
    connection_id = uuid4()
    credential_id = uuid4()

    class FakeCredentialMetadata:
        provider = CredentialProvider.GITHUB

    class FakeCredentialService:
        def metadata(self, *, owner_id, credential_id):
            return FakeCredentialMetadata()

        def decrypt_for_provider_call(self, *, owner_id, credential_id):
            return {"access_token": "synthetic-token"}

    monkeypatch.setattr(
        "external_repositories.service._active_connection",
        lambda *_args, **_kwargs: {
            "id": connection_id,
            "credential_id": credential_id,
        },
    )
    return (
        RepositoryService(
            engine=object(),
            credential_service=FakeCredentialService(),
            settings=type(
                "Settings", (), {"github_api_url": "https://github.example"}
            )(),
            github_client=github_client,
        ),
        owner_id,
    )


def test_repository_query_uses_a_bounded_owner_scoped_catalog_cache(
    monkeypatch,
) -> None:
    class FakeGitHubClient:
        repository_calls = 0

        def list_repositories(self, *, access_token, page, page_size, query=None):
            self.repository_calls += 1
            assert access_token == "synthetic-token"
            assert (page, page_size, query) == (1, 100, None)
            return RepositoryPageResult(
                items=[
                    RepositoryRecord(
                        repository_id="1",
                        owner_login="trace-labs",
                        name="trace-dashboard",
                        full_name="trace-labs/trace-dashboard",
                        visibility="private",
                        private=True,
                        default_branch="main",
                        web_url="https://github.com/trace-labs/trace-dashboard",
                    ),
                    RepositoryRecord(
                        repository_id="2",
                        owner_login="trace-labs",
                        name="mobile-companion",
                        full_name="trace-labs/mobile-companion",
                        visibility="public",
                        private=False,
                        default_branch="main",
                        web_url="https://github.com/trace-labs/mobile-companion",
                    ),
                ],
                next_page=2,
            )

    github_client = FakeGitHubClient()
    service, owner_id = _catalog_service(monkeypatch, github_client)
    cache = _CatalogRedis()

    dashboard = asyncio.run(
        service.search_repositories(
            owner_id=owner_id,
            source="github",
            query="dashboard",
            page=1,
            page_size=50,
            redis_client=cache,
        )
    )
    mobile = asyncio.run(
        service.search_repositories(
            owner_id=owner_id,
            source="github",
            query="MOBILE",
            page=1,
            page_size=50,
            redis_client=cache,
        )
    )

    assert [item.name for item in dashboard.items] == ["trace-dashboard"]
    assert [item.name for item in mobile.items] == ["mobile-companion"]
    assert github_client.repository_calls == 1
    assert len(cache.values) == 1
    assert set(cache.expirations.values()) == {300}


def test_branch_query_uses_a_separate_catalog_cache(monkeypatch) -> None:
    class FakeGitHubClient:
        branch_calls = 0

        def get_repository(self, *, access_token, repository_identifier):
            return RepositoryRecord(
                repository_id=repository_identifier,
                owner_login="trace-labs",
                name="trace-dashboard",
                full_name="trace-labs/trace-dashboard",
                visibility="private",
                private=True,
                default_branch="main",
                web_url="https://github.com/trace-labs/trace-dashboard",
            )

        def list_branches(
            self, *, access_token, repository, page, page_size, query=None
        ):
            self.branch_calls += 1
            assert (page, page_size, query) == (1, 100, None)
            return RepositoryPageResult(
                items=[
                    BranchRecord(
                        repository_id=repository.repository_id,
                        name="main",
                        commit_sha="a" * 40,
                        protected=True,
                    ),
                    BranchRecord(
                        repository_id=repository.repository_id,
                        name="feature/catalog-cache",
                        commit_sha="b" * 40,
                        protected=False,
                    ),
                ],
                next_page=None,
            )

    github_client = FakeGitHubClient()
    service, owner_id = _catalog_service(monkeypatch, github_client)
    cache = _CatalogRedis()

    result = asyncio.run(
        service.search_branches(
            owner_id=owner_id,
            source="github",
            repository_identifier="12345",
            query="FEATURE",
            page=1,
            page_size=50,
            redis_client=cache,
        )
    )

    assert [item.name for item in result.items] == ["feature/catalog-cache"]
    assert github_client.branch_calls == 1
    assert len(cache.values) == 1


def test_repository_query_bypasses_an_unavailable_cache(monkeypatch) -> None:
    class UnavailableRedis:
        async def get(self, _key: str):
            raise RedisError("cache unavailable")

    class FakeGitHubClient:
        def list_repositories(self, *, access_token, page, page_size, query=None):
            return RepositoryPageResult(
                items=[
                    RepositoryRecord(
                        repository_id="1",
                        owner_login="trace-labs",
                        name="trace-dashboard",
                        full_name="trace-labs/trace-dashboard",
                        visibility="private",
                        private=True,
                        default_branch="main",
                        web_url="https://github.com/trace-labs/trace-dashboard",
                    )
                ],
                next_page=None,
            )

    service, owner_id = _catalog_service(monkeypatch, FakeGitHubClient())

    result = asyncio.run(
        service.search_repositories(
            owner_id=owner_id,
            source="github",
            query="trace",
            page=1,
            page_size=50,
            redis_client=UnavailableRedis(),
        )
    )

    assert [item.name for item in result.items] == ["trace-dashboard"]


def test_successful_reconnect_invalidates_catalogs_by_version() -> None:
    redis = _CatalogRedis()
    owner_id = uuid4()

    asyncio.run(
        invalidate_repository_catalog(
            redis_client=redis,
            owner_id=owner_id,
            source=RepositoryProvider.GITHUB,
        )
    )

    assert len(redis.values) == 1
    assert set(redis.values.values()) == {b"1"}
    assert set(redis.expirations.values()) == {600}


def test_repository_routes_expose_a_bounded_query_parameter() -> None:
    app = FastAPI()
    app.include_router(build_router(AuthSettings()))
    paths = app.openapi()["paths"]

    for path in ("/repositories", "/repositories/{repository_identifier}/branches"):
        parameters = {
            parameter["name"]: parameter
            for parameter in paths[path]["get"]["parameters"]
        }
        assert {
            item.get("maxLength") for item in parameters["query"]["schema"]["anyOf"]
        } == {
            100,
            None,
        }
