from auth.config import AuthSettings
from core.v1 import router as v1_router
from main import create_app


def test_resource_endpoints_are_composed_under_v1_only():
    app = create_app(AuthSettings())
    paths = set(app.openapi()["paths"])

    expected = {
        "/api/v1/projects",
        "/api/v1/agents",
        "/api/v1/reviews",
        "/api/v1/findings/{finding_id}",
        "/api/v1/remediations/{remediation_id}",
        "/api/v1/credentials",
        "/api/v1/pull-requests/{artifact_id}",
        "/api/v1/repositories",
        "/api/v1/repositories/{repository_identifier}/branches",
    }
    assert expected <= paths
    assert not {"/projects", "/agents", "/reviews", "/credentials"} & paths
    assert v1_router.prefix == "/api/v1"

    openapi = app.openapi()["paths"]
    repository_parameters = {
        parameter["name"] for parameter in openapi["/api/v1/repositories"]["get"]["parameters"]
    }
    branch_parameters = {
        parameter["name"]
        for parameter in openapi["/api/v1/repositories/{repository_identifier}/branches"]["get"]["parameters"]
    }
    assert {"source", "page", "page_size"} <= repository_parameters
    assert {"repository_identifier", "source", "page", "page_size"} <= branch_parameters


def test_feature_packages_expose_modular_model_imports():
    from agents.models import Agent
    from artifacts.models import LocalFileBackup, PullRequest
    from credentials.models import Credential
    from findings.models import Finding
    from projects.models import Project
    from remediations.models import Remediation
    from reviews.models import ReviewRun, ReviewRunAgent, ReviewRunCategory

    assert all(
        model.__table__.metadata is Project.__table__.metadata
        for model in (
            Agent,
            Credential,
            Finding,
            Remediation,
            PullRequest,
            LocalFileBackup,
            ReviewRun,
            ReviewRunAgent,
            ReviewRunCategory,
        )
    )
