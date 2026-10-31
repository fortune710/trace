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
from db.types import ModelProvider, RepositorySource, ReviewCategory
from projects.models import ProjectCategory
from resources.routes import _credential_response, install_resource_routes
from resources.schemas import AgentCreate, PageQuery, ProjectCreate, ReviewCreate


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
        "/reviews/{review_id}/findings",
        "/findings/{finding_id}",
        "/findings/{finding_id}/remediations",
        "/remediations/{remediation_id}",
        "/remediations/{remediation_id}/prompt",
        "/remediations/{remediation_id}/reject",
        "/remediations/{remediation_id}/local-file-backup",
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

    review_create = openapi_paths["/reviews"]["post"]
    review_schema = review_create["requestBody"]["content"]["application/json"][
        "schema"
    ]
    review_reference = review_schema["$ref"].rsplit("/", 1)[-1]
    review_properties = app.openapi()["components"]["schemas"][review_reference]
    assert set(review_properties["properties"]) == {
        "project_id",
        "agent_ids",
        "local_source_snapshot",
        "local_source_upload",
    }
    assert set(review_properties["required"]) == {"project_id", "agent_ids"}
    assert any(
        parameter["name"] == "Idempotency-Key"
        and parameter["in"] == "header"
        and parameter["required"] is True
        for parameter in review_create["parameters"]
    )

    remediation_collection = openapi_paths["/findings/{finding_id}/remediations"]
    assert set(remediation_collection) == {"get"}
    assert "/remediations/{remediation_id}/approve" not in openapi_paths

    remediation_get = openapi_paths["/remediations/{remediation_id}"]["get"]
    remediation_reference = remediation_get["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"].rsplit("/", 1)[-1]
    remediation_properties = app.openapi()["components"]["schemas"][
        remediation_reference
    ]["properties"]
    assert "prompt_text" not in remediation_properties

    prompt_get = openapi_paths["/remediations/{remediation_id}/prompt"]["get"]
    prompt_reference = prompt_get["responses"]["200"]["content"]["application/json"][
        "schema"
    ]["$ref"].rsplit("/", 1)[-1]
    prompt_properties = app.openapi()["components"]["schemas"][prompt_reference][
        "properties"
    ]
    assert set(prompt_properties) == {"prompt_text"}


def test_page_query_uses_one_based_pages_and_derives_internal_offset() -> None:
    pagination = PageQuery(page=3, page_size=25)

    assert pagination.limit == 25
    assert pagination.offset == 50
    assert set(PageQuery.model_fields) == {"page", "page_size"}

    with pytest.raises(ValidationError):
        PageQuery(page=0)
    with pytest.raises(ValidationError):
        PageQuery(page_size=101)


def test_project_and_review_requests_reject_duplicates() -> None:
    with pytest.raises(ValidationError):
        ProjectCreate(
            name="local project",
            source=RepositorySource.LOCAL,
            local_path_hash="a" * 64,
            external_repository_id="should-not-be-present",
        )

    with pytest.raises(ValidationError):
        duplicate_agent_id = uuid4()
        ReviewCreate(
            project_id=uuid4(),
            agent_ids=[duplicate_agent_id, duplicate_agent_id],
        )


def test_agents_accept_marketing_and_only_supported_model_providers() -> None:
    agent = AgentCreate(
        name="growth reviewer",
        review_category=ReviewCategory.MARKETING,
        model_provider=ModelProvider.XAI,
        model_name="grok-4.7",
        avatar="agent-defaults/growth-reviewer",
    )

    assert agent.review_category is ReviewCategory.MARKETING
    assert agent.model_provider is ModelProvider.XAI
    assert agent.avatar == "agent-defaults/growth-reviewer"

    with pytest.raises(ValidationError):
        AgentCreate(
            name="unsupported provider",
            review_category=ReviewCategory.SECURITY,
            model_provider="github",
            model_name="not-a-model",
        )


def test_github_project_import_requires_server_resolved_source_selection() -> None:
    valid = ProjectCreate(
        name="github project",
        source=RepositorySource.GITHUB,
        repository_id="12345",
        branch_name="main",
        category=ProjectCategory.OTHER,
    )
    assert valid.repository_id == "12345"

    invalid_payloads = (
        {
            "name": "github project",
            "source": RepositorySource.GITHUB,
            "repository_id": "12345",
            "category": ProjectCategory.OTHER,
        },
        {
            "name": "github project",
            "source": RepositorySource.GITHUB,
            "repository_id": "12345",
            "branch_name": "main",
        },
        {
            "name": "github project",
            "source": RepositorySource.GITHUB,
            "repository_id": "12345",
            "branch_name": "main",
            "category": ProjectCategory.OTHER,
            "current_revision": "a" * 40,
        },
        {
            "name": "github project",
            "source": RepositorySource.GITHUB,
            "repository_id": "12345",
            "branch_name": "main",
            "category": ProjectCategory.OTHER,
            "external_repository_connection_id": str(uuid4()),
        },
    )
    for payload in invalid_payloads:
        with pytest.raises(ValidationError):
            ProjectCreate(**payload)


def test_credential_response_is_metadata_only() -> None:
    metadata = CredentialMetadata(
        id=uuid4(),
        owner_id=uuid4(),
        provider=CredentialProvider.GITHUB,
        kind=CredentialKind.OAUTH,
        name=None,
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
        "name": None,
        "active": True,
        "created_at": metadata.created_at,
        "updated_at": metadata.updated_at,
        "revoked_at": None,
    }
    assert (
        not {"owner_id", "ciphertext", "nonce", "key_reference", "payload"}
        & response.keys()
    )
