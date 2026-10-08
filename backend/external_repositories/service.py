"""Provider repository access, branch operations, and OAuth provisioning."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from uuid import UUID

import sqlalchemy as sa

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
    "RepositoryPageResult",
    "RepositoryRecord",
    "RepositoryService",
    "provision_external_repository",
]

_GITHUB_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
_GITHUB_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,18}$")
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_GITHUB_API_VERSION = "2022-11-28"
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
class RepositoryPageResult[T]:
    items: list[T]
    next_page: int | None


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


class GitHubClient:
    """Response-validating GitHub REST adapter with no secret logging."""

    def __init__(self, *, base_url: str, timeout_seconds: float = 10.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def list_repositories(
        self, *, access_token: str, page: int, page_size: int
    ) -> RepositoryPageResult[RepositoryRecord]:
        query = urlencode(
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
            method="GET", path=f"/user/repos?{query}", access_token=access_token
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

    def list_branches(
        self,
        *,
        access_token: str,
        repository: RepositoryRecord,
        page: int,
        page_size: int,
    ) -> RepositoryPageResult[BranchRecord]:
        query = urlencode({"per_page": page_size, "page": page})
        payload, headers = self._request_json(
            method="GET",
            path=(
                f"/repos/{quote(repository.owner_login, safe='')}/"
                f"{quote(repository.name, safe='')}/branches?{query}"
            ),
            access_token=access_token,
        )
        if not isinstance(payload, list):
            raise RepositoryProviderError(kind="malformed_response")
        items = [self._branch_record(item, repository.repository_id) for item in payload]
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
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                raw = response.read(_MAX_RESPONSE_BYTES + 1)
                headers = response.headers
        except HTTPError as error:
            retry_after = _retry_after(error.headers)
            remaining = error.headers.get("X-RateLimit-Remaining")
            if error.code == 429 or (
                error.code == 403 and remaining == "0"
            ):
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
        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise GithubAuthorizationRequired()
        return token


def _provider(source: str | RepositoryProvider) -> RepositoryProvider:
    try:
        return (
            source
            if isinstance(source, RepositoryProvider)
            else RepositoryProvider(source)
        )
    except ValueError as error:
        raise UnsupportedSource() from error


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
            ord(char) < 32 or ord(char) == 127 or char in " ~^:?*[\\"
            for char in value
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


def _log_provider_call(operation: str, outcome: str) -> None:
    logger.info(
        "repository_provider_call",
        extra={
            "operation": operation,
            "provider": RepositoryProvider.GITHUB.value,
            "outcome": outcome,
        },
    )
