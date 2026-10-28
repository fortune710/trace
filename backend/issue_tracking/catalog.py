"""Owner-scoped discovery of Linear destinations for issue tracking."""

from __future__ import annotations

from typing import NoReturn
from uuid import UUID

import sqlalchemy as sa
from pydantic import SecretStr
from sqlalchemy.engine import Engine

from auth.credential_service import (
    CredentialNotFound,
    CredentialService,
    CredentialServiceError,
)
from auth.errors import (
    IssueDestinationAccessDenied,
    IssueDestinationNotFound,
    IssueProviderAuthorizationRequired,
    IssueProviderValidationError,
    ProviderRateLimited,
    ResourceUnavailable,
)
from credentials.models import Credential, CredentialKind, CredentialProvider
from db.rls import principal_transaction
from issue_tracking.contracts import IssueProviderError, LinearProject, LinearTeam
from issue_tracking.providers import LinearIssuesProvider


class LinearCatalogService:
    """Read teams and projects with the caller's stored Linear OAuth credential."""

    def __init__(
        self,
        *,
        provider: LinearIssuesProvider,
        engine: Engine,
        credential_service: CredentialService,
    ) -> None:
        self._provider = provider
        self._engine = engine
        self._credential_service = credential_service

    def list_teams(self, *, owner_id: UUID) -> list[LinearTeam]:
        try:
            return self._provider.list_teams(access_token=self._access_token(owner_id))
        except IssueProviderError as error:
            self._raise_provider_error(error)

    def list_projects(
        self,
        *,
        owner_id: UUID,
        team_id: UUID,
    ) -> list[LinearProject]:
        try:
            return self._provider.list_projects(
                access_token=self._access_token(owner_id),
                team_id=str(team_id),
            )
        except IssueProviderError as error:
            self._raise_provider_error(error)

    def _access_token(self, owner_id: UUID) -> SecretStr:
        with principal_transaction(self._engine, owner_id) as connection:
            credential_id = connection.execute(
                sa.select(Credential.id)
                .where(
                    Credential.owner_id == owner_id,
                    Credential.provider == CredentialProvider.LINEAR,
                    Credential.credential_kind == CredentialKind.OAUTH,
                    Credential.revoked_at.is_(None),
                )
                .order_by(Credential.updated_at.desc(), Credential.id.desc())
                .limit(1)
            ).scalar_one_or_none()
        if credential_id is None:
            raise IssueProviderAuthorizationRequired()
        try:
            credential = self._credential_service.decrypt_for_provider_call(
                owner_id=owner_id,
                credential_id=credential_id,
            )
        except CredentialNotFound as error:
            raise IssueProviderAuthorizationRequired() from error
        except CredentialServiceError as error:
            raise ResourceUnavailable() from error
        access_token = credential.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise IssueProviderAuthorizationRequired()
        return SecretStr(access_token)

    @staticmethod
    def _raise_provider_error(error: IssueProviderError) -> NoReturn:
        if error.kind == "authorization":
            raise IssueProviderAuthorizationRequired() from error
        if error.kind == "access_denied":
            raise IssueDestinationAccessDenied() from error
        if error.kind == "not_found":
            raise IssueDestinationNotFound() from error
        if error.kind == "rate_limited":
            raise ProviderRateLimited(error.retry_after_seconds) from error
        if error.kind == "validation":
            raise IssueProviderValidationError() from error
        raise ResourceUnavailable() from error


__all__ = ["LinearCatalogService"]
