from __future__ import annotations

import json
from dataclasses import dataclass, field
from email.message import Message
from io import BytesIO
from typing import Literal, Self
from urllib.error import HTTPError
from urllib.parse import parse_qs, unquote, urlsplit


@dataclass
class StubResponse:
    payload: object
    headers: Message = field(default_factory=Message)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> Literal[False]:
        return False

    def read(self, _limit: int) -> bytes:
        if isinstance(self.payload, bytes):
            return self.payload
        return json.dumps(self.payload).encode("utf-8")


@dataclass
class GithubApiStub:
    repositories_by_token: dict[str, list[dict[str, object]]] = field(
        default_factory=dict
    )
    branches_by_repository: dict[str, list[dict[str, object]]] = field(
        default_factory=dict
    )
    failures: dict[str, tuple[int, dict[str, str]]] = field(default_factory=dict)
    calls: list[tuple[str, str, float]] = field(default_factory=list)

    def __call__(self, request, timeout: float) -> StubResponse:
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        parsed = urlsplit(request.full_url)
        path = parsed.path
        self.calls.append((token, path, timeout))

        failure = self.failures.get(path)
        if failure is not None:
            status_code, headers = failure
            error_headers = Message()
            for name, value in headers.items():
                error_headers[name] = value
            raise HTTPError(
                request.full_url,
                status_code,
                "synthetic provider failure",
                error_headers,
                BytesIO(b"synthetic provider response"),
            )

        if path == "/user/repos":
            query = parse_qs(parsed.query)
            page = int(query.get("page", ["1"])[0])
            page_size = int(query.get("per_page", ["50"])[0])
            repositories = self.repositories_by_token.get(token, [])
            start = (page - 1) * page_size
            items = repositories[start : start + page_size]
            response_headers = Message()
            if start + page_size < len(repositories):
                response_headers["Link"] = (
                    f"<https://github.example.test/user/repos?page={page + 1}>"
                    '; rel="next"'
                )
            return StubResponse(items, response_headers)

        if path.startswith("/repositories/"):
            repository_id = path.removeprefix("/repositories/")
            repository = next(
                (
                    item
                    for item in self.repositories_by_token.get(token, [])
                    if str(item.get("id")) == repository_id
                ),
                None,
            )
            if repository is None:
                raise self._error(request.full_url, 404)
            return StubResponse(repository)

        if path.startswith("/repos/"):
            parts = path.split("/")
            if len(parts) >= 5 and parts[4] == "branches":
                owner = unquote(parts[2])
                name = unquote(parts[3])
                repository = None
                for item in self.repositories_by_token.get(token, []):
                    owner_payload = item.get("owner")
                    if (
                        isinstance(owner_payload, dict)
                        and owner_payload.get("login") == owner
                        and item.get("name") == name
                    ):
                        repository = item
                        break
                if repository is None:
                    raise self._error(request.full_url, 404)
                repository_id = str(repository["id"])
                branch_name = unquote("/".join(parts[5:])) if len(parts) > 5 else None
                branches = self.branches_by_repository.get(repository_id, [])
                if branch_name is None:
                    query = parse_qs(parsed.query)
                    page = int(query.get("page", ["1"])[0])
                    page_size = int(query.get("per_page", ["50"])[0])
                    start = (page - 1) * page_size
                    return StubResponse(branches[start : start + page_size])
                branch = next(
                    (item for item in branches if item.get("name") == branch_name),
                    None,
                )
                if branch is None:
                    raise self._error(request.full_url, 404)
                return StubResponse(branch)

        raise self._error(request.full_url, 404)

    def install(self, monkeypatch) -> None:
        monkeypatch.setattr("external_repositories.service.urlopen", self)

    @staticmethod
    def _error(url: str, status_code: int) -> HTTPError:
        return HTTPError(
            url,
            status_code,
            "synthetic provider failure",
            Message(),
            BytesIO(b"synthetic provider response"),
        )
