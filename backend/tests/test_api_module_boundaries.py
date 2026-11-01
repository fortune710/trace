from auth.config import AuthSettings
from core.v1 import router as v1_router
from main import create_app


def test_resource_endpoints_are_composed_under_v1_only():
    app = create_app(AuthSettings())
    paths = set(app.openapi()["paths"])

    expected = {
        "/api/v1/projects",
        "/api/v1/agents",
        "/api/v1/agents/{agent_id}/avatar",
        "/api/v1/reviews",
        "/api/v1/findings/{finding_id}",
        "/api/v1/remediations/{remediation_id}",
        "/api/v1/credentials",
        "/api/v1/remediations/{remediation_id}/pull-request",
        "/api/v1/repositories",
        "/api/v1/repositories/{repository_identifier}/branches",
    }
    assert expected <= paths
    assert not {"/projects", "/agents", "/reviews", "/credentials"} & paths
    assert v1_router.prefix == "/api/v1"

    openapi = app.openapi()["paths"]
    pull_request_create = openapi["/api/v1/remediations/{remediation_id}/pull-request"][
        "post"
    ]
    assert "requestBody" not in pull_request_create
    repository_parameters = {
        parameter["name"]
        for parameter in openapi["/api/v1/repositories"]["get"]["parameters"]
    }
    branch_parameters = {
        parameter["name"]
        for parameter in openapi[
            "/api/v1/repositories/{repository_identifier}/branches"
        ]["get"]["parameters"]
    }
    assert {"source", "page", "page_size"} <= repository_parameters
    assert {"repository_identifier", "source", "page", "page_size"} <= branch_parameters

    avatar = openapi["/api/v1/agents/{agent_id}/avatar"]
    assert set(avatar) == {"get", "post", "delete"}
    upload_body = avatar["post"]["requestBody"]["content"]["multipart/form-data"]
    upload_schema_name = upload_body["schema"]["$ref"].rsplit("/", 1)[-1]
    upload_schema = app.openapi()["components"]["schemas"][upload_schema_name]
    assert set(upload_schema["properties"]) == {"file", "config"}
    assert upload_schema["required"] == ["file"]
    assert "204" in avatar["delete"]["responses"]
    assert "200" in avatar["post"]["responses"]
    agent_properties = app.openapi()["components"]["schemas"]["AgentResponse"][
        "properties"
    ]
    assert "avatar_config" in agent_properties
    for request_schema in ("AgentCreate", "AgentUpdate"):
        request_properties = app.openapi()["components"]["schemas"][request_schema][
            "properties"
        ]
        assert "avatar_config" not in request_properties
    assert "security" not in avatar["get"]

    project_create_schema = app.openapi()["components"]["schemas"]["ProjectCreate"]
    assert {
        "name",
        "source",
        "repository_id",
        "branch_name",
        "category",
    } <= project_create_schema["properties"].keys()
    assert (
        "external_repository_connection_id" not in project_create_schema["properties"]
    )
    assert "current_revision" in project_create_schema["properties"]


def test_feature_packages_expose_modular_model_imports():
    from agents.models import Agent
    from artifacts.models import LocalFileBackup
    from credentials.models import Credential
    from findings.models import Finding
    from projects.models import Project
    from remediations.models import Remediation
    from reviews.models import Review, ReviewAgent

    assert all(
        model.__table__.metadata is Project.__table__.metadata
        for model in (
            Agent,
            Credential,
            Finding,
            Remediation,
            LocalFileBackup,
            Review,
            ReviewAgent,
        )
    )
