"""Private storage for agent avatar image bytes."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from agents.models import Agent  # noqa: F401  (registers public.agents first)
from db.base import Base

agent_avatars = sa.Table(
    "agent_avatars",
    Base.metadata,
    sa.Column("owner_id", UUID(as_uuid=True), nullable=False),
    sa.Column("agent_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("content_type", sa.Text, nullable=False),
    sa.Column("data", sa.LargeBinary, nullable=False),
    sa.Column("sha256", sa.Text, nullable=False),
    sa.Column("byte_size", sa.Integer, nullable=False),
    sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    ),
    sa.CheckConstraint("byte_size <= 262144", name="agent_avatars_byte_size_check"),
    sa.CheckConstraint(
        "octet_length(data) = byte_size", name="agent_avatars_byte_size_match_check"
    ),
    sa.ForeignKeyConstraint(
        ["owner_id", "agent_id"],
        ["public.agents.owner_id", "public.agents.id"],
        name="agent_avatars_owner_agent_fkey",
        ondelete="CASCADE",
    ),
    schema="private",
)

__all__ = ["agent_avatars"]
