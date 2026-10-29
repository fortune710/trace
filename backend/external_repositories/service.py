"""Provider repository access, branch operations, and OAuth provisioning."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import random
import re
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Self
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from uuid import UUID

import httpx
import sqlalchemy as sa
from redis.exceptions import RedisError

from auth.config import AuthSettings
from auth.credential_service import (
    CredentialNotFound,
    CredentialService,
    CredentialServiceError,
)
from auth.errors import (
    BranchConflict,
    BranchNotFound,
    GithubAuthorizationRequired,
    ProviderRateLimited,
    ProviderUnavailable,
    RepositoryInvalidRequest,
    RepositoryNotFound,
    UnsupportedSource,
)
from credentials.models import CredentialProvider
from db.rls import principal_transaction
from db.types import RepositoryProvider, RepositorySource
from external_repositories.models import ExternalRepository
from resources.services import provision_external_repository

__all__ = [
    "BranchRecord",
    "CreatedBranch",
    "GitHubClient",
    "GitHubRequestLogContext",
    "RepositoryPageResult",
    "RepositoryRecord",
    "RepositoryService",
    "ReviewGitHubSourceAccess",
    "ReviewSourceFileError",
    "invalidate_repository_catalog",
    "provision_external_repository",
]

_GITHUB_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
_GITHUB_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,18}$")
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_MAX_REVIEW_FILE_BYTES = 512 * 1024
_GITHUB_API_VERSION = "2022-11-28"
_CATALOG_CACHE_LIMIT = 100
_CATALOG_CACHE_TTL_SECONDS = 300
_CATALOG_VERSION_TTL_SECONDS = 600
logger = logging.getLogger("trace.repositories")


@dataclass(frozen=True)
class RepositoryRecord:
    repository_id: str
    owner_login: str
    name: str
    full_name: str
    visibility: str
    private: bool
    default_branch: str | None
    web_url: str


@dataclass(frozen=True)
class BranchRecord:
    repository_id: str
    name: str
    commit_sha: str
    protected: bool


@dataclass(frozen=True)
class CreatedBranch:
    source: RepositoryProvider
    repository_id: str
    name: str
    commit_sha: str


@dataclass(frozen=True)
class PublishedPullRequest:
    url: str
    number: int
    is_merged: bool


@dataclass(frozen=True, slots=True)
class GitHubRequestLogContext:
    """Correlation fields attached to execution-worker GitHub request logs."""

    review_id: UUID
    review_agent_id: UUID | None = None
    attempt_id: UUID | None = None


@dataclass(frozen=True)
class RepositoryPageResult[T]:
    items: list[T]
    next_page: int | None


class RepositoryCatalogCache:
    """Fail-open cache containing only safe, owner-scoped provider metadata."""

    def __init__(self, redis_client: Any) -> None:
        self._redis = redis_client

    async def version(
        self, *, owner_id: UUID, provider: RepositoryProvider
    ) -> str | None:
        try:
            value = await self._redis.get(_catalog_version_key(owner_id, provider))
        except RedisError:
            return None
        if value is None:
            return "0"
        if isinstance(value, bytes):
            value = value.decode("ascii", errors="ignore")
        return value if isinstance(value, str) and value.isdecimal() else "0"

    async def repositories(
        self,
        *,
        owner_id: UUID,
        provider: RepositoryProvider,
        connection_id: UUID,
        version: str,
    ) -> list[RepositoryRecord] | None:
        return await self._read_records(
            _repository_catalog_key(owner_id, provider, connection_id, version),
            RepositoryRecord,
        )

    async def branches(
        self,
        *,
        owner_id: UUID,
        provider: RepositoryProvider,
        connection_id: UUID,
        version: str,
        repository_identifier: str,
    ) -> list[BranchRecord] | None:
        return await self._read_records(
            _branch_catalog_key(
                owner_id, provider, connection_id, version, repository_identifier
            ),
            BranchRecord,
        )

    async def store_repositories(
        self,
        *,
        owner_id: UUID,
        provider: RepositoryProvider,
        connection_id: UUID,
        version: str,
        records: list[RepositoryRecord],
    ) -> None:
        await self._write_records(
            _repository_catalog_key(owner_id, provider, connection_id, version), records
        )

    async def store_branches(
        self,
        *,
        owner_id: UUID,
        provider: RepositoryProvider,
        connection_id: UUID,
        version: str,
        repository_identifier: str,
        records: list[BranchRecord],
    ) -> None:
        await self._write_records(
            _branch_catalog_key(
                owner_id, provider, connection_id, version, repository_identifier
            ),
            records,
        )

    async def _read_records(self, key: str, record_type):
        try:
            raw = await self._redis.get(key)
        except RedisError:
            return None
        if raw is None:
            return None
        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            payload = json.loads(raw)
            items = payload["items"]
            if not isinstance(items, list) or len(items) > _CATALOG_CACHE_LIMIT:
                return None
            return [record_type(**item) for item in items]
        except (KeyError, TypeError, UnicodeDecodeError, ValueError):
            return None

    async def _write_records(
        self, key: str, records: list[RepositoryRecord] | list[BranchRecord]
    ) -> None:
        payload = json.dumps(
            {"items": [record.__dict__ for record in records]},
            separators=(",", ":"),
        )
        try:
            await self._redis.set(key, payload, ex=_CATALOG_CACHE_TTL_SECONDS)
        except RedisError:
            return


class RepositoryProviderError(RuntimeError):
    def __init__(
        self,
        *,
        kind: str,
        retry_after_seconds: int | None = None,
    ) -> None:
        self.kind = kind
        self.retry_after_seconds = retry_after_seconds
        super().__init__(kind)


class ReviewSourceFileError(ValueError):
    """A safe, expected failure while reading one immutable source file."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class GitHubClient:
    """Response-validating GitHub REST adapter with no secret logging."""

    def __init__(self, *, base_url: str, timeout_seconds: float = 10.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def list_repositories(
        self,
        *,
        access_token: str,
        page: int,
        page_size: int,
    ) -> RepositoryPageResult[RepositoryRecord]:
        return self._list_repositories_page(
            access_token=access_token,
            page=page,
            page_size=page_size,
        )

    def _list_repositories_page(
        self, *, access_token: str, page: int, page_size: int
    ) -> RepositoryPageResult[RepositoryRecord]:
        parameters = urlencode(
            {
                "visibility": "all",
                "affiliation": "owner,collaborator,organization_member",
                "sort": "updated",
                "direction": "desc",
                "per_page": page_size,
                "page": page,
            }
        )
        payload, headers = self._request_json(
            method="GET", path=f"/user/repos?{parameters}", access_token=access_token
        )
        if not isinstance(payload, list):
            raise RepositoryProviderError(kind="malformed_response")
        items = [self._repository_record(item) for item in payload]
        return RepositoryPageResult(
            items=items,
            next_page=_next_page(headers, page, len(items) == page_size),
        )

    def get_repository(
        self, *, access_token: str, repository_identifier: str
    ) -> RepositoryRecord:
        payload, _headers = self._request_json(
            method="GET",
            path=f"/repositories/{repository_identifier}",
            access_token=access_token,
        )
        return self._repository_record(payload)

    def list_paths_at_revision(
        self,
        *,
        access_token: str,
        repository: RepositoryRecord,
        revision: str,
        path_prefix: str | None,
        max_results: int,
    ) -> tuple[list[str], bool]:
        """List file paths from exactly one immutable Git commit."""
        if not _GITHUB_SHA.fullmatch(revision) or not 1 <= max_results <= 500:
            raise RepositoryProviderError(kind="malformed_response")
        payload, _headers = self._request_json(
            method="GET",
            path=(
                f"/repos/{quote(repository.owner_login, safe='')}/"
                f"{quote(repository.name, safe='')}/git/trees/{revision}?recursive=1"
            ),
            access_token=access_token,
        )
        if not isinstance(payload, dict) or payload.get("truncated") is True:
            raise RepositoryProviderError(kind="malformed_response")
        entries = payload.get("tree")
        if not isinstance(entries, list):
            raise RepositoryProviderError(kind="malformed_response")
        normalized_prefix = _review_path_prefix(path_prefix)
        paths: list[str] = []
        has_more = False
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("type") != "blob":
                continue
            path = entry.get("path")
            if not isinstance(path, str) or not _is_safe_review_path(path):
                raise RepositoryProviderError(kind="malformed_response")
            if normalized_prefix and not path.startswith(normalized_prefix):
                continue
            if len(paths) == max_results:
                has_more = True
                break
            paths.append(path)
        return paths, has_more

    def read_file_at_revision(
        self,
        *,
        access_token: str,
        repository: RepositoryRecord,
        revision: str,
        path: str,
    ) -> str:
        """Read one UTF-8 text file from exactly one immutable Git commit."""
        if not _GITHUB_SHA.fullmatch(revision) or not _is_safe_review_path(path):
            raise RepositoryProviderError(kind="malformed_response")
        payload, _headers = self._request_json(
            method="GET",
            path=(
                f"/repos/{quote(repository.owner_login, safe='')}/"
                f"{quote(repository.name, safe='')}/contents/"
                f"{quote(path, safe='/')}?ref={revision}"
            ),
            access_token=access_token,
        )
        if not isinstance(payload, dict) or payload.get("type") != "file":
            raise RepositoryProviderError(kind="malformed_response")
        encoded_content = payload.get("content")
        encoding = payload.get("encoding")
        if not isinstance(encoded_content, str) or encoding != "base64":
            raise RepositoryProviderError(kind="malformed_response")
        try:
            content = base64.b64decode(
                "".join(encoded_content.splitlines()), validate=True
            )
        except (ValueError, UnicodeEncodeError) as error:
            raise RepositoryProviderError(kind="malformed_response") from error
        if len(content) > _MAX_REVIEW_FILE_BYTES:
            raise RepositoryProviderError(kind="malformed_response")
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise RepositoryProviderError(kind="malformed_response") from error

    def list_branches(
        self,
        *,
        access_token: str,
        repository: RepositoryRecord,
        page: int,
        page_size: int,
    ) -> RepositoryPageResult[BranchRecord]:
        return self._list_branches_page(
            access_token=access_token,
            repository=repository,
            page=page,
            page_size=page_size,
        )

    def _list_branches_page(
        self,
        *,
        access_token: str,
        repository: RepositoryRecord,
        page: int,
        page_size: int,
    ) -> RepositoryPageResult[BranchRecord]:
        parameters = urlencode({"per_page": page_size, "page": page})
        payload, headers = self._request_json(
            method="GET",
            path=(
                f"/repos/{quote(repository.owner_login, safe='')}/"
                f"{quote(repository.name, safe='')}/branches?{parameters}"
            ),
            access_token=access_token,
        )
        if not isinstance(payload, list):
            raise RepositoryProviderError(kind="malformed_response")
        items = [
            self._branch_record(item, repository.repository_id) for item in payload
        ]
        return RepositoryPageResult(
            items=items,
            next_page=_next_page(headers, page, len(items) == page_size),
        )

    def get_branch(
        self,
        *,
        access_token: str,
        repository: RepositoryRecord,
        branch_name: str,
    ) -> BranchRecord:
        payload, _headers = self._request_json(
            method="GET",
            path=(
                f"/repos/{quote(repository.owner_login, safe='')}/"
                f"{quote(repository.name, safe='')}/branches/"
                f"{quote(branch_name, safe='')}"
            ),
            access_token=access_token,
        )
        return self._branch_record(payload, repository.repository_id)

    def create_branch(
        self,
        *,
        access_token: str,
        repository: RepositoryRecord,
        branch_name: str,
        base_revision: str,
    ) -> CreatedBranch:
        payload, _headers = self._request_json(
            method="POST",
            path=(
                f"/repos/{quote(repository.owner_login, safe='')}/"
                f"{quote(repository.name, safe='')}/git/refs"
            ),
            access_token=access_token,
            body={"ref": f"refs/heads/{branch_name}", "sha": base_revision},
        )
        if not isinstance(payload, dict):
            raise RepositoryProviderError(kind="malformed_response")
        ref = payload.get("ref")
        obj = payload.get("object")
        sha = obj.get("sha") if isinstance(obj, dict) else None
        if (
            ref != f"refs/heads/{branch_name}"
            or not isinstance(sha, str)
            or not _GITHUB_SHA.fullmatch(sha)
        ):
            raise RepositoryProviderError(kind="malformed_response")
        return CreatedBranch(
            source=RepositoryProvider.GITHUB,
            repository_id=repository.repository_id,
            name=branch_name,
            commit_sha=sha,
        )

    def authenticated_identity(self, *, access_token: str) -> tuple[str, str]:
        payload, _headers = self._request_json(
            method="GET", path="/user", access_token=access_token
        )
        if not isinstance(payload, dict):
            raise RepositoryProviderError(kind="malformed_response")
        login, user_id = payload.get("login"), payload.get("id")
        email = payload.get("email")
        if not isinstance(login, str) or not login or not isinstance(user_id, int):
            raise RepositoryProviderError(kind="malformed_response")
        if not isinstance(email, str) or not email:
            email = f"{user_id}+{login}@users.noreply.github.com"
        return login, email

    def find_pull_request(
        self, *, access_token: str, repository: RepositoryRecord, branch_name: str
    ) -> PublishedPullRequest | None:
        payload, _headers = self._request_json(
            method="GET",
            path=(
                f"/repos/{quote(repository.owner_login, safe='')}/"
                f"{quote(repository.name, safe='')}/pulls?state=all&head="
                f"{quote(repository.owner_login + ':' + branch_name, safe='')}"
            ),
            access_token=access_token,
        )
        if not isinstance(payload, list):
            raise RepositoryProviderError(kind="malformed_response")
        if not payload:
            return None
        return self._pull_request(payload[0])

    def create_pull_request(
        self,
        *,
        access_token: str,
        repository: RepositoryRecord,
        branch_name: str,
        base_branch: str,
        title: str,
        body: str,
    ) -> PublishedPullRequest:
        payload, _headers = self._request_json(
            method="POST",
            path=(
                f"/repos/{quote(repository.owner_login, safe='')}/"
                f"{quote(repository.name, safe='')}/pulls"
            ),
            access_token=access_token,
            body={
                "head": branch_name,
                "base": base_branch,
                "title": title,
                "body": body,
            },
        )
        return self._pull_request(payload)

    @staticmethod
    def _pull_request(payload: object) -> PublishedPullRequest:
        if not isinstance(payload, dict):
            raise RepositoryProviderError(kind="malformed_response")
        url, number = payload.get("html_url"), payload.get("number")
        merged = payload.get("merged")
        merged_at = payload.get("merged_at")
        if (
            not isinstance(url, str)
            or not url
            or not isinstance(number, int)
            or number < 1
        ):
            raise RepositoryProviderError(kind="malformed_response")
        return PublishedPullRequest(
            url=url, number=number, is_merged=merged is True or merged_at is not None
        )

    def _request_json(
        self,
        *,
        method: str,
        path: str,
        access_token: str,
        body: dict[str, object] | None = None,
    ) -> tuple[object, Any]:
        request_body = (
            json.dumps(body, separators=(",", ":")).encode("utf-8")
            if body is not None
            else None
        )
        request = Request(
            f"{self._base_url}{path}",
            data=request_body,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": _GITHUB_API_VERSION,
                "User-Agent": "Trace/1.0",
            },
        )
        _log_github_api_request(
            method=method,
            path=path,
            request_body_bytes=len(request_body) if request_body is not None else 0,
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                raw = response.read(_MAX_RESPONSE_BYTES + 1)
                headers = response.headers
                _log_github_api_response(
                    method=method,
                    path=path,
                    status_code=_response_status_code(response),
                    response_body_bytes=len(raw),
                )
        except HTTPError as error:
            _log_github_api_failure(
                method=method,
                path=path,
                error=error,
            )
            retry_after = _retry_after(error.headers)
            remaining = error.headers.get("X-RateLimit-Remaining")
            if error.code == 429 or (error.code == 403 and remaining == "0"):
                kind = "rate_limited"
            elif error.code in {401, 403}:
                kind = "authorization"
            elif error.code == 404:
                kind = "not_found"
            elif error.code == 409:
                kind = "conflict"
            else:
                kind = "unavailable"
            raise RepositoryProviderError(
                kind=kind, retry_after_seconds=retry_after
            ) from error
        except (URLError, TimeoutError, OSError) as error:
            _log_github_api_failure(
                method=method,
                path=path,
                error=error,
            )
            raise RepositoryProviderError(kind="unavailable") from error
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise RepositoryProviderError(kind="malformed_response")
        try:
            return json.loads(raw.decode("utf-8")), headers
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RepositoryProviderError(kind="malformed_response") from error

    @staticmethod
    def _repository_record(payload: object) -> RepositoryRecord:
        if not isinstance(payload, dict):
            raise RepositoryProviderError(kind="malformed_response")
        repository_id = payload.get("id")
        owner = payload.get("owner")
        owner_login = owner.get("login") if isinstance(owner, dict) else None
        name = payload.get("name")
        full_name = payload.get("full_name")
        private = payload.get("private")
        visibility = payload.get("visibility")
        default_branch = payload.get("default_branch")
        web_url = payload.get("html_url")
        if (
            not isinstance(repository_id, int)
            or repository_id <= 0
            or not isinstance(owner_login, str)
            or not owner_login
            or not isinstance(name, str)
            or not name
            or not isinstance(full_name, str)
            or not full_name
            or not isinstance(private, bool)
            or not isinstance(web_url, str)
            or not web_url
        ):
            raise RepositoryProviderError(kind="malformed_response")
        if not isinstance(visibility, str) or not visibility:
            visibility = "private" if private else "public"
        if default_branch is not None and not isinstance(default_branch, str):
            raise RepositoryProviderError(kind="malformed_response")
        return RepositoryRecord(
            repository_id=str(repository_id),
            owner_login=owner_login,
            name=name,
            full_name=full_name,
            visibility=visibility,
            private=private,
            default_branch=default_branch,
            web_url=web_url,
        )

    @staticmethod
    def _branch_record(payload: object, repository_id: str) -> BranchRecord:
        if not isinstance(payload, dict):
            raise RepositoryProviderError(kind="malformed_response")
        name = payload.get("name")
        commit = payload.get("commit")
        sha = commit.get("sha") if isinstance(commit, dict) else None
        protected = payload.get("protected", False)
        if (
            not isinstance(name, str)
            or not name
            or not isinstance(sha, str)
            or not _GITHUB_SHA.fullmatch(sha)
            or not isinstance(protected, bool)
        ):
            raise RepositoryProviderError(kind="malformed_response")
        return BranchRecord(
            repository_id=repository_id,
            name=name,
            commit_sha=sha,
            protected=protected,
        )


class ReviewGitHubSourceAccess:
    """Review-scoped GitHub source reader shared by all runtime tools.

    This deliberately sits beside, rather than replaces, :class:`GitHubClient`.
    Repository-browsing endpoints retain their existing request behaviour; only
    execution-worker reads share a connection pool, metadata cache, and request
    budget.
    """

    def __init__(
        self,
        *,
        repository_service: RepositoryService,
        owner_id: UUID,
        repository_identifier: str,
        revision: str,
        max_concurrent_requests: int = 2,
        max_attempts: int = 3,
        retry_base_seconds: float = 0.25,
        retry_max_seconds: float = 2.0,
        retry_after_max_seconds: float = 30.0,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[float, float], float] = random.uniform,
    ) -> None:
        if max_concurrent_requests < 1:
            raise ValueError("max_concurrent_requests must be positive")
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if retry_base_seconds < 0 or retry_max_seconds < retry_base_seconds:
            raise ValueError("invalid GitHub retry configuration")

        self._repository_service = repository_service
        self._owner_id = owner_id
        self._repository_identifier = _validate_repository_identifier(
            repository_identifier
        )
        self._revision = revision
        self._max_attempts = max_attempts
        self._retry_base_seconds = retry_base_seconds
        self._retry_max_seconds = retry_max_seconds
        self._retry_after_max_seconds = retry_after_max_seconds
        self._semaphore = threading.BoundedSemaphore(max_concurrent_requests)
        self._metadata_lock = threading.Lock()
        self._credential_lock = threading.Lock()
        self._repository: RepositoryRecord | None = None
        self._access_token: str | None = None
        self._sleep = sleep
        self._jitter = jitter
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=repository_service._settings.github_api_url.rstrip("/"),
            timeout=10.0,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": _GITHUB_API_VERSION,
                "User-Agent": "Trace/1.0",
            },
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def list_paths(
        self,
        *,
        path_prefix: str | None,
        max_results: int,
        log_context: GitHubRequestLogContext,
    ) -> tuple[list[str], bool]:
        try:
            repository = self._repository_metadata(log_context=log_context)
            if not _GITHUB_SHA.fullmatch(self._revision) or not 1 <= max_results <= 500:
                raise RepositoryProviderError(kind="malformed_response")
            payload, _headers = self._request_json(
                method="GET",
                path=(
                    f"/repos/{quote(repository.owner_login, safe='')}/"
                    f"{quote(repository.name, safe='')}/git/trees/"
                    f"{self._revision}?recursive=1"
                ),
                log_context=log_context,
            )
            if not isinstance(payload, dict) or payload.get("truncated") is True:
                raise RepositoryProviderError(kind="malformed_response")
            entries = payload.get("tree")
            if not isinstance(entries, list):
                raise RepositoryProviderError(kind="malformed_response")
            normalized_prefix = _review_path_prefix(path_prefix)
            paths: list[str] = []
            has_more = False
            for entry in entries:
                if not isinstance(entry, dict) or entry.get("type") != "blob":
                    continue
                path = entry.get("path")
                if not isinstance(path, str) or not _is_safe_review_path(path):
                    raise RepositoryProviderError(kind="malformed_response")
                if normalized_prefix and not path.startswith(normalized_prefix):
                    continue
                if len(paths) == max_results:
                    has_more = True
                    break
                paths.append(path)
            return paths, has_more
        except RepositoryProviderError as error:
            _log_provider_call("list_paths", error.kind, error=error)
            raise _provider_error(error, operation="review_source") from error

    def read_file(
        self,
        *,
        path: str,
        log_context: GitHubRequestLogContext,
    ) -> str:
        try:
            repository = self._repository_metadata(log_context=log_context)
            if not _GITHUB_SHA.fullmatch(self._revision) or not _is_safe_review_path(
                path
            ):
                raise RepositoryProviderError(kind="malformed_response")
            try:
                payload, _headers = self._request_json(
                    method="GET",
                    path=(
                        f"/repos/{quote(repository.owner_login, safe='')}/"
                        f"{quote(repository.name, safe='')}/contents/"
                        f"{quote(path, safe='/')}?ref={self._revision}"
                    ),
                    log_context=log_context,
                )
            except RepositoryProviderError as error:
                if error.kind == "not_found":
                    raise ReviewSourceFileError("path_not_found") from error
                raise
            if not isinstance(payload, dict) or payload.get("type") != "file":
                raise RepositoryProviderError(kind="malformed_response")
            encoded_content = payload.get("content")
            encoding = payload.get("encoding")
            if not isinstance(encoded_content, str) or encoding != "base64":
                raise RepositoryProviderError(kind="malformed_response")
            try:
                content = base64.b64decode(
                    "".join(encoded_content.splitlines()), validate=True
                )
            except (ValueError, UnicodeEncodeError) as error:
                raise RepositoryProviderError(kind="malformed_response") from error
            if len(content) > _MAX_REVIEW_FILE_BYTES:
                raise ReviewSourceFileError("file_too_large")
            try:
                return content.decode("utf-8")
            except UnicodeDecodeError as error:
                raise ReviewSourceFileError("file_not_utf8") from error
        except ReviewSourceFileError:
            raise
        except RepositoryProviderError as error:
            _log_provider_call("read_file", error.kind, error=error)
            raise _provider_error(error, operation="review_source") from error

    def validate_diff(
        self,
        *,
        diff: str,
        log_context: GitHubRequestLogContext,
    ) -> bool:
        """Check that a diff applies cleanly to this reader's immutable revision."""

        try:
            repository = self._repository_metadata(log_context=log_context)
            if not _GITHUB_SHA.fullmatch(self._revision):
                raise RepositoryProviderError(kind="malformed_response")
            token = self._token()
            git_authorization = base64.b64encode(
                f"x-access-token:{token}".encode()
            ).decode("ascii")
            environment = {
                **os.environ,
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_CONFIG_COUNT": "2",
                "GIT_CONFIG_KEY_0": "http.extraHeader",
                "GIT_CONFIG_VALUE_0": f"Authorization: Basic {git_authorization}",
                "GIT_CONFIG_KEY_1": "core.hooksPath",
                "GIT_CONFIG_VALUE_1": "/dev/null",
            }
            with tempfile.TemporaryDirectory(
                prefix="trace-diff-validation-"
            ) as directory:
                patch_path = f"{directory}/change.patch"
                with open(
                    patch_path, "w", encoding="utf-8", newline="\n"
                ) as patch_file:
                    patch_file.write(diff)
                for arguments in (
                    ("git", "init", "-q"),
                    ("git", "remote", "add", "origin", f"{repository.web_url}.git"),
                    ("git", "fetch", "--depth=1", "origin", self._revision),
                    ("git", "checkout", "-q", "--detach", "FETCH_HEAD"),
                ):
                    try:
                        subprocess.run(
                            arguments,
                            cwd=directory,
                            env=environment,
                            check=True,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=60,
                        )
                    except (OSError, subprocess.CalledProcessError) as error:
                        raise RepositoryProviderError(kind="unavailable") from error
                result = subprocess.run(
                    (
                        "git",
                        "apply",
                        "--check",
                        "--whitespace=error",
                        patch_path,
                    ),
                    cwd=directory,
                    env=environment,
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=60,
                )
                return result.returncode == 0
        except RepositoryProviderError as error:
            _log_provider_call("validate_diff", error.kind, error=error)
            raise _provider_error(error, operation="review_source") from error
        except OSError as error:
            _log_provider_call("validate_diff", "unavailable", error=error)
            raise ProviderUnavailable() from error

    def _repository_metadata(
        self, *, log_context: GitHubRequestLogContext
    ) -> RepositoryRecord:
        if self._repository is not None:
            return self._repository
        with self._metadata_lock:
            if self._repository is None:
                payload, _headers = self._request_json(
                    method="GET",
                    path=f"/repositories/{self._repository_identifier}",
                    log_context=log_context,
                )
                self._repository = GitHubClient._repository_record(payload)
            return self._repository

    def _token(self) -> str:
        if self._access_token is not None:
            return self._access_token
        with self._credential_lock:
            if self._access_token is None:
                self._access_token = self._repository_service._access_token(
                    owner_id=self._owner_id,
                    provider=RepositoryProvider.GITHUB,
                )
            return self._access_token

    def _request_json(
        self,
        *,
        method: str,
        path: str,
        log_context: GitHubRequestLogContext,
    ) -> tuple[object, httpx.Headers]:
        # The review reader only makes GET requests. Keep that invariant local
        # so retry policy cannot accidentally be expanded to mutations.
        if method != "GET":
            raise ValueError("review source requests must be GET")
        for request_attempt in range(1, self._max_attempts + 1):
            try:
                status_code, response_headers, response_body = self._send_once(
                    method=method,
                    path=path,
                    log_context=log_context,
                    request_attempt=request_attempt,
                )
            except (httpx.TransportError, TimeoutError, OSError) as error:
                _log_github_api_failure(
                    method=method,
                    path=path,
                    error=error,
                    log_context=log_context,
                    request_attempt=request_attempt,
                )
                if request_attempt == self._max_attempts:
                    raise RepositoryProviderError(kind="unavailable") from error
                self._sleep_before_retry(
                    method=method,
                    path=path,
                    log_context=log_context,
                    request_attempt=request_attempt,
                    error=error,
                )
                continue

            _log_github_api_response(
                method=method,
                path=path,
                status_code=status_code,
                response_body_bytes=len(response_body),
                log_context=log_context,
                request_attempt=request_attempt,
            )
            if len(response_body) > _MAX_RESPONSE_BYTES:
                raise RepositoryProviderError(kind="malformed_response")
            if 200 <= status_code < 300:
                try:
                    return json.loads(response_body.decode("utf-8")), response_headers
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise RepositoryProviderError(kind="malformed_response") from error

            retryable = status_code == 408 or status_code == 429 or status_code >= 500
            if retryable and request_attempt < self._max_attempts:
                self._sleep_before_retry(
                    method=method,
                    path=path,
                    log_context=log_context,
                    request_attempt=request_attempt,
                    status_code=status_code,
                    retry_after_seconds=_retry_after(response_headers),
                )
                continue
            if status_code == 429:
                raise RepositoryProviderError(
                    kind="rate_limited",
                    retry_after_seconds=_retry_after(response_headers),
                )
            if status_code in {401, 403}:
                if response_headers.get("X-RateLimit-Remaining") == "0":
                    raise RepositoryProviderError(
                        kind="rate_limited",
                        retry_after_seconds=_retry_after(response_headers),
                    )
                raise RepositoryProviderError(kind="authorization")
            if status_code == 404:
                raise RepositoryProviderError(kind="not_found")
            if status_code == 409:
                raise RepositoryProviderError(kind="conflict")
            if retryable:
                raise RepositoryProviderError(kind="unavailable")
            raise RepositoryProviderError(kind="malformed_response")

        raise AssertionError("unreachable request retry state")

    def _send_once(
        self,
        *,
        method: str,
        path: str,
        log_context: GitHubRequestLogContext,
        request_attempt: int,
    ) -> tuple[int, httpx.Headers, bytes]:
        _log_github_api_request(
            method=method,
            path=path,
            request_body_bytes=0,
            log_context=log_context,
            request_attempt=request_attempt,
        )
        with (
            self._semaphore,
            self._client.stream(
                method,
                path,
                headers={"Authorization": f"Bearer {self._token()}"},
            ) as response,
        ):
            response_body = bytearray()
            for chunk in response.iter_bytes(chunk_size=64 * 1024):
                remaining = _MAX_RESPONSE_BYTES + 1 - len(response_body)
                if len(chunk) > remaining:
                    response_body.extend(chunk[:remaining])
                    break
                response_body.extend(chunk)
            return response.status_code, response.headers, bytes(response_body)

    def _sleep_before_retry(
        self,
        *,
        method: str,
        path: str,
        log_context: GitHubRequestLogContext,
        request_attempt: int,
        status_code: int | None = None,
        retry_after_seconds: int | None = None,
        error: Exception | None = None,
    ) -> None:
        backoff_seconds = min(
            self._retry_max_seconds,
            self._retry_base_seconds * (2 ** (request_attempt - 1)),
        )
        if retry_after_seconds is not None and status_code == 429:
            delay_seconds = min(
                float(retry_after_seconds), self._retry_after_max_seconds
            )
        else:
            delay_seconds = self._jitter(0, backoff_seconds)
        fields: dict[str, object] = {
            "event": "github_api_retry_scheduled",
            "method": method,
            "request_attempt": request_attempt,
            "request_path": path,
            "retry_delay_ms": round(delay_seconds * 1000),
        }
        fields.update(_github_log_context_fields(log_context))
        if status_code is not None:
            fields["status_code"] = status_code
        if error is not None:
            fields["transport_error_class"] = type(error).__name__
        logger.info(json.dumps(fields, default=str, sort_keys=True))
        self._sleep(delay_seconds)


