"""Creation and persistence of owner-scoped external issue links."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from pydantic import SecretStr
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine

from agents.execution.redaction import redact_text
from auth.credential_service import (
    CredentialNotFound,
    CredentialService,
    CredentialServiceError,
)
from auth.errors import (
    AuthorizationDenied,
    IssueDestinationAccessDenied,
    IssueDestinationNotConfigured,
    IssueDestinationNotFound,
    IssueProviderAuthorizationRequired,
    IssueProviderValidationError,
    ProviderRateLimited,
    ResourceConflict,
    ResourceNotFound,
    ResourceUnavailable,
)
from auth.uuids import uuid7
from credentials.models import Credential, CredentialKind, CredentialProvider
from db.rls import principal_transaction
from findings.models import Finding
from issue_tracking.contracts import (
    GitHubIssueDestination,
    IssueDestination,
    IssuePayload,
    IssueProvider,
    IssueProviderError,
    LinearIssueDestination,
)
from issue_tracking.models import IssueLink, IssueLinkState, IssueProviderName
from notifications.models import NotificationEventType
from notifications.service import create_notification
from projects.models import Project
from remediations.models import Remediation
from reviews.models import Review


@dataclass(frozen=True, slots=True)
class IssueLinkResult:
    id: UUID
    finding_id: UUID
    provider: IssueProviderName
    destination_id: str
    external_identifier: str | None
    external_url: str | None
    state: IssueLinkState
    failure_code: str | None
    created_at: datetime
    updated_at: datetime


class IssueTrackingService:
    """Use one provider adapter to create an externally tracked finding."""

    def __init__(
        self,
        *,
        provider: IssueProvider,
        engine: Engine,
        credential_service: CredentialService,
    ) -> None:
        self._provider = provider
        self._engine = engine
        self._credential_service = credential_service

    def preview_issue(
        self,
        *,
        owner_id: UUID,
        finding_id: UUID,
    ) -> IssuePayload:
        payload, _credential_id, _destination, _finding_action_path = (
            self._load_context_for_finding(
                owner_id=owner_id,
                finding_id=finding_id,
                require_credential=False,
            )
        )
        return payload

    def create_remediation_issue(
        self,
        *,
        owner_id: UUID,
        remediation_id: UUID,
    ) -> IssueLinkResult:
        (
            finding_id,
            payload,
            credential_id,
            destination,
            finding_action_path,
        ) = self._load_context_for_remediation(
            owner_id=owner_id,
            remediation_id=remediation_id,
        )
        assert credential_id is not None
        link, created_now = self._claim_link(
            owner_id=owner_id,
            finding_id=finding_id,
            destination_id=destination.id,
        )
        if link.state is IssueLinkState.CREATED:
            return link
        if not created_now and link.state is IssueLinkState.PENDING:
            return link
        if link.state is IssueLinkState.FAILED:
            self._mark_pending(owner_id=owner_id, link_id=link.id)
        try:
            credential = self._credential_service.decrypt_for_provider_call(
                owner_id=owner_id,
                credential_id=credential_id,
            )
            access_token = credential.get("access_token")
            if not isinstance(access_token, str) or not access_token:
                raise CredentialNotFound("Credential is unavailable")
            self._provider.verify_destination(
                access_token=SecretStr(access_token),
                destination=destination,
            )
            created = self._provider.create_issue(
                access_token=SecretStr(access_token),
                destination=destination,
                payload=payload,
            )
        except CredentialNotFound as error:
            self._mark_failed(
                owner_id=owner_id,
                link_id=link.id,
                finding_id=finding_id,
                finding_action_path=finding_action_path,
                failure_code="authorization",
            )
            raise IssueProviderAuthorizationRequired() from error
        except CredentialServiceError as error:
            self._mark_failed(
                owner_id=owner_id,
                link_id=link.id,
                finding_id=finding_id,
                finding_action_path=finding_action_path,
                failure_code="unavailable",
            )
            raise ResourceUnavailable() from error
        except IssueProviderError as error:
            self._handle_provider_error(
                owner_id=owner_id,
                link_id=link.id,
                finding_id=finding_id,
                finding_action_path=finding_action_path,
                error=error,
            )
            raise AssertionError("unreachable") from error

        with principal_transaction(self._engine, owner_id) as connection:
            row = (
                connection.execute(
                    sa.update(IssueLink)
                    .where(
                        IssueLink.id == link.id,
                        IssueLink.owner_id == owner_id,
                        IssueLink.state == IssueLinkState.PENDING,
                    )
                    .values(
                        state=IssueLinkState.CREATED,
                        external_identifier=created.external_id,
                        external_url=created.url,
                        failure_code=None,
                        updated_at=sa.func.now(),
                    )
                    .returning(IssueLink.__table__)
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ResourceConflict("issue_link_state_conflict")
            create_notification(
                connection,
                owner_id=owner_id,
                event_type=NotificationEventType.ISSUE_CREATED,
                dedupe_key=f"issue-link:{link.id}:created",
                action_path=finding_action_path,
                data={
                    "finding_id": str(finding_id),
                    "issue_link_id": str(link.id),
                    "provider": self._provider.name.value,
                },
            )
        return _link_result(row)

    def list_links(self, *, owner_id: UUID, finding_id: UUID) -> list[IssueLinkResult]:
        with principal_transaction(self._engine, owner_id) as connection:
            self._owned_finding(connection, owner_id=owner_id, finding_id=finding_id)
            rows = (
                connection.execute(
                    sa.select(IssueLink.__table__)
                    .where(
                        IssueLink.owner_id == owner_id,
                        IssueLink.finding_id == finding_id,
                    )
                    .order_by(IssueLink.created_at.desc(), IssueLink.id.desc())
                )
                .mappings()
                .all()
            )
        return [_link_result(row) for row in rows]

    def get_link(self, *, owner_id: UUID, link_id: UUID) -> IssueLinkResult:
        with principal_transaction(self._engine, owner_id) as connection:
            row = (
                connection.execute(
                    sa.select(IssueLink.__table__).where(
                        IssueLink.owner_id == owner_id,
                        IssueLink.id == link_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                exists = connection.execute(
                    sa.text("SELECT public.trace_issue_link_exists(:link_id)"),
                    {"link_id": link_id},
                ).scalar_one()
                if exists:
                    raise AuthorizationDenied()
                raise ResourceNotFound()
        return _link_result(row)

    def _load_context_for_finding(
        self,
        *,
        owner_id: UUID,
        finding_id: UUID,
        require_credential: bool = True,
    ) -> tuple[IssuePayload, UUID | None, IssueDestination, str]:
        with principal_transaction(self._engine, owner_id) as connection:
            finding = self._owned_finding(
                connection,
                owner_id=owner_id,
                finding_id=finding_id,
            )
            remediation = (
                connection.execute(
                    sa.select(Remediation.__table__)
                    .where(
                        Remediation.owner_id == owner_id,
                        Remediation.finding_id == finding_id,
                    )
                    .order_by(Remediation.created_at.desc(), Remediation.id.desc())
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            return self._load_link_context(
                connection=connection,
                owner_id=owner_id,
                finding=finding,
                remediation=remediation,
                require_credential=require_credential,
            )

    def _load_context_for_remediation(
        self,
        *,
        owner_id: UUID,
        remediation_id: UUID,
    ) -> tuple[UUID, IssuePayload, UUID | None, IssueDestination, str]:
        with principal_transaction(self._engine, owner_id) as connection:
            remediation = self._owned_remediation(
                connection,
                owner_id=owner_id,
                remediation_id=remediation_id,
            )
            finding_id = remediation["finding_id"]
            assert isinstance(finding_id, UUID)
            finding = self._owned_finding(
                connection,
                owner_id=owner_id,
                finding_id=finding_id,
            )
            payload, credential_id, destination, action_path = self._load_link_context(
                connection=connection,
                owner_id=owner_id,
                finding=finding,
                remediation=remediation,
                require_credential=True,
            )
        return finding_id, payload, credential_id, destination, action_path

    def _load_link_context(
        self,
        *,
        connection: sa.Connection,
        owner_id: UUID,
        finding: sa.RowMapping,
        remediation: sa.RowMapping | None,
        require_credential: bool,
    ) -> tuple[IssuePayload, UUID | None, IssueDestination, str]:
        if remediation is None:
            raise ResourceConflict("remediation_unavailable")
        review = (
            connection.execute(
                sa.select(Review.__table__).where(
                    Review.id == finding["review_id"],
                    Review.owner_id == owner_id,
                )
            )
            .mappings()
            .one()
        )
        project = (
            connection.execute(
                sa.select(Project.__table__).where(
                    Project.id == remediation["project_id"],
                    Project.owner_id == owner_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if project is None:
            raise ResourceNotFound()
        credential_id = connection.execute(
            sa.select(Credential.id)
            .where(
                Credential.owner_id == owner_id,
                Credential.provider == CredentialProvider(self._provider.name.value),
                Credential.credential_kind == CredentialKind.OAUTH,
                Credential.revoked_at.is_(None),
            )
            .order_by(Credential.updated_at.desc(), Credential.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        if require_credential and credential_id is None:
            raise IssueProviderAuthorizationRequired()
        destination = _project_destination(
            project,
            provider=self._provider.name,
        )
        return (
            _payload(finding=finding, review=review, remediation=remediation),
            credential_id,
            destination,
            f"/reviews/{review['id']}/findings/{finding['id']}",
        )

    def _claim_link(
        self,
        *,
        owner_id: UUID,
        finding_id: UUID,
        destination_id: str,
    ) -> tuple[IssueLinkResult, bool]:
        with principal_transaction(self._engine, owner_id) as connection:
            self._owned_finding(connection, owner_id=owner_id, finding_id=finding_id)
            inserted = (
                connection.execute(
                    pg_insert(IssueLink)
                    .values(
                        id=uuid7(),
                        owner_id=owner_id,
                        finding_id=finding_id,
                        provider=self._provider.name,
                        destination_id=destination_id,
                        state=IssueLinkState.PENDING,
                    )
                    .on_conflict_do_nothing(
                        constraint="issue_links_owner_finding_provider_destination_key"
                    )
                    .returning(IssueLink.__table__)
                )
                .mappings()
                .one_or_none()
            )
            if inserted is not None:
                return _link_result(inserted), True
            existing = (
                connection.execute(
                    sa.select(IssueLink.__table__)
                    .where(
                        IssueLink.owner_id == owner_id,
                        IssueLink.finding_id == finding_id,
                        IssueLink.provider == self._provider.name,
                        IssueLink.destination_id == destination_id,
                    )
                    .with_for_update()
                )
                .mappings()
                .one()
            )
        return _link_result(existing), False

    def _mark_pending(self, *, owner_id: UUID, link_id: UUID) -> None:
        with principal_transaction(self._engine, owner_id) as connection:
            connection.execute(
                sa.update(IssueLink)
                .where(
                    IssueLink.id == link_id,
                    IssueLink.owner_id == owner_id,
                    IssueLink.state == IssueLinkState.FAILED,
                )
                .values(
                    state=IssueLinkState.PENDING,
                    failure_code=None,
                    updated_at=sa.func.now(),
                )
            )

    def _mark_failed(
        self,
        *,
        owner_id: UUID,
        link_id: UUID,
        finding_id: UUID,
        finding_action_path: str,
        failure_code: str,
    ) -> None:
        with principal_transaction(self._engine, owner_id) as connection:
            row = (
                connection.execute(
                    sa.update(IssueLink)
                    .where(IssueLink.id == link_id, IssueLink.owner_id == owner_id)
                    .values(
                        state=IssueLinkState.FAILED,
                        failure_code=failure_code,
                        updated_at=sa.func.now(),
                    )
                    .returning(IssueLink.__table__)
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ResourceConflict("issue_link_state_conflict")
            create_notification(
                connection,
                owner_id=owner_id,
                event_type=NotificationEventType.ISSUE_CREATION_FAILED,
                dedupe_key=f"issue-link:{link_id}:failed",
                action_path=finding_action_path,
                data={
                    "finding_id": str(finding_id),
                    "issue_link_id": str(link_id),
                    "provider": self._provider.name.value,
                    "failure_code": failure_code,
                },
            )

    def _handle_provider_error(
        self,
        *,
        owner_id: UUID,
        link_id: UUID,
        finding_id: UUID,
        finding_action_path: str,
        error: IssueProviderError,
    ) -> None:
        if error.kind == "unavailable":
            # The remote provider may have accepted the request before disconnecting.
            # Preserve pending so a retry never creates a second ticket blindly.
            raise ResourceUnavailable() from error
        self._mark_failed(
            owner_id=owner_id,
            link_id=link_id,
            finding_id=finding_id,
            finding_action_path=finding_action_path,
            failure_code=error.kind,
        )
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

    @staticmethod
    def _owned_finding(
        connection,
        *,
        owner_id: UUID,
        finding_id: UUID,
    ) -> sa.RowMapping:
        finding = (
            connection.execute(
                sa.select(Finding.__table__).where(
                    Finding.id == finding_id,
                    Finding.owner_id == owner_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if finding is not None:
            return finding
        exists = connection.execute(
            sa.text("SELECT public.trace_finding_exists(:finding_id)"),
            {"finding_id": finding_id},
        ).scalar_one()
        if exists:
            raise AuthorizationDenied()
        raise ResourceNotFound()

    @staticmethod
    def _owned_remediation(
        connection: sa.Connection,
        *,
        owner_id: UUID,
        remediation_id: UUID,
    ) -> sa.RowMapping:
        remediation = (
            connection.execute(
                sa.select(Remediation.__table__).where(
                    Remediation.id == remediation_id,
                    Remediation.owner_id == owner_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if remediation is not None:
            return remediation
        exists = connection.execute(
            sa.text("SELECT public.trace_remediation_exists(:remediation_id)"),
            {"remediation_id": remediation_id},
        ).scalar_one()
        if exists:
            raise AuthorizationDenied()
        raise ResourceNotFound()


def _payload(
    *,
    finding: Mapping[Any, Any],
    review: Mapping[Any, Any],
    remediation: Mapping[Any, Any],
) -> IssuePayload:
    severity = finding["severity"]
    category = finding["category"]
    severity_value = getattr(severity, "value", severity)
    category_value = getattr(category, "value", category)
    assert isinstance(severity_value, str)
    assert isinstance(category_value, str)
    explanation = finding["explanation"]
    assert isinstance(explanation, str)
    sections = [
        f"## Finding\n\n{redact_text(explanation)}",
        f"- Severity: `{severity_value}`",
        f"- Category: `{category_value}`",
        f"- Trace review: `/reviews/{review['id']}/findings/{finding['id']}`",
        f"- Source revision: `{review['source_revision']}`",
    ]
    evidence = finding["evidence"]
    recommendation = finding["recommendation"]
    prompt_text = remediation["prompt_text"]
    proposed_diff = remediation["proposed_diff"]
    if isinstance(evidence, str) and evidence:
        sections.append(f"## Evidence\n\n{redact_text(evidence)}")
    if isinstance(recommendation, str) and recommendation:
        sections.append(f"## Recommendation\n\n{redact_text(recommendation)}")
    if isinstance(prompt_text, str) and prompt_text:
        sections.append(
            f"## Proposed implementation prompt\n\n{redact_text(prompt_text)}"
        )
    assert isinstance(proposed_diff, str)
    title = finding["title"]
    assert isinstance(title, str)
    sections.append(f"## Proposed diff\n\n```diff\n{redact_text(proposed_diff)}\n```")
    return IssuePayload(
        title=redact_text(title),
        body_markdown="\n\n".join(sections),
    )


def _project_destination(
    project: Mapping[Any, Any],
    *,
    provider: IssueProviderName,
) -> IssueDestination:
    if provider is IssueProviderName.GITHUB:
        owner = project["repository_owner"]
        repository = project["repository_name"]
        if (
            not isinstance(owner, str)
            or not owner
            or not isinstance(repository, str)
            or not repository
        ):
            raise IssueDestinationNotConfigured()
        return GitHubIssueDestination(owner=owner, repository=repository)

    details = project["issue_tracking_details"]
    if not isinstance(details, dict):
        raise IssueDestinationNotConfigured()
    entries = details.get("connected_projects")
    if not isinstance(entries, list):
        raise IssueDestinationNotConfigured()
    matches = [
        entry
        for entry in entries
        if isinstance(entry, dict) and entry.get("provider") == provider.value
    ]
    if len(matches) != 1:
        raise IssueDestinationNotConfigured()
    entry = matches[0]
    owner = entry.get("owner")
    linear_project = entry.get("project")
    if (
        not isinstance(owner, str)
        or not owner
        or not isinstance(linear_project, str)
        or not linear_project
    ):
        raise IssueDestinationNotConfigured()
    return LinearIssueDestination(team_id=owner, project_id=linear_project)


def _link_result(row: sa.RowMapping) -> IssueLinkResult:
    return IssueLinkResult(
        id=row["id"],
        finding_id=row["finding_id"],
        provider=row["provider"],
        destination_id=row["destination_id"],
        external_identifier=row["external_identifier"],
        external_url=row["external_url"],
        state=row["state"],
        failure_code=row["failure_code"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


__all__ = ["IssueLinkResult", "IssueTrackingService"]
