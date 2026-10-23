"""Artifact database models."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class PullRequest(Base):
    __tablename__ = "pull_requests"
    __table_args__ = (
        sa.UniqueConstraint("owner_id", "id", name="pull_requests_owner_id_id_key"),
        sa.UniqueConstraint(
            "owner_id", "remediation_id", name="pull_requests_owner_remediation_key"
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "remediation_id"],
            ["public.remediations.owner_id", "public.remediations.id"],
            name="pull_requests_owner_remediation_fkey",
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
    remediation_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    repository_url: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    pull_request_number: Mapped[int] = mapped_column(sa.BigInteger(), nullable=False)
    pull_request_url: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    branch_name: Mapped[str] = mapped_column(sa.Text(), nullable=False)
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


class LocalFileBackup(Base):
    __tablename__ = "local_file_backups"
    __table_args__ = (
        sa.UniqueConstraint(
            "owner_id", "id", name="local_file_backups_owner_id_id_key"
        ),
        sa.UniqueConstraint(
            "owner_id",
            "remediation_id",
            name="local_file_backups_owner_remediation_key",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "remediation_id"],
            ["public.remediations.owner_id", "public.remediations.id"],
            name="local_file_backups_owner_remediation_fkey",
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
    remediation_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    file_path: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    backup_path: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    source_hash: Mapped[bytes] = mapped_column(sa.LargeBinary(), nullable=False)
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
    "pull_requests_owner_created_idx",
    PullRequest.owner_id,
    PullRequest.created_at.desc(),
)
sa.Index(
    "local_file_backups_owner_created_idx",
    LocalFileBackup.owner_id,
    LocalFileBackup.created_at.desc(),
)


__all__ = ["LocalFileBackup", "PullRequest"]
