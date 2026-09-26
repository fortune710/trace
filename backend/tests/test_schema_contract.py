import sqlalchemy as sa

from db.base import Base
from db.models import AuthIdentity, AuthUser, Credential, Project, User


def test_string_columns_use_text_and_provider_fields_use_native_enums() -> None:
    assert isinstance(AuthUser.__table__.c.email.type, sa.Text)
    assert isinstance(AuthIdentity.__table__.c.provider_subject.type, sa.Text)
    assert isinstance(Project.__table__.c.name.type, sa.Text)
    assert isinstance(Credential.__table__.c.key_version.type, sa.Text)
    assert isinstance(AuthIdentity.__table__.c.provider.type, sa.Enum)
    assert isinstance(Project.__table__.c.source_type.type, sa.Enum)
    assert AuthIdentity.__table__.c.provider.type.native_enum
    assert Project.__table__.c.source_type.type.native_enum


def test_all_auth_and_public_tables_match_the_database_contract() -> None:
    expected_tables = {
        "auth": {"identities", "password_credentials", "sessions", "users"},
        "public": {"projects", "users"},
    }
    actual_tables: dict[str, set[str]] = {}

    for table in Base.metadata.tables.values():
        if table.schema in expected_tables:
            actual_tables.setdefault(table.schema, set()).add(table.name)

    assert actual_tables == expected_tables


def test_private_tables_remain_outside_the_auth_and_public_schemas() -> None:
    assert Credential.__table__.schema == "private"