class RepositoryService:
    def __init__(
        self,
        *,
        engine,
        credential_service: CredentialService,
        settings: AuthSettings,
        github_client: GitHubClient | None = None,
    ) -> None:
        self._engine = engine
        self._credential_service = credential_service
        self._settings = settings
        self._github_client = github_client or GitHubClient(
            base_url=settings.github_api_url
        )

    def list_repositories(
        self,
        *,
        owner_id: UUID,
        source: str,
        page: int,
        page_size: int,
    ) -> RepositoryPageResult[RepositoryRecord]:
        provider = _provider(source)
        token = self._access_token(owner_id=owner_id, provider=provider)
        try:
            result = self._github_client.list_repositories(
                access_token=token, page=page, page_size=page_size
            )
            _log_provider_call("list_repositories", "accepted")
            return result
        except RepositoryProviderError as error:
            _log_provider_call("list_repositories", error.kind)
            raise _provider_auth_error(error) from error

    async def search_repositories(
        self,
        *,
        owner_id: UUID,
        source: str,
        query: str,
        page: int,
        page_size: int,
        redis_client: Any,
    ) -> RepositoryPageResult[RepositoryRecord]:
        """Filter the first 100 owner-accessible repositories from a safe cache."""

        provider = _provider(source)
        query = query.strip().casefold()
        connection_id, token = await asyncio.to_thread(
            self._catalog_connection, owner_id=owner_id, provider=provider
        )
        if redis_client is None:
            return await asyncio.to_thread(
                self._search_repositories_from_provider,
                token=token,
                query=query,
                page=page,
                page_size=page_size,
            )
        cache = RepositoryCatalogCache(redis_client)
        version = await cache.version(owner_id=owner_id, provider=provider)
        if version is None:
            return await asyncio.to_thread(
                self._search_repositories_from_provider,
                token=token,
                query=query,
                page=page,
                page_size=page_size,
            )

        records = await cache.repositories(
            owner_id=owner_id,
            provider=provider,
            connection_id=connection_id,
            version=version,
        )
        if records is None:
            records = await asyncio.to_thread(
                self._repository_catalog_from_provider, token=token
            )
            await cache.store_repositories(
                owner_id=owner_id,
                provider=provider,
                connection_id=connection_id,
                version=version,
                records=records,
            )
        return _filtered_page(
            records,
            page=page,
            page_size=page_size,
            matches=lambda record: (
                query in record.name.casefold() or query in record.full_name.casefold()
            ),
        )

    def list_branches(
        self,
        *,
        owner_id: UUID,
        source: str,
        repository_identifier: str,
        page: int,
        page_size: int,
    ) -> RepositoryPageResult[BranchRecord]:
        provider = _provider(source)
        repository_identifier = _validate_repository_identifier(repository_identifier)
        token = self._access_token(owner_id=owner_id, provider=provider)
        try:
            repository = self._github_client.get_repository(
                access_token=token, repository_identifier=repository_identifier
            )
            result = self._github_client.list_branches(
                access_token=token,
                repository=repository,
                page=page,
                page_size=page_size,
            )
            _log_provider_call("list_branches", "accepted")
            return result
        except RepositoryProviderError as error:
            _log_provider_call("list_branches", error.kind)
            raise _provider_error(error, operation="repository") from error

    def list_paths(
        self,
        *,
        owner_id: UUID,
        repository_identifier: str,
        revision: str,
        path_prefix: str | None,
        max_results: int,
    ) -> tuple[list[str], bool]:
        """List bounded paths for an agent's immutable GitHub review target."""
        repository_identifier = _validate_repository_identifier(repository_identifier)
        token = self._access_token(
            owner_id=owner_id, provider=RepositoryProvider.GITHUB
        )
        try:
            repository = self._github_client.get_repository(
                access_token=token, repository_identifier=repository_identifier
            )
            return self._github_client.list_paths_at_revision(
                access_token=token,
                repository=repository,
                revision=revision,
                path_prefix=path_prefix,
                max_results=max_results,
            )
        except RepositoryProviderError as error:
            _log_provider_call("list_paths", error.kind)
            raise _provider_error(error, operation="review_source") from error

    def read_file(
        self,
        *,
        owner_id: UUID,
        repository_identifier: str,
        revision: str,
        path: str,
    ) -> str:
        """Read one bounded text file for an agent's immutable GitHub review target."""
        repository_identifier = _validate_repository_identifier(repository_identifier)
        token = self._access_token(
            owner_id=owner_id, provider=RepositoryProvider.GITHUB
        )
        try:
            repository = self._github_client.get_repository(
                access_token=token, repository_identifier=repository_identifier
            )
            return self._github_client.read_file_at_revision(
                access_token=token,
                repository=repository,
                revision=revision,
                path=path,
            )
        except RepositoryProviderError as error:
            _log_provider_call("read_file", error.kind, error=error)
            raise _provider_error(error, operation="review_source") from error

    def open_review_github_source_access(
        self,
        *,
        owner_id: UUID,
        repository_identifier: str,
        revision: str,
        max_concurrent_requests: int = 2,
        max_attempts: int = 3,
        retry_base_seconds: float = 0.25,
        retry_max_seconds: float = 2.0,
        retry_after_max_seconds: float = 30.0,
    ) -> ReviewGitHubSourceAccess:
        """Create one shared GitHub reader for a single review execution."""

        return ReviewGitHubSourceAccess(
            repository_service=self,
            owner_id=owner_id,
            repository_identifier=repository_identifier,
            revision=revision,
            max_concurrent_requests=max_concurrent_requests,
            max_attempts=max_attempts,
            retry_base_seconds=retry_base_seconds,
            retry_max_seconds=retry_max_seconds,
            retry_after_max_seconds=retry_after_max_seconds,
        )

    async def search_branches(
        self,
        *,
        owner_id: UUID,
        source: str,
        repository_identifier: str,
        query: str,
        page: int,
        page_size: int,
        redis_client: Any,
    ) -> RepositoryPageResult[BranchRecord]:
        """Filter the first 100 branches for an owner-accessible repository."""

        provider = _provider(source)
        query = query.strip().casefold()
        repository_identifier = _validate_repository_identifier(repository_identifier)
        connection_id, token = await asyncio.to_thread(
            self._catalog_connection, owner_id=owner_id, provider=provider
        )
        if redis_client is None:
            return await asyncio.to_thread(
                self._search_branches_from_provider,
                token=token,
                repository_identifier=repository_identifier,
                query=query,
                page=page,
                page_size=page_size,
            )
        cache = RepositoryCatalogCache(redis_client)
        version = await cache.version(owner_id=owner_id, provider=provider)
        if version is None:
            return await asyncio.to_thread(
                self._search_branches_from_provider,
                token=token,
                repository_identifier=repository_identifier,
                query=query,
                page=page,
                page_size=page_size,
            )

        records = await cache.branches(
            owner_id=owner_id,
            provider=provider,
            connection_id=connection_id,
            version=version,
            repository_identifier=repository_identifier,
        )
        if records is None:
            records = await asyncio.to_thread(
                self._branch_catalog_from_provider,
                token=token,
                repository_identifier=repository_identifier,
            )
            await cache.store_branches(
                owner_id=owner_id,
                provider=provider,
                connection_id=connection_id,
                version=version,
                repository_identifier=repository_identifier,
                records=records,
            )
        return _filtered_page(
            records,
            page=page,
            page_size=page_size,
            matches=lambda record: query in record.name.casefold(),
        )

    def connection_id(self, *, owner_id: UUID, source: str) -> UUID:
        provider = _provider(source)
        connection = _active_connection(
            self._engine, owner_id=owner_id, provider=provider
        )
        if connection is None:
            raise GithubAuthorizationRequired()
        return connection["id"]

    def resolve_branch(
        self,
        *,
        owner_id: UUID,
        source: str,
        repository_identifier: str,
        branch_name: str,
    ) -> tuple[RepositoryRecord, BranchRecord]:
        provider = _provider(source)
        repository_identifier = _validate_repository_identifier(repository_identifier)
        _validate_branch_name(branch_name)
        token = self._access_token(owner_id=owner_id, provider=provider)
        try:
            repository = self._github_client.get_repository(
                access_token=token, repository_identifier=repository_identifier
            )
        except RepositoryProviderError as error:
            _log_provider_call("resolve_repository", error.kind)
            raise _provider_error(error, operation="repository") from error

        try:
            branch = self._github_client.get_branch(
                access_token=token, repository=repository, branch_name=branch_name
            )
            _log_provider_call("resolve_branch", "accepted")
            return repository, branch
        except RepositoryProviderError as error:
            _log_provider_call("resolve_branch", error.kind)
            raise _provider_error(error, operation="branch") from error

    def create_branch(
        self,
        *,
        owner_id: UUID,
        source: str,
        repository_identifier: str,
        branch_name: str,
        base_revision: str,
    ) -> CreatedBranch:
        provider = _provider(source)
        repository_identifier = _validate_repository_identifier(repository_identifier)
        _validate_branch_name(branch_name)
        if not _GITHUB_SHA.fullmatch(base_revision):
            raise RepositoryInvalidRequest()
        token = self._access_token(owner_id=owner_id, provider=provider)
        try:
            repository = self._github_client.get_repository(
                access_token=token, repository_identifier=repository_identifier
            )
            result = self._github_client.create_branch(
                access_token=token,
                repository=repository,
                branch_name=branch_name,
                base_revision=base_revision,
            )
            _log_provider_call("create_branch", "accepted")
            return result
        except RepositoryProviderError as error:
            _log_provider_call("create_branch", error.kind)
            raise _provider_error(error, operation="branch_create") from error

    def publish_remediation_pull_request(
        self,
        *,
        owner_id: UUID,
        repository_identifier: str,
        source_revision: str,
        base_branch: str,
        remediation_id: UUID,
        diff: str,
        finding_title: str,
    ) -> PublishedPullRequest:
        """Apply a trusted persisted diff in an isolated checkout and open a GitHub PR."""
        token = self._access_token(
            owner_id=owner_id, provider=RepositoryProvider.GITHUB
        )
        try:
            repository = self._github_client.get_repository(
                access_token=token, repository_identifier=repository_identifier
            )
            branch_name = f"trace-fix/{remediation_id}"
            existing = self._github_client.find_pull_request(
                access_token=token, repository=repository, branch_name=branch_name
            )
            if existing is not None:
                return existing
            login, email = self._github_client.authenticated_identity(
                access_token=token
            )
            self._apply_and_push_patch(
                repository=repository,
                token=token,
                revision=source_revision,
                branch_name=branch_name,
                diff=diff,
                author_name=login,
                author_email=email,
            )
            return self._github_client.create_pull_request(
                access_token=token,
                repository=repository,
                branch_name=branch_name,
                base_branch=base_branch,
                title=f"Trace remediation: {finding_title.strip().replace(chr(10), ' ')[:180]}",
                body=f"Created by Trace for remediation `{remediation_id}`.",
            )
        except RepositoryProviderError as error:
            _log_provider_call("publish_remediation_pull_request", error.kind)
            raise _provider_error(error, operation="pull_request") from error

    @staticmethod
    def _apply_and_push_patch(
        *,
        repository: RepositoryRecord,
        token: str,
        revision: str,
        branch_name: str,
        diff: str,
        author_name: str,
        author_email: str,
    ) -> None:
        if not _GITHUB_SHA.fullmatch(revision) or not _is_safe_patch(diff):
            raise RepositoryInvalidRequest()
        with tempfile.TemporaryDirectory(prefix="trace-remediation-") as directory:
            patch_path = f"{directory}/change.patch"
            with open(patch_path, "w", encoding="utf-8", newline="\n") as patch_file:
                patch_file.write(diff)
            remote = f"{repository.web_url}.git"
            git_authorization = base64.b64encode(
                f"x-access-token:{token}".encode()
            ).decode("ascii")
            environment = {
                **os.environ,
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_CONFIG_COUNT": "2",
                "GIT_CONFIG_KEY_0": "http.extraHeader",
                "GIT_CONFIG_VALUE_0": f"Authorization: Basic {git_authorization}",
                "GIT_CONFIG_KEY_1": "core.hooksPath",
                "GIT_CONFIG_VALUE_1": "/dev/null",
            }

            def run(
                *arguments: str,
                invalid_patch: bool = False,
                allow_failure: bool = False,
            ) -> bool:
                try:
                    subprocess.run(
                        arguments,
                        cwd=directory,
                        env=environment,
                        check=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=60,
                    )
                except subprocess.CalledProcessError:
                    if allow_failure:
                        return False
                    if invalid_patch:
                        raise RepositoryInvalidRequest() from None
                    raise RepositoryProviderError(kind="unavailable") from None
                except OSError:
                    if allow_failure:
                        return False
                    raise RepositoryProviderError(kind="unavailable") from None
                return True

            run("git", "init", "-q")
            run("git", "remote", "add", "origin", remote)
            run("git", "fetch", "--depth=1", "origin", revision)
            run("git", "checkout", "-q", "-b", branch_name, "FETCH_HEAD")
            run(
                "git",
                "apply",
                "--check",
                "--whitespace=error",
                patch_path,
                invalid_patch=True,
            )
            run(
                "git",
                "apply",
                "--whitespace=error",
                patch_path,
                invalid_patch=True,
            )
            run("git", "add", "--all")
            run(
                "git",
                "-c",
                f"user.name={author_name}",
                "-c",
                f"user.email={author_email}",
                "commit",
                "-m",
                "Trace remediation",
            )
            if run(
                "git",
                "push",
                "origin",
                f"HEAD:refs/heads/{branch_name}",
                allow_failure=True,
            ):
                return

            # A process can fail after the remote accepts the push but before it
            # records the pull request. Verify the deterministic branch contains
            # this exact patch, then let the caller create or recover the PR.
            if not run(
                "git",
                "fetch",
                "--depth=1",
                "origin",
                f"refs/heads/{branch_name}",
                allow_failure=True,
            ):
                raise RepositoryProviderError(kind="unavailable")
            run("git", "checkout", "-q", "FETCH_HEAD")
            if not run(
                "git",
                "apply",
                "--reverse",
                "--check",
                "--whitespace=error",
                patch_path,
                allow_failure=True,
            ):
                raise RepositoryProviderError(kind="conflict")

    def _repository_catalog_from_provider(
        self, *, token: str
    ) -> list[RepositoryRecord]:
        try:
            result = self._github_client.list_repositories(
                access_token=token,
                page=1,
                page_size=_CATALOG_CACHE_LIMIT,
            )
            _log_provider_call("list_repositories", "accepted")
            return result.items
        except RepositoryProviderError as error:
            _log_provider_call("list_repositories", error.kind)
            raise _provider_auth_error(error) from error

    def _branch_catalog_from_provider(
        self, *, token: str, repository_identifier: str
    ) -> list[BranchRecord]:
        try:
            repository = self._github_client.get_repository(
                access_token=token, repository_identifier=repository_identifier
            )
            result = self._github_client.list_branches(
                access_token=token,
                repository=repository,
                page=1,
                page_size=_CATALOG_CACHE_LIMIT,
            )
            _log_provider_call("list_branches", "accepted")
            return result.items
        except RepositoryProviderError as error:
            _log_provider_call("list_branches", error.kind)
            raise _provider_error(error, operation="repository") from error

    def _search_repositories_from_provider(
        self, *, token: str, query: str, page: int, page_size: int
    ) -> RepositoryPageResult[RepositoryRecord]:
        records = self._repository_catalog_from_provider(token=token)
        return _filtered_page(
            records,
            page=page,
            page_size=page_size,
            matches=lambda record: (
                query in record.name.casefold() or query in record.full_name.casefold()
            ),
        )

    def _search_branches_from_provider(
        self,
        *,
        token: str,
        repository_identifier: str,
        query: str,
        page: int,
        page_size: int,
    ) -> RepositoryPageResult[BranchRecord]:
        records = self._branch_catalog_from_provider(
            token=token, repository_identifier=repository_identifier
        )
        return _filtered_page(
            records,
            page=page,
            page_size=page_size,
            matches=lambda record: query in record.name.casefold(),
        )

    def _catalog_connection(
        self, *, owner_id: UUID, provider: RepositoryProvider
    ) -> tuple[UUID, str]:
        if provider is not RepositoryProvider.GITHUB:
            raise UnsupportedSource()
        connection = _active_connection(
            self._engine, owner_id=owner_id, provider=provider
        )
        if connection is None:
            raise GithubAuthorizationRequired()
        return connection["id"], self._access_token(
            owner_id=owner_id, provider=provider
        )

    def _access_token(self, *, owner_id: UUID, provider: RepositoryProvider) -> str:
        if provider is not RepositoryProvider.GITHUB:
            raise UnsupportedSource()
        connection = _active_connection(
            self._engine, owner_id=owner_id, provider=provider
        )
        if connection is None:
            raise GithubAuthorizationRequired()
        try:
            metadata = self._credential_service.metadata(
                owner_id=owner_id, credential_id=connection["credential_id"]
            )
            if metadata.provider is not CredentialProvider.GITHUB:
                raise GithubAuthorizationRequired()
            payload = self._credential_service.decrypt_for_provider_call(
                owner_id=owner_id, credential_id=connection["credential_id"]
            )
        except (CredentialNotFound, CredentialServiceError):
            raise GithubAuthorizationRequired()

        from auth.oauth import (
            OAuthRejected,
            OAuthUnavailable,
            _github_access_token_expiration,
            refresh_github_credential,
        )

        expiration = _github_access_token_expiration(payload)
        if expiration is not None and not isinstance(expiration, datetime):
            raise GithubAuthorizationRequired()
        if expiration is not None and expiration <= datetime.now(UTC):
            try:
                payload = refresh_github_credential(
                    service=self._credential_service,
                    settings=self._settings,
                    owner_id=owner_id,
                    credential_id=connection["credential_id"],
                )
            except (OAuthRejected, CredentialServiceError):
                raise GithubAuthorizationRequired() from None
            except OAuthUnavailable as error:
                raise ProviderUnavailable() from error
        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise GithubAuthorizationRequired()
        return token


