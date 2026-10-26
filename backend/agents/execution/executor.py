"""Durable review execution with safe logs and optional LangSmith tracing."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa
from langsmith import Client
from langsmith.run_helpers import tracing_context
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from agents.execution.agent import Agent, FindingOutput, ReviewTarget
from agents.execution.orchestrator import OrchestratorAgent
from agents.execution.redaction import redact_text
from agents.execution.tools import ToolExecutionContext
from auth.credential_service import CredentialService, CredentialServiceError
from auth.errors import (
    GithubAuthorizationRequired,
    ProviderRateLimited,
    ProviderUnavailable,
    RepositoryNotFound,
)
from auth.uuids import uuid7
from credentials.models import CredentialProvider
from db.rls import principal_transaction
from external_repositories.service import RepositoryService, ReviewGitHubSourceAccess
from findings.models import Finding
from notifications.models import NotificationEventType
from notifications.service import create_notification
from reviews.config import AgentExecutionSettings
from reviews.models import (
    Review,
    ReviewAgent,
    ReviewAgentAttempt,
    ReviewAgentAttemptStatus,
    ReviewAgentExecutionConfig,
    ReviewAgentStatus,
    ReviewStatus,
)

logger = logging.getLogger("trace.agent_execution")


class ExecutionFailure(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class SelectedAgentExecution:
    """One selected agent's immutable review and credential snapshots."""

    review_agent: ReviewAgent
    credential_snapshot: ReviewAgentExecutionConfig


def _log(event: str, **fields: object) -> None:
    """Emit one JSON object; callers must only supply approved metadata."""
    logger.info(json.dumps({"event": event, **fields}, default=str, sort_keys=True))


def _source_failure_code(
    error: GithubAuthorizationRequired
    | ProviderRateLimited
    | ProviderUnavailable
    | RepositoryNotFound,
) -> str:
    if isinstance(error, GithubAuthorizationRequired):
        return "source_authorization_failed"
    if isinstance(error, ProviderRateLimited):
        return "source_rate_limited"
    if isinstance(error, RepositoryNotFound):
        return "source_not_found"
    return "source_unavailable"


