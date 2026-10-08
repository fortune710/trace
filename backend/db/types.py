"""Shared SQLAlchemy type helpers and database-wide enum values."""

from __future__ import annotations

from enum import Enum

import sqlalchemy as sa


def native_enum(enum_class: type[Enum], name: str, schema: str) -> sa.Enum:
    """Build a PostgreSQL enum using the Python enum values as labels."""

    return sa.Enum(
        enum_class,
        name=name,
        schema=schema,
        native_enum=True,
        values_callable=lambda enum_type: [member.value for member in enum_type],
    )


class RepositorySource(str, Enum):
    GITHUB = "github"
    LOCAL = "local"


class RepositoryProvider(str, Enum):
    GITHUB = "github"


class ReviewCategory(str, Enum):
    SECURITY = "security"
    ENGINEERING = "engineering"
    PRODUCT = "product"
    LEGAL = "legal"
    ACCESSIBILITY = "accessibility"


class CredentialEncryptionProvider(str, Enum):
    LOCAL = "local"
    VAULT = "vault"


# Compatibility name retained for callers that used the original project enum.
ProjectSourceType = RepositorySource