async def invalidate_repository_catalog(
    *, redis_client: Any, owner_id: UUID, source: RepositoryProvider
) -> None:
    """Version owner/provider catalog keys without scanning or deleting Redis keys."""

    try:
        version_key = _catalog_version_key(owner_id, source)
        await redis_client.incr(version_key)
        await redis_client.expire(version_key, _CATALOG_VERSION_TTL_SECONDS)
    except RedisError:
        return


def _catalog_version_key(owner_id: UUID, provider: RepositoryProvider) -> str:
    return f"trace:repository-catalog:v1:{owner_id}:{provider.value}:version"


def _repository_catalog_key(
    owner_id: UUID,
    provider: RepositoryProvider,
    connection_id: UUID,
    version: str,
) -> str:
    return (
        f"trace:repository-catalog:v1:{owner_id}:{provider.value}:"
        f"{connection_id}:{version}"
    )


def _branch_catalog_key(
    owner_id: UUID,
    provider: RepositoryProvider,
    connection_id: UUID,
    version: str,
    repository_identifier: str,
) -> str:
    return (
        f"trace:branch-catalog:v1:{owner_id}:{provider.value}:"
        f"{connection_id}:{version}:{repository_identifier}"
    )


def _filtered_page[T](
    records: list[T],
    *,
    page: int,
    page_size: int,
    matches: Callable[[T], bool],
) -> RepositoryPageResult[T]:
    matched = [record for record in records if matches(record)]
    start = (page - 1) * page_size
    selected = matched[start : start + page_size]
    next_page = page + 1 if start + page_size < len(matched) else None
    return RepositoryPageResult(items=selected, next_page=next_page)