class ReviewExecutionService:
    def __init__(
        self,
        *,
        engine: Engine,
        credential_service: CredentialService,
        repository_service: RepositoryService,
        settings: AgentExecutionSettings,
    ) -> None:
        self._engine = engine
        self._credential_service = credential_service
        self._repository_service = repository_service
        self._settings = settings
        self._settings.validate_for_execution()
        self._langsmith: Client | None = None
        if self._settings.langsmith_tracing:
            langsmith_api_key = self._settings.langsmith_api_key
            if langsmith_api_key is None:
                raise RuntimeError(
                    "LangSmith API key is required when tracing is enabled"
                )
            self._langsmith = Client(
                api_key=langsmith_api_key.get_secret_value(),
                api_url=self._settings.langsmith_endpoint,
                hide_inputs=True,
                hide_outputs=True,
            )
        self._orchestrator = OrchestratorAgent()

    def execute(self, *, owner_id: UUID, review_id: UUID, dispatch_id: UUID) -> None:
        review_claimed = self._claim_queued_review(
            owner_id=owner_id, review_id=review_id
        )
        if not review_claimed:
            _log(
                "review_execution_skipped",
                review_id=review_id,
                dispatch_id=dispatch_id,
                owner_id=owner_id,
            )
            return
        review, selected_agent_executions = self._load_review_and_selected_agents(
            owner_id=owner_id,
            review_id=review_id,
        )
        selected_review_agents = [
            selected_agent.review_agent for selected_agent in selected_agent_executions
        ]
        execution_started_at = time.monotonic()
        trace_metadata = {
            "review_id": str(review_id),
            "dispatch_id": str(dispatch_id),
            "source_kind": review.source_kind.value,
            "source_revision": review.source_revision,
        }
        try:
            with tracing_context(
                project_name=self._settings.langsmith_project,
                metadata=trace_metadata,
                client=self._langsmith,
                enabled=self._settings.langsmith_tracing,
            ):
                review_target = ReviewTarget(
                    source_kind=review.source_kind.value,
                    source_identifier=review.source_identifier,
                    source_revision=review.source_revision,
                )
                with self._open_review_source_access(
                    owner_id=owner_id,
                    review=review,
                ) as repository_access:
                    tool_context = ToolExecutionContext(
                        owner_id=owner_id,
                        source_kind=review.source_kind.value,
                        source_identifier=review.source_identifier,
                        source_revision=review.source_revision,
                        repository_access=repository_access,
                        review_id=review_id,
                    )
                    for selected_agent in selected_agent_executions:
                        self._execute_selected_agent(
                            owner_id=owner_id,
                            review=review,
                            selected_agent=selected_agent,
                            review_target=review_target,
                            tool_context=tool_context,
                            dispatch_id=dispatch_id,
                        )
            self._finalize_review_status(owner_id=owner_id, review_id=review_id)
            _log(
                "review_execution_completed",
                review_id=review_id,
                dispatch_id=dispatch_id,
                graph_duration_ms=round(
                    (time.monotonic() - execution_started_at) * 1000
                ),
            )
        except ExecutionFailure as error:
            self._fail_review_and_selected_agents(
                owner_id=owner_id,
                review_id=review_id,
                review_agents=selected_review_agents,
                failure_code=error.code,
            )

    @contextmanager
    def _open_review_source_access(
        self,
        *,
        owner_id: UUID,
        review: Review,
    ) -> Iterator[ReviewGitHubSourceAccess | None]:
        """Open a provider reader only for source kinds implemented by execution.

        Tools retain responsibility for returning ``source_execution_unsupported``
        when an agent attempts an operation for a source kind without an adapter.
        This prevents a local or GitLab review identifier from being validated as a
        GitHub numeric repository ID before the agent starts.
        """
        if review.source_kind.value != "github":
            yield None
            return

        with self._repository_service.open_review_github_source_access(
            owner_id=owner_id,
            repository_identifier=review.source_identifier,
            revision=review.source_revision,
            max_concurrent_requests=self._settings.github_max_concurrent_requests,
            max_attempts=self._settings.github_get_max_attempts,
            retry_base_seconds=self._settings.github_retry_base_seconds,
            retry_max_seconds=self._settings.github_retry_max_seconds,
        ) as repository_access:
            yield repository_access

    def _claim_queued_review(self, *, owner_id: UUID, review_id: UUID) -> bool:
        with principal_transaction(self._engine, owner_id) as connection:
            review = connection.execute(
                sa.select(Review.status)
                .where(Review.id == review_id, Review.owner_id == owner_id)
                .with_for_update()
            ).scalar_one_or_none()
            if review is not ReviewStatus.QUEUED:
                return False
            result = connection.execute(
                sa.update(Review)
                .where(
                    Review.id == review_id,
                    Review.owner_id == owner_id,
                    Review.status == ReviewStatus.QUEUED,
                )
                .values(status=ReviewStatus.RUNNING, started_at=sa.func.now())
            )
            return result.rowcount == 1

    def _load_review_and_selected_agents(
        self, *, owner_id: UUID, review_id: UUID
    ) -> tuple[Review, list[SelectedAgentExecution]]:
        with (
            principal_transaction(self._engine, owner_id) as connection,
            Session(bind=connection) as session,
        ):
            review = session.execute(
                sa.select(Review).where(
                    Review.id == review_id, Review.owner_id == owner_id
                )
            ).scalar_one()
            selected_agent_executions = [
                SelectedAgentExecution(
                    review_agent=review_agent,
                    credential_snapshot=credential_snapshot,
                )
                for review_agent, credential_snapshot in session.execute(
                    sa.select(ReviewAgent, ReviewAgentExecutionConfig)
                    .join(
                        ReviewAgentExecutionConfig,
                        sa.and_(
                            ReviewAgentExecutionConfig.owner_id == ReviewAgent.owner_id,
                            ReviewAgentExecutionConfig.review_id
                            == ReviewAgent.review_id,
                            ReviewAgentExecutionConfig.review_agent_id
                            == ReviewAgent.id,
                        ),
                    )
                    .where(
                        ReviewAgent.review_id == review_id,
                        ReviewAgent.owner_id == owner_id,
                    )
                    .order_by(ReviewAgent.assigned_at, ReviewAgent.id)
                ).all()
            ]
        return review, selected_agent_executions

    def _execute_selected_agent(
        self,
        *,
        owner_id: UUID,
        review: Review,
        selected_agent: SelectedAgentExecution,
        review_target: ReviewTarget,
        tool_context: ToolExecutionContext,
        dispatch_id: UUID,
    ) -> None:
        review_agent = selected_agent.review_agent
        attempt_id = self._start_review_agent_attempt(
            owner_id=owner_id,
            review=review,
            review_agent=review_agent,
        )
        provider_call_started_at = time.monotonic()
        try:
            runtime_agent = self._build_runtime_agent(
                owner_id=owner_id,
                review_agent=review_agent,
                credential_snapshot=selected_agent.credential_snapshot,
            )
            finding_batch = self._orchestrator.run(
                review_target=review_target,
                tool_context=replace(
                    tool_context,
                    review_agent_id=review_agent.id,
                    attempt_id=attempt_id,
                ),
                agents=(runtime_agent,),
            )[0]
            self._persist_findings(
                owner_id=owner_id,
                review=review,
                review_agent=review_agent,
                finding_outputs=finding_batch.findings,
            )
        except (CredentialServiceError, ExecutionFailure, ValueError) as error:
            self._finish_review_agent_attempt(
                owner_id=owner_id,
                review_agent=review_agent,
                attempt_id=attempt_id,
                failure_code="model_access_unavailable",
            )
            _log(
                "agent_execution_failed",
                review_id=review.id,
                review_agent_id=review_agent.id,
                attempt_id=attempt_id,
                dispatch_id=dispatch_id,
                failure_code="model_access_unavailable",
                error_class=type(error).__name__,
            )
            return
        except (
            GithubAuthorizationRequired,
            ProviderRateLimited,
            ProviderUnavailable,
            RepositoryNotFound,
        ) as error:
            failure_code = _source_failure_code(error)
            self._finish_review_agent_attempt(
                owner_id=owner_id,
                review_agent=review_agent,
                attempt_id=attempt_id,
                failure_code=failure_code,
            )
            _log(
                "agent_execution_failed",
                review_id=review.id,
                review_agent_id=review_agent.id,
                attempt_id=attempt_id,
                dispatch_id=dispatch_id,
                failure_code=failure_code,
                error_class=type(error).__name__,
            )
            return
        except Exception as error:  # noqa: BLE001 - provider SDKs have no shared error base.
            self._finish_review_agent_attempt(
                owner_id=owner_id,
                review_agent=review_agent,
                attempt_id=attempt_id,
                failure_code="provider_execution_failed",
            )
            _log(
                "agent_execution_failed",
                review_id=review.id,
                review_agent_id=review_agent.id,
                attempt_id=attempt_id,
                dispatch_id=dispatch_id,
                failure_code="provider_execution_failed",
                error_class=type(error).__name__,
            )
            return
        self._finish_review_agent_attempt(
            owner_id=owner_id,
            review_agent=review_agent,
            attempt_id=attempt_id,
            failure_code=None,
        )
        _log(
            "agent_execution_completed",
            review_id=review.id,
            review_agent_id=review_agent.id,
            agent_id=review_agent.agent_id,
            attempt_id=attempt_id,
            provider=review_agent.agent_model_provider,
            model=review_agent.agent_model_name,
            provider_latency_ms=round(
                (time.monotonic() - provider_call_started_at) * 1000
            ),
        )

    def _build_runtime_agent(
        self,
        *,
        owner_id: UUID,
        review_agent: ReviewAgent,
        credential_snapshot: ReviewAgentExecutionConfig,
    ) -> Agent:
        api_key = self._resolve_model_api_key(
            owner_id=owner_id,
            credential_id=credential_snapshot.credential_id,
            provider=review_agent.agent_model_provider,
        )
        return Agent(
            provider=review_agent.agent_model_provider,
            model=review_agent.agent_model_name,
            skills=tuple(review_agent.agent_skills),
            metadata={
                "category": review_agent.agent_specialization.value,
                "personality": review_agent.agent_personality or "",
            },
            api_key=api_key,
        )

    def _resolve_model_api_key(
        self, *, owner_id: UUID, credential_id: UUID | None, provider: str
    ) -> str | None:
        if credential_id is not None:
            credential_payload = self._credential_service.decrypt_for_provider_call(
                owner_id=owner_id, credential_id=credential_id
            )
            api_key = credential_payload.get("api_key")
            if not isinstance(api_key, str) or not api_key:
                raise ExecutionFailure("model_access_unavailable")
            return api_key
        trace_managed_api_key = {
            CredentialProvider.OPENAI.value: self._settings.openai_api_key,
            CredentialProvider.ANTHROPIC.value: self._settings.anthropic_api_key,
            CredentialProvider.GOOGLE.value: self._settings.google_api_key,
            CredentialProvider.XAI.value: self._settings.xai_api_key,
        }.get(provider)
        if (
            trace_managed_api_key is None
            or not trace_managed_api_key.get_secret_value()
        ):
            raise ExecutionFailure("model_access_unavailable")
        return trace_managed_api_key.get_secret_value()

    def _start_review_agent_attempt(
        self,
        *,
        owner_id: UUID,
        review: Review,
        review_agent: ReviewAgent,
    ) -> UUID:
        attempt_id = uuid7()
        with principal_transaction(self._engine, owner_id) as connection:
            next_attempt_number = (
                connection.execute(
                    sa.select(
                        sa.func.coalesce(
                            sa.func.max(ReviewAgentAttempt.attempt_number), 0
                        )
                    ).where(
                        ReviewAgentAttempt.owner_id == owner_id,
                        ReviewAgentAttempt.review_agent_id == review_agent.id,
                    )
                ).scalar_one()
                + 1
            )
            connection.execute(
                sa.insert(ReviewAgentAttempt).values(
                    id=attempt_id,
                    owner_id=owner_id,
                    review_id=review.id,
                    review_agent_id=review_agent.id,
                    attempt_number=next_attempt_number,
                    status=ReviewAgentAttemptStatus.STARTED,
                    started_at=datetime.now(UTC),
                )
            )
            connection.execute(
                sa.update(ReviewAgent)
                .where(
                    ReviewAgent.id == review_agent.id, ReviewAgent.owner_id == owner_id
                )
                .values(status=ReviewAgentStatus.RUNNING, started_at=sa.func.now())
            )
        return attempt_id

    def _persist_findings(
        self,
        *,
        owner_id: UUID,
        review: Review,
        review_agent: ReviewAgent,
        finding_outputs: list[FindingOutput],
    ) -> None:
        finding_rows = []
        for finding in finding_outputs:
            normalized = finding.model_dump(mode="json")
            redacted_finding = {
                key: redact_text(value) if isinstance(value, str) else value
                for key, value in normalized.items()
            }
            digest = hashlib.sha256(
                json.dumps(
                    redacted_finding,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).digest()
            finding_rows.append(
                {
                    "id": uuid7(),
                    "owner_id": owner_id,
                    "review_id": review.id,
                    "agent_id": review_agent.agent_id,
                    "content_digest": digest,
                    "category": review_agent.agent_specialization,
                    **redacted_finding,
                }
            )
        if not finding_rows:
            return
        with principal_transaction(self._engine, owner_id) as connection:
            inserted_ids = (
                connection.execute(
                    pg_insert(Finding)
                    .values(finding_rows)
                    .on_conflict_do_nothing(
                        index_elements=[
                            Finding.owner_id,
                            Finding.review_id,
                            Finding.agent_id,
                            Finding.content_digest,
                        ],
                        index_where=Finding.content_digest.is_not(None),
                    )
                    .returning(Finding.id)
                )
                .scalars()
                .all()
            )
            if inserted_ids:
                create_notification(
                    connection,
                    owner_id=owner_id,
                    event_type=NotificationEventType.FINDINGS_AVAILABLE,
                    dedupe_key=f"review:{review.id}:findings_available",
                    review_id=review.id,
                )
        _log(
            "findings_persisted",
            review_id=review.id,
            review_agent_id=review_agent.id,
            findings_created=len(inserted_ids),
        )

    def _finish_review_agent_attempt(
        self,
        *,
        owner_id: UUID,
        review_agent: ReviewAgent,
        attempt_id: UUID,
        failure_code: str | None,
    ) -> None:
        succeeded = failure_code is None
        with principal_transaction(self._engine, owner_id) as connection:
            connection.execute(
                sa.update(ReviewAgentAttempt)
                .where(
                    ReviewAgentAttempt.id == attempt_id,
                    ReviewAgentAttempt.owner_id == owner_id,
                )
                .values(
                    status=ReviewAgentAttemptStatus.SUCCEEDED
                    if succeeded
                    else ReviewAgentAttemptStatus.FAILED,
                    failure_code=failure_code,
                    completed_at=sa.func.now(),
                )
            )
            connection.execute(
                sa.update(ReviewAgent)
                .where(
                    ReviewAgent.id == review_agent.id, ReviewAgent.owner_id == owner_id
                )
                .values(
                    status=ReviewAgentStatus.COMPLETED
                    if succeeded
                    else ReviewAgentStatus.FAILED,
                    error_reason=failure_code,
                    completed_at=sa.func.now(),
                )
            )

    def _fail_review_and_selected_agents(
        self,
        *,
        owner_id: UUID,
        review_id: UUID,
        review_agents: list[ReviewAgent],
        failure_code: str,
    ) -> None:
        with principal_transaction(self._engine, owner_id) as connection:
            updated = connection.execute(
                sa.update(Review)
                .where(
                    Review.id == review_id,
                    Review.owner_id == owner_id,
                    Review.status.in_([ReviewStatus.QUEUED, ReviewStatus.RUNNING]),
                )
                .values(status=ReviewStatus.FAILED, completed_at=sa.func.now())
            )
            if updated.rowcount == 1:
                connection.execute(
                    sa.update(ReviewAgent)
                    .where(
                        ReviewAgent.owner_id == owner_id,
                        ReviewAgent.review_id == review_id,
                    )
                    .values(
                        status=ReviewAgentStatus.FAILED,
                        error_reason=failure_code,
                        completed_at=sa.func.now(),
                    )
                )
                create_notification(
                    connection,
                    owner_id=owner_id,
                    event_type=NotificationEventType.REVIEW_FAILED,
                    dedupe_key=f"review:{review_id}:failed",
                    review_id=review_id,
                )
        _log(
            "review_execution_failed",
            review_id=review_id,
            failure_code=failure_code,
            selected_agent_count=len(review_agents),
        )

    def _finalize_review_status(self, *, owner_id: UUID, review_id: UUID) -> None:
        with principal_transaction(self._engine, owner_id) as connection:
            failed_agent_count = connection.execute(
                sa.select(sa.func.count())
                .select_from(ReviewAgent)
                .where(
                    ReviewAgent.owner_id == owner_id,
                    ReviewAgent.review_id == review_id,
                    ReviewAgent.status == ReviewAgentStatus.FAILED,
                )
            ).scalar_one()
            terminal_status = (
                ReviewStatus.FAILED if failed_agent_count else ReviewStatus.COMPLETED
            )
            updated = connection.execute(
                sa.update(Review)
                .where(
                    Review.id == review_id,
                    Review.owner_id == owner_id,
                    Review.status.in_([ReviewStatus.QUEUED, ReviewStatus.RUNNING]),
                )
                .values(status=terminal_status, completed_at=sa.func.now())
            )
            if updated.rowcount == 1:
                create_notification(
                    connection,
                    owner_id=owner_id,
                    event_type=(
                        NotificationEventType.REVIEW_FAILED
                        if terminal_status is ReviewStatus.FAILED
                        else NotificationEventType.REVIEW_COMPLETED
                    ),
                    dedupe_key=f"review:{review_id}:{terminal_status.value}",
                    review_id=review_id,
                )
