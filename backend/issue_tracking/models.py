"""Owner-scoped links from findings to external issue trackers."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.types import native_enum


class IssueProviderName(str, Enum):
    GITHUB = "github"
    LINEAR = "linear"


class IssueLinkState(str, Enum):
    PENDING = "pending"
    CREATED = "created"
    FAILED = "failed"


class IssueLink(Base):
    __tablename__ = "issue_links"
    __table_args__ = (
        sa.UniqueConstraint("owner_id", "id", name="issue_links_owner_id_id_key"),
        sa.UniqueConstraint(
            "owner_id",
            "finding_id",
            "provider",
            "destination_id",
            name="issue_links_owner_finding_provider_destination_key",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "finding_id"],
            ["public.findings.owner_id", "public.findings.id"],
            name="issue_links_owner_finding_fkey",
            ondelete="CASCADE",
        ),
        {"schema": "public"},
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("public.uuidv7()"),
    )
    owner_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        sa.ForeignKey("public.users.id", ondelete="CASCADE"),
        nullable=False,
    )
    finding_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    provider: Mapped[IssueProviderName] = mapped_column(
        native_enum(IssueProviderName, "issue_provider_name", "public"),
        nullable=False,
    )
    destination_id: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    external_identifier: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    external_url: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    state: Mapped[IssueLinkState] = mapped_column(
        native_enum(IssueLinkState, "issue_link_state", "public"),
        nullable=False,
        server_default=sa.text("'pending'::public.issue_link_state"),
    )
    failure_code: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )


sa.Index(
    "issue_links_owner_finding_provider_idx",
    IssueLink.owner_id,
    IssueLink.finding_id,
    IssueLink.provider,
)


__all__ = ["IssueLink", "IssueLinkState", "IssueProviderName"]