def _provider(source: str | RepositoryProvider) -> RepositoryProvider:
    try:
        return (
            source
            if isinstance(source, RepositoryProvider)
            else RepositoryProvider(source)
        )
    except ValueError as error:
        raise UnsupportedSource() from error


def _review_path_prefix(path_prefix: str | None) -> str:
    raw_prefix = (path_prefix or "").strip()
    if raw_prefix in {"", ".", "./"}:
        return ""
    raw_prefix = raw_prefix.removeprefix("./")
    normalized = raw_prefix.rstrip("/")
    if not _is_safe_review_path(normalized):
        raise RepositoryProviderError(kind="malformed_response")
    return f"{normalized}/"


def _is_safe_review_path(path: str) -> bool:
    return bool(
        path
        and not path.startswith("/")
        and "\x00" not in path
        and all(part not in {"", ".", ".."} for part in path.split("/"))
    )


def _is_safe_patch(diff: str) -> bool:
    if not diff.startswith("diff --git ") or "GIT binary patch" in diff:
        return False
    for line in diff.splitlines():
        if line.startswith(
            ("new file mode 120000", "new file mode 160000", "Submodule ")
        ):
            return False
        if line.startswith(("--- a/", "+++ b/", "diff --git a/")):
            paths = line.replace("diff --git ", "").split()
            for path in paths:
                normalized = path.removeprefix("a/").removeprefix("b/")
                if not _is_safe_review_path(normalized) or normalized.startswith(
                    ".git/"
                ):
                    return False
    return True


