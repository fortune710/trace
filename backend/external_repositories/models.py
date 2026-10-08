"""External provider connection models."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.types import RepositorySource, native_enum


class ExternalRepository(Base):
    __tablename__ = "external_repositories"
    __table_args__ = (
        sa.UniqueConstraint(
            "owner_id", "id", name="external_repositories_owner_id_id_key"
        ),
        sa.CheckConstraint(
            "source = 'github'", name="external_repositories_github_only_check"
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "credential_id"],
            ["private.credentials.owner_id", "private.credentials.id"],
            name="external_repositories_owner_credential_fkey",
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
    source: Mapped[RepositorySource] = mapped_column(
        native_enum(RepositorySource, "repository_source", "public"), nullable=False
    )
    external_user_id: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    credential_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    connected_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
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


sa.Index(
    "external_repositories_owner_active_key",
    ExternalRepository.owner_id,
    ExternalRepository.source,
    ExternalRepository.external_user_id,
    unique=True,
    postgresql_where=ExternalRepository.revoked_at.is_(None),
)


__all__ = ["ExternalRepository"]
