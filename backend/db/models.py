"""Compatibility re-exports for the pre-modular model import path.

New code should import models from the owning feature package. The aliases in
this module preserve the existing import surface during the transition.
"""

from agents.models import Agent
from artifacts.models import LocalFileBackup
from audit.models import AuditDeliveryJob, AuditDeliveryStatus
from auth.models import (
    AuthIdentity,
    AuthSession,
    AuthUser,
    EmailDeliveryJob,
    EmailDeliveryKind,
    EmailDeliveryStatus,
    EmailVerificationToken,
    IdentityProvider,
    PasswordCredential,
    PasswordRecoveryToken,
    RefreshToken,
    UserStatus,
)
from credentials.models import (
    Credential,
    CredentialKind,
    CredentialProvider,
    CredentialReencryptionItem,
    CredentialReencryptionItemStatus,
    CredentialReencryptionRun,
    CredentialReencryptionStatus,
)
from db.types import (
    CredentialEncryptionProvider,
    ModelProvider,
    ProjectSourceType,
    RepositoryProvider,
    RepositorySource,
    ReviewCategory,
    native_enum,
)
from external_repositories.models import ExternalRepository
from findings.models import Finding, FindingSeverity, FindingStatus
from issue_tracking.models import IssueLink, IssueLinkState, IssueProviderName
from local_projects.models import LocalProjectHandle
from notifications.models import (
    Notification,
    NotificationCategory,
    NotificationEventType,
)
from projects.models import Project, ProjectCategory
from remediations.models import (
    Remediation,
    RemediationPullRequestJob,
    RemediationPullRequestJobStatus,
    RemediationPullRequestOutboxJob,
    RemediationPullRequestOutboxStatus,
    RemediationStatus,
)
from reviews.models import (
    Review,
    ReviewAgent,
    ReviewAgentStatus,
    ReviewDispatchJob,
    ReviewDispatchStatus,
    ReviewStatus,
)
from users.models import User

__all__ = [
    "Agent",
    "AuditDeliveryJob",
    "AuditDeliveryStatus",
    "AuthIdentity",
    "AuthSession",
    "AuthUser",
    "Credential",
    "CredentialEncryptionProvider",
    "CredentialKind",
    "CredentialProvider",
    "CredentialReencryptionItem",
    "CredentialReencryptionItemStatus",
    "CredentialReencryptionRun",
    "CredentialReencryptionStatus",
    "EmailDeliveryJob",
    "EmailDeliveryKind",
    "EmailDeliveryStatus",
    "EmailVerificationToken",
    "ExternalRepository",
    "Finding",
    "FindingSeverity",
    "FindingStatus",
    "IdentityProvider",
    "IssueLink",
    "IssueLinkState",
    "IssueProviderName",
    "LocalFileBackup",
    "LocalProjectHandle",
    "ModelProvider",
    "Notification",
    "NotificationCategory",
    "NotificationEventType",
    "PasswordCredential",
    "PasswordRecoveryToken",
    "Project",
    "ProjectCategory",
    "ProjectSourceType",
    "RefreshToken",
    "Remediation",
    "RemediationPullRequestJob",
    "RemediationPullRequestJobStatus",
    "RemediationPullRequestOutboxJob",
    "RemediationPullRequestOutboxStatus",
    "RemediationStatus",
    "RepositoryProvider",
    "RepositorySource",
    "Review",
    "ReviewAgent",
    "ReviewAgentStatus",
    "ReviewCategory",
    "ReviewDispatchJob",
    "ReviewDispatchStatus",
    "ReviewStatus",
    "User",
    "UserStatus",
    "native_enum",
]