def _validate_repository_identifier(value: str) -> str:
    if not _GITHUB_REPOSITORY_ID.fullmatch(value):
        raise RepositoryInvalidRequest()
    return value


def _validate_branch_name(value: str) -> None:
    if (
        not value
        or len(value) > 255
        or value.startswith(("/", "."))
        or value.endswith(("/", "."))
        or ".." in value
        or "//" in value
        or "@{" in value
        or any(
            ord(char) < 32 or ord(char) == 127 or char in " ~^:?*[\\" for char in value
        )
    ):
        raise RepositoryInvalidRequest()


def _active_connection(engine, *, owner_id: UUID, provider: RepositoryProvider):
    with principal_transaction(engine, owner_id) as connection:
        return (
            connection.execute(
                sa.select(ExternalRepository.__table__)
                .where(
                    ExternalRepository.owner_id == owner_id,
                    ExternalRepository.source == RepositorySource(provider.value),
                    ExternalRepository.revoked_at.is_(None),
                )
                .order_by(
                    ExternalRepository.updated_at.desc(),
                    ExternalRepository.id.desc(),
                )
                .limit(1)
            )
            .mappings()
            .one_or_none()
        )


def _provider_auth_error(error: RepositoryProviderError):
    if error.kind == "authorization":
        return GithubAuthorizationRequired()
    if error.kind == "rate_limited":
        return ProviderRateLimited(error.retry_after_seconds)
    return ProviderUnavailable()


