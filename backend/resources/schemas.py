from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from credentials.models import CredentialKind, CredentialProvider
from db.types import ModelProvider, RepositoryProvider, RepositorySource
from findings.models import FindingSeverity, FindingStatus
from issue_tracking.schemas import IssueTrackingDetails
from projects.models import ProjectCategory
from remediations.models import RemediationStatus
from reviews.models import ReviewAgentStatus, ReviewCategory, ReviewStatus


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
    issue_tracking_details: IssueTrackingDetails
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
    model_provider: ModelProvider
    model_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
    ]
    avatar: (
        Annotated[
            str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2048)
        ]
        | None
    ) = None
    skills: list[dict[str, object] | str] = Field(default_factory=list, max_length=64)
    credential_id: UUID | None = None


class AgentUpdate(RequestModel):
    name: ShortName | None = None
    personality: Annotated[str, StringConstraints(max_length=4000)] | None = None
    review_category: ReviewCategory | None = None
    model_provider: ModelProvider | None = None
    model_name: (
        Annotated[
            str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
        ]
        | None
    ) = None
    avatar: (
        Annotated[
            str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2048)
        ]
        | None
    ) = None
    skills: list[dict[str, object] | str] | None = Field(default=None, max_length=64)
    credential_id: UUID | None = None


class AgentResponse(RequestModel):
    id: UUID
    name: str
    personality: str | None
    review_category: ReviewCategory
    model_provider: ModelProvider
    model_name: str
    avatar: str | None
    skills: list[dict[str, object] | str]
    credential_id: UUID | None
    configuration_version: int
    created_at: datetime
    updated_at: datetime
    disabled_at: datetime | None


class AgentPage(RequestModel):
    items: list[AgentResponse]
    next_offset: int | None


class AgentModelOption(RequestModel):
    id: str
    label: str


class AgentModelProviderOption(RequestModel):
    id: ModelProvider
    label: str
    models: list[AgentModelOption]


class AgentModelCatalogResponse(RequestModel):
    providers: list[AgentModelProviderOption]


class LocalSourceSnapshot(RequestModel):
    source_id: UUID
    integrity_algorithm: Annotated[
        str, StringConstraints(pattern=r"^sha256-directory-manifest-v1$")
    ]
    digest: HashString


class ReviewCreate(RequestModel):
    project_id: UUID
    agent_ids: list[UUID] = Field(min_length=1, max_length=100)
    local_source_snapshot: LocalSourceSnapshot | None = None

    @model_validator(mode="after")
    def validate_unique_values(self) -> ReviewCreate:
        if len(set(self.agent_ids)) != len(self.agent_ids):
            raise ValueError("review agents must be unique")
        return self


class ReviewSourceSnapshotResponse(RequestModel):
    source_kind: RepositorySource
    source_identifier: str
    integrity_algorithm: str
    revision: str
    captured_at: datetime


class ReviewAgentResponse(RequestModel):
    assignment_id: UUID
    agent_id: UUID
    name: str
    review_category: ReviewCategory
    model_provider: str
    model_name: str
    personality: str | None
    skills: list[dict[str, object] | str]
    configuration_version: int
    status: ReviewAgentStatus
    assigned_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class ReviewResponse(RequestModel):
    id: UUID
    project_id: UUID
    source_revision: str
    source_snapshot: ReviewSourceSnapshotResponse
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
    review_id: UUID
    agent_id: UUID
    reviewing_agent: ReviewingAgentResponse
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


class ReviewingAgentResponse(RequestModel):
    assignment_id: UUID
    agent_id: UUID
    display_name: str
    specialization: ReviewCategory


class FindingUpdate(RequestModel):
    status: FindingStatus


class FindingPage(RequestModel):
    items: list[FindingResponse]
    next_offset: int | None


class PullRequestSummary(RequestModel):
    url: str
    number: int
    is_merged: bool


class RemediationResponse(RequestModel):
    id: UUID
    project_id: UUID
    finding_id: UUID
    proposed_diff: str
    pull_request: PullRequestSummary | None
    status: RemediationStatus
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class RemediationPromptResponse(RequestModel):
    prompt_text: str


class LocalFileBackupResponse(RequestModel):
    id: UUID
    remediation_id: UUID
    file_path: str
    backup_path: str
    source_hash: str
    applied_hash: str
    created_at: datetime
    updated_at: datetime


class LocalRemediationApplyFile(RequestModel):
    file_path: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=1,
            max_length=2_000,
        ),
    ]
    backup_reference: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=1,
            max_length=2_000,
        ),
    ]
    source_hash: HashString
    applied_hash: HashString

    @field_validator("file_path", "backup_reference")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        if (
            value.startswith("/")
            or "\\" in value
            or any(segment == ".." for segment in value.split("/"))
        ):
            raise ValueError("must be a relative path without parent traversal")
        return value


class LocalRemediationApply(RequestModel):
    files: Annotated[
        list[LocalRemediationApplyFile],
        Field(min_length=1, max_length=100),
    ]

    @model_validator(mode="after")
    def validate_unique_file_paths(self) -> LocalRemediationApply:
        paths = [file.file_path for file in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError("file paths must be unique")
        return self


class CredentialCreate(RequestModel):
    provider: CredentialProvider
    kind: CredentialKind
    # Present for user-named BYOK keys. When absent, creation keeps the
    # historical one-active-credential-per-provider upsert (used by the
    # OAuth connect flow and legacy unnamed keys).
    name: (
        Annotated[
            str,
            StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
        ]
        | None
    ) = None
    payload: dict[str, object]


class CredentialResponse(RequestModel):
    id: UUID
    provider: CredentialProvider
    kind: CredentialKind
    name: str | None
    active: bool
    created_at: datetime
    updated_at: datetime
    revoked_at: datetime | None


class CredentialPage(RequestModel):
    items: list[CredentialResponse]
    next_offset: int | None
