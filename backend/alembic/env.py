from __future__ import annotations

import os
from logging.config import fileConfig
from typing import Any

from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy import MetaData, engine_from_config, pool

import db.model_registry  # noqa: F401
from alembic import context
from db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def alembic_metadata() -> MetaData:
    """Normalize PostgreSQL's default ``public`` schema for autogeneration.

    Runtime models retain explicit ``public`` schema names.  PostgreSQL's
    inspector represents that default schema as ``None``; a copied metadata
    graph keeps Alembic comparisons semantic without changing ``Base.metadata``
    or the application model contract.
    """

    metadata = MetaData()
    for table in Base.metadata.tables.values():
        table.to_metadata(
            metadata,
            schema=None if table.schema == "public" else table.schema,
        )

    for table in metadata.tables.values():
        for constraint in table.foreign_key_constraints:
            for foreign_key in constraint.elements:
                if foreign_key._given_tokens.schema == "public":
                    foreign_key._given_tokens = foreign_key._given_tokens._replace(
                        schema=None
                    )
    return metadata


target_metadata = alembic_metadata()


def compare_type(
    _context: Any,
    _inspected_column: Any,
    _metadata_column: Any,
    inspected_type: Any,
    metadata_type: Any,
) -> bool | None:
    """Ignore enum schema qualification differences, but detect value drift."""

    if (
        isinstance(inspected_type, SQLAlchemyEnum)
        and isinstance(metadata_type, SQLAlchemyEnum)
        and inspected_type.name == metadata_type.name
        and tuple(inspected_type.enums or ()) == tuple(metadata_type.enums or ())
    ):
        return False
    return None


def migration_database_url() -> str:
    url = os.getenv("MIGRATION_DATABASE_URL")
    if not url:
        raise RuntimeError(
            "MIGRATION_DATABASE_URL must be set before running migrations"
        )
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=migration_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "pyformat"},
        compare_type=compare_type,
        include_schemas=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = migration_database_url()
    connectable = engine_from_config(
        configuration, prefix="sqlalchemy.", poolclass=pool.NullPool
    )

    with connectable.connect() as connection:
        # PostgreSQL treats ``public`` as the default schema.  The models keep
        # the explicit name to make ownership and cross-schema foreign keys
        # unambiguous, while Alembic reflects the default schema as ``None``.
        # Normalize that representation during comparison so a model-only
        # refactor does not appear as table/FK churn.
        connection = connection.execution_options(schema_translate_map={"public": None})
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=compare_type,
            include_schemas=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