def _provider_error(error: RepositoryProviderError, *, operation: str):
    if error.kind == "authorization":
        return GithubAuthorizationRequired()
    if error.kind == "not_found":
        return BranchNotFound() if operation == "branch" else RepositoryNotFound()
    if error.kind == "conflict":
        return BranchConflict()
    if error.kind == "rate_limited":
        return ProviderRateLimited(error.retry_after_seconds)
    return ProviderUnavailable()


def _next_page(headers: Any, current_page: int, full_page: bool) -> int | None:
    link = headers.get("Link") if headers is not None else None
    if isinstance(link, str) and re.search(r'rel="next"', link):
        return current_page + 1
    return current_page + 1 if full_page else None


def _retry_after(headers: Any) -> int | None:
    value = headers.get("Retry-After") if headers is not None else None
    try:
        return max(1, int(value)) if value is not None else None
    except (TypeError, ValueError):
        return None


def _log_provider_call(
    operation: str,
    outcome: str,
    *,
    error: RepositoryProviderError | None = None,
) -> None:
    fields: dict[str, object] = {
        "event": "repository_provider_call",
        "operation": operation,
        "provider": RepositoryProvider.GITHUB.value,
        "outcome": outcome,
    }
    if error is not None:
        cause = error.__cause__
        if isinstance(cause, HTTPError):
            fields["http_status"] = cause.code
        elif cause is not None:
            fields["transport_error_class"] = type(cause).__name__
    logger.info(
        json.dumps(fields, sort_keys=True),
        extra={
            "operation": operation,
            "provider": RepositoryProvider.GITHUB.value,
            "outcome": outcome,
        },
    )


