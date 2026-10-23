"""Project database models."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.types import RepositorySource, native_enum


class ProjectCategory(str, Enum):
    ENTERTAINMENT = "entertainment"
    EDUCATIONAL = "educational"
    SPORTS = "sports"
    GAMING = "gaming"
    BUSINESS = "business"
    HEALTH = "health"
    FINANCE = "finance"
    SOCIAL = "social"
    PRODUCTIVITY = "productivity"
    E_COMMERCE = "e_commerce"
    OTHER = "other"


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        sa.UniqueConstraint("owner_id", "id", name="projects_owner_id_id_key"),
        sa.CheckConstraint(
            "(source = 'github' AND external_repository_id IS NOT NULL "
            "AND external_repository_connection_id IS NOT NULL AND local_path_hash IS NULL) "
            "OR (source = 'local' AND local_path_hash IS NOT NULL "
            "AND external_repository_id IS NULL AND external_repository_connection_id IS NULL)",
            name="projects_source_reference_check",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "external_repository_connection_id"],
            [
                "public.external_repositories.owner_id",
                "public.external_repositories.id",
            ],
            name="projects_owner_external_repository_connection_fkey",
            ondelete="RESTRICT",
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
    name: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    source: Mapped[RepositorySource] = mapped_column(
        native_enum(RepositorySource, "repository_source", "public"), nullable=False
    )
    external_repository_id: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    external_repository_connection_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=True
    )
    local_path_hash: Mapped[bytes | None] = mapped_column(
        sa.LargeBinary(), nullable=True
    )
    source_hash: Mapped[bytes | None] = mapped_column(sa.LargeBinary(), nullable=True)
    current_revision: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    category: Mapped[ProjectCategory] = mapped_column(
        native_enum(ProjectCategory, "project_category", "public"),
        nullable=False,
        server_default=sa.text("'other'::public.project_category"),
    )
    auto_create_pull_requests: Mapped[bool] = mapped_column(
        sa.Boolean(), nullable=False, server_default=sa.text("false")
    )
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
    archived_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )


sa.Index("projects_owner_created_idx", Project.owner_id, Project.created_at.desc())
sa.Index(
    "projects_owner_external_repository_key",
    Project.owner_id,
    Project.external_repository_id,
    unique=True,
    postgresql_where=sa.text("source = 'github' AND archived_at IS NULL"),
)
sa.Index(
    "projects_owner_local_path_key",
    Project.owner_id,
    Project.local_path_hash,
    unique=True,
    postgresql_where=sa.text("source = 'local' AND archived_at IS NULL"),
)


__all__ = ["Project", "ProjectCategory", "RepositorySource"]
