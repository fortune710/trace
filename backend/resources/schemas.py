from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from credentials.models import CredentialKind, CredentialProvider
from db.types import RepositoryProvider, RepositorySource
from findings.models import FindingSeverity, FindingStatus
from projects.models import ProjectCategory
from remediations.models import RemediationStatus
from reviews.models import ReviewCategory, ReviewRunAgentStatus, ReviewStatus


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


HashString = Annotated[str, StringConstraints(pattern=r"^[0-9a-fA-F]{64}$")]
CommitSha = Annotated[str, StringConstraints(pattern=r"^[0-9a-fA-F]{40}$")]
ShortName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
]


class PageQuery(RequestModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=100)

    @property
    def limit(self) -> int:
        """Internal service page size; not an HTTP query parameter."""

        return self.page_size

    @property
    def offset(self) -> int:
        """Internal service offset derived from the public page contract."""

        return (self.page - 1) * self.page_size


class ProjectCreate(RequestModel):
    name: ShortName
    source: RepositorySource
    repository_id: (
        Annotated[
            str,
            StringConstraints(
                pattern=r"^[1-9][0-9]{0,18}$", min_length=1, max_length=19
            ),
        ]
        | None
    ) = None
    branch_name: (
        Annotated[
            str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
        ]
        | None
    ) = None
    local_path_hash: HashString | None = None
    source_hash: HashString | None = None
    current_revision: (
        Annotated[str, StringConstraints(min_length=1, max_length=256)] | None
    ) = None
    category: ProjectCategory | None = None
    auto_create_pull_requests: bool = False

    @model_validator(mode="after")
    def validate_source_fields(self) -> ProjectCreate:
        if self.source is RepositorySource.LOCAL:
            if (
                self.local_path_hash is None
                or self.repository_id is not None
                or self.branch_name is not None
            ):
                raise ValueError("local projects require local-only fields")
        else:
            if (
                self.repository_id is None
                or self.branch_name is None
                or self.category is None
                or self.local_path_hash is not None
                or self.current_revision is not None
            ):
                raise ValueError(
                    "GitHub imports require repository_id, branch_name, category, "
                    "and a server-resolved revision"
                )
        return self


class ProjectUpdate(RequestModel):
    name: ShortName | None = None
    category: ProjectCategory | None = None
    auto_create_pull_requests: bool | None = None


class ProjectResponse(RequestModel):
    id: UUID
    name: str
    source: RepositorySource
    external_repository_id: str | None
    external_repository_connection_id: UUID | None
    repository_owner: str | None
    repository_name: str | None
    branch_name: str | None
    repository_visibility: str | None
    imported_at: datetime | None
    source_hash: str | None
    current_revision: str | None
    category: ProjectCategory
    auto_create_pull_requests: bool
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


class ProjectPage(RequestModel):
    items: list[ProjectResponse]
    next_offset: int | None


class RepositoryResponse(RequestModel):
    source: RepositoryProvider
    repository_id: str
    owner_login: str
    name: str
    full_name: str
    visibility: str
    private: bool
    default_branch: str | None
    web_url: str


class RepositoryPage(RequestModel):
    items: list[RepositoryResponse]
    next_page: int | None


class BranchResponse(RequestModel):
    source: RepositoryProvider
    repository_id: str
    name: str
    commit_sha: CommitSha
    protected: bool


class BranchPage(RequestModel):
    items: list[BranchResponse]
    next_page: int | None


class AgentCreate(RequestModel):
    name: ShortName
    personality: Annotated[str, StringConstraints(max_length=4000)] | None = None
    review_category: ReviewCategory
    model_provider: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
    ]
    model_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
    ]
    skills: list[dict[str, object] | str] = Field(default_factory=list, max_length=64)
    fallback_order: int = Field(default=0, ge=0, le=1000)
    credential_id: UUID | None = None


class AgentUpdate(RequestModel):
    name: ShortName | None = None
    personality: Annotated[str, StringConstraints(max_length=4000)] | None = None
    review_category: ReviewCategory | None = None
    model_provider: (
        Annotated[
            str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
        ]
        | None
    ) = None
    model_name: (
        Annotated[
            str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
        ]
        | None
    ) = None
    skills: list[dict[str, object] | str] | None = Field(default=None, max_length=64)
    fallback_order: int | None = Field(default=None, ge=0, le=1000)
    credential_id: UUID | None = None


class AgentResponse(RequestModel):
    id: UUID
    name: str
    personality: str | None
    review_category: ReviewCategory
    model_provider: str
    model_name: str
    skills: list[dict[str, object] | str]
    fallback_order: int
    credential_id: UUID | None
    created_at: datetime
    updated_at: datetime
    disabled_at: datetime | None


class AgentPage(RequestModel):
    items: list[AgentResponse]
    next_offset: int | None


class ReviewCreate(RequestModel):
    project_id: UUID
    source_revision: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)
    ]
    selected_categories: list[ReviewCategory] = Field(min_length=1, max_length=5)
    agent_ids: list[UUID] | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def validate_unique_values(self) -> ReviewCreate:
        if len(set(self.selected_categories)) != len(self.selected_categories):
            raise ValueError("review categories must be unique")
        if self.agent_ids is not None and len(set(self.agent_ids)) != len(
            self.agent_ids
        ):
            raise ValueError("review agents must be unique")
        return self


class ReviewAgentResponse(RequestModel):
    agent_id: UUID
    name: str
    review_category: ReviewCategory
    status: ReviewRunAgentStatus
    assigned_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class ReviewResponse(RequestModel):
    id: UUID
    project_id: UUID
    source_revision: str
    selected_categories: list[ReviewCategory]
    status: ReviewStatus
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    agents: list[ReviewAgentResponse]


class ReviewPage(RequestModel):
    items: list[ReviewResponse]
    next_offset: int | None


class FindingResponse(RequestModel):
    id: UUID
    review_run_id: UUID
    agent_id: UUID
    category: ReviewCategory
    severity: FindingSeverity
    title: str
    explanation: str
    evidence: str | None
    source_location: str | None
    recommendation: str | None
    status: FindingStatus
    created_at: datetime
    updated_at: datetime


class FindingUpdate(RequestModel):
    status: FindingStatus


class FindingPage(RequestModel):
    items: list[FindingResponse]
    next_offset: int | None


class RemediationCreate(RequestModel):
    proposed_diff: Annotated[str, StringConstraints(min_length=1, max_length=1_048_576)]


class RemediationResponse(RequestModel):
    id: UUID
    project_id: UUID
    finding_id: UUID
    proposed_diff: str
    status: RemediationStatus
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PullRequestResponse(RequestModel):
    id: UUID
    remediation_id: UUID
    repository_url: str
    pull_request_number: int
    pull_request_url: str
    branch_name: str
    created_at: datetime
    updated_at: datetime


class LocalFileBackupResponse(RequestModel):
    id: UUID
    remediation_id: UUID
    file_path: str
    backup_path: str
    source_hash: str
    created_at: datetime
    updated_at: datetime


class CredentialCreate(RequestModel):
    provider: CredentialProvider
    kind: CredentialKind
    payload: dict[str, object]


class CredentialResponse(RequestModel):
    id: UUID
    provider: CredentialProvider
    kind: CredentialKind
    active: bool
    created_at: datetime
    updated_at: datetime
    revoked_at: datetime | None


class CredentialPage(RequestModel):
    items: list[CredentialResponse]
    next_offset: int | None