def _github_log_context_fields(
    log_context: GitHubRequestLogContext | None,
) -> dict[str, str]:
    if log_context is None:
        return {}
    fields = {"review_id": str(log_context.review_id)}
    if log_context.review_agent_id is not None:
        fields["review_agent_id"] = str(log_context.review_agent_id)
    if log_context.attempt_id is not None:
        fields["attempt_id"] = str(log_context.attempt_id)
    return fields


def _log_github_api_request(
    *,
    method: str,
    path: str,
    request_body_bytes: int,
    log_context: GitHubRequestLogContext | None = None,
    request_attempt: int | None = None,
) -> None:
    """Record request metadata, excluding URL host, headers, and request body."""

    fields: dict[str, object] = {
        "event": "github_api_request",
        "method": method,
        "request_body_bytes": request_body_bytes,
        "request_path": path,
    }
    fields.update(_github_log_context_fields(log_context))
    if request_attempt is not None:
        fields["request_attempt"] = request_attempt
    logger.info(json.dumps(fields, sort_keys=True))


def _log_github_api_response(
    *,
    method: str,
    path: str,
    status_code: int | None,
    response_body_bytes: int,
    log_context: GitHubRequestLogContext | None = None,
    request_attempt: int | None = None,
) -> None:
    """Record safe response metadata without serializing its payload."""

    fields: dict[str, object] = {
        "event": "github_api_response",
        "method": method,
        "request_path": path,
        "response_body_bytes": response_body_bytes,
        "status_code": status_code,
    }
    fields.update(_github_log_context_fields(log_context))
    if request_attempt is not None:
        fields["request_attempt"] = request_attempt
    logger.info(json.dumps(fields, sort_keys=True))


def _log_github_api_failure(
    *,
    method: str,
    path: str,
    error: Exception,
    log_context: GitHubRequestLogContext | None = None,
    request_attempt: int | None = None,
) -> None:
    """Record a safe transport or HTTP failure without the provider's response body."""

    fields: dict[str, object] = {
        "event": "github_api_request_failed",
        "error_class": type(error).__name__,
        "method": method,
        "request_path": path,
    }
    if isinstance(error, HTTPError):
        fields["status_code"] = error.code
    elif isinstance(error, URLError) and error.reason is not None:
        fields["transport_reason_class"] = type(error.reason).__name__
    elif isinstance(error, httpx.TransportError):
        fields["transport_error_class"] = type(error).__name__
    fields.update(_github_log_context_fields(log_context))
    if request_attempt is not None:
        fields["request_attempt"] = request_attempt
    logger.info(json.dumps(fields, sort_keys=True))


def _response_status_code(response: object) -> int | None:
    status = getattr(response, "status", None)
    return status if isinstance(status, int) else None
