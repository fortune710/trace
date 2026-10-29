"""Central SQLAlchemy model import registry for Alembic discovery."""

from agents.models import Agent
from artifacts.models import LocalFileBackup
from audit.models import AuditDeliveryJob
from auth.models import (
    AuthIdentity,
    AuthSession,
    AuthUser,
    EmailDeliveryJob,
    EmailVerificationToken,
    PasswordCredential,
    PasswordRecoveryToken,
    RefreshToken,
)
from credentials.models import (
    Credential,
    CredentialReencryptionItem,
    CredentialReencryptionRun,
)
from external_repositories.models import ExternalRepository
from findings.models import Finding
from issue_tracking.models import IssueLink
from local_projects.models import LocalProjectHandle
from notifications.models import Notification
from projects.models import Project
from remediations.models import (
    Remediation,
    RemediationPullRequestJob,
    RemediationPullRequestOutboxJob,
)
from reviews.models import (
    Review,
    ReviewAgent,
    ReviewAgentAttempt,
    ReviewAgentExecutionConfig,
    ReviewDispatchJob,
)
from users.models import User

__all__ = [
    "Agent",
    "AuditDeliveryJob",
    "AuthIdentity",
    "AuthSession",
    "AuthUser",
    "Credential",
    "CredentialReencryptionItem",
    "CredentialReencryptionRun",
    "EmailDeliveryJob",
    "EmailVerificationToken",
    "ExternalRepository",
    "Finding",
    "IssueLink",
    "LocalFileBackup",
    "LocalProjectHandle",
    "Notification",
    "PasswordCredential",
    "PasswordRecoveryToken",
    "Project",
    "RefreshToken",
    "Remediation",
    "RemediationPullRequestJob",
    "RemediationPullRequestOutboxJob",
    "Review",
    "ReviewAgent",
    "ReviewAgentAttempt",
    "ReviewAgentExecutionConfig",
    "ReviewDispatchJob",
    "User",
]
