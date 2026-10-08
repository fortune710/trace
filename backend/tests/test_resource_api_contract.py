from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from auth.config import AuthSettings
from auth.credential_service import CredentialMetadata
from credentials.models import (
    CredentialEncryptionProvider,
    CredentialKind,
    CredentialProvider,
)
from db.types import RepositorySource
from resources.routes import _credential_response, install_resource_routes
from resources.schemas import PageQuery, ProjectCreate, ReviewCreate
from reviews.models import ReviewCategory


def test_resource_routes_register_the_complete_owner_scoped_surface() -> None:
    app = FastAPI()
    install_resource_routes(app, AuthSettings())

    paths = {route.path for route in app.routes if hasattr(route, "path")}

    assert {
        "/projects",
        "/projects/{project_id}",
        "/projects/{project_id}/restore",
        "/agents",
        "/agents/{agent_id}",
        "/reviews",
        "/reviews/{review_id}",
        "/reviews/{review_id}/cancel",
        "/reviews/{review_id}/retry",
        "/reviews/{review_id}/findings",
        "/findings/{finding_id}",
        "/findings/{finding_id}/remediations",
        "/remediations/{remediation_id}",
        "/remediations/{remediation_id}/approve",
        "/remediations/{remediation_id}/reject",
        "/remediations/{remediation_id}/pull-request",
        "/remediations/{remediation_id}/local-file-backup",
        "/pull-requests/{artifact_id}",
        "/local-file-backups/{artifact_id}",
        "/credentials",
        "/credentials/{credential_id}",
        "/credentials/{credential_id}/rotate",
    } <= paths

    openapi_paths = app.openapi()["paths"]
    for path in (
        "/projects",
        "/agents",
        "/reviews",
        "/reviews/{review_id}/findings",
        "/credentials",
    ):
        query_parameters = {
            parameter["name"] for parameter in openapi_paths[path]["get"]["parameters"]
        }
        assert {"page", "page_size"} <= query_parameters
        assert not {"limit", "offset"} & query_parameters


def test_page_query_uses_one_based_pages_and_derives_internal_offset() -> None:
    pagination = PageQuery(page=3, page_size=25)

    assert pagination.limit == 25
    assert pagination.offset == 50
    assert set(PageQuery.model_fields) == {"page", "page_size"}

    with pytest.raises(ValidationError):
        PageQuery(page=0)
    with pytest.raises(ValidationError):
        PageQuery(page_size=101)


def test_project_and_review_requests_reject_cross_field_duplicates() -> None:
    with pytest.raises(ValidationError):
        ProjectCreate(
            name="local project",
            source=RepositorySource.LOCAL,
            local_path_hash="a" * 64,
            external_repository_id="should-not-be-present",
        )

    with pytest.raises(ValidationError):
        ReviewCreate(
            project_id=uuid4(),
            source_revision="main",
            selected_categories=[ReviewCategory.SECURITY, ReviewCategory.SECURITY],
        )


def test_credential_response_is_metadata_only() -> None:
    metadata = CredentialMetadata(
        id=uuid4(),
        owner_id=uuid4(),
        provider=CredentialProvider.GITHUB,
        kind=CredentialKind.OAUTH,
        encryption_provider=CredentialEncryptionProvider.VAULT,
        key_version="v1",
        aad_version="v1",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        revoked_at=None,
    )

    response = _credential_response(metadata)

    assert response == {
        "id": metadata.id,
        "provider": CredentialProvider.GITHUB,
        "kind": CredentialKind.OAUTH,
        "active": True,
        "created_at": metadata.created_at,
        "updated_at": metadata.updated_at,
        "revoked_at": None,
    }
    assert (
        not {"owner_id", "ciphertext", "nonce", "key_reference", "payload"}
        & response.keys()
    )
