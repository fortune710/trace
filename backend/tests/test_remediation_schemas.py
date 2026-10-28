import pytest
from pydantic import ValidationError

from issue_tracking.models import IssueProviderName
from remediations.schemas import RemediationIssueCreate


def test_github_remediation_destinations_are_project_resolved() -> None:
    issue = RemediationIssueCreate.model_validate(
        {"destination": {"provider": "github"}}
    )

    assert issue.destination.provider is IssueProviderName.GITHUB


@pytest.mark.parametrize(
    "destination",
    (
        {"provider": "github", "owner": "acme"},
        {"provider": "github", "repository": "trace"},
        {"provider": "github", "unexpected": "value"},
    ),
)
def test_github_remediation_destinations_reject_client_repository_coordinates(
    destination: dict[str, str],
) -> None:
    with pytest.raises(ValidationError):
        RemediationIssueCreate.model_validate({"destination": destination})


def test_remediation_issue_accepts_project_resolved_linear_destination() -> None:
    issue = RemediationIssueCreate.model_validate(
        {
            "destination": {
                "provider": "linear",
            }
        }
    )

    assert issue.destination.provider is IssueProviderName.LINEAR


@pytest.mark.parametrize(
    "payload",
    (
        {"destination": {"provider": "linear", "team_id": "not-a-uuid"}},
        {"destination": {"provider": "unsupported"}},
        {"destination": {"provider": "github"}, "unexpected": "value"},
    ),
)
def test_remediation_issue_destination_rejects_invalid_values(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        RemediationIssueCreate.model_validate(payload)
