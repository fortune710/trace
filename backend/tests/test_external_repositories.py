from __future__ import annotations

import io
import json
from email.message import Message
from uuid import uuid4

import pytest

from auth.errors import RepositoryInvalidRequest, UnsupportedSource
from credentials.models import CredentialProvider
from external_repositories.service import (
    CreatedBranch,
    GitHubClient,
    RepositoryPageResult,
    RepositoryProviderError,
    RepositoryRecord,
    RepositoryService,
)


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
        def list_repositories(self, *, access_token, page, page_size):
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
    assert "synthetic-token" not in caplog.text
    assert "Authorization" not in caplog.text


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
