"""Compatibility re-exports for the pre-modular model import path.

New code should import models from the owning feature package. The aliases in
this module preserve the existing import surface during the transition.
"""

from agents.models import Agent
from artifacts.models import LocalFileBackup, PullRequest
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
    ProjectSourceType,
    RepositorySource,
    ReviewCategory,
    native_enum,
)
from external_repositories.models import ExternalRepository
from findings.models import Finding, FindingSeverity, FindingStatus
from projects.models import Project, ProjectCategory
from remediations.models import Remediation, RemediationStatus
from reviews.models import (
    ReviewRun,
    ReviewRunAgent,
    ReviewRunAgentStatus,
    ReviewRunCategory,
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
    "LocalFileBackup",
    "PasswordCredential",
    "PasswordRecoveryToken",
    "Project",
    "ProjectCategory",
    "ProjectSourceType",
    "PullRequest",
    "RefreshToken",
    "Remediation",
    "RemediationStatus",
    "RepositorySource",
    "ReviewCategory",
    "ReviewRun",
    "ReviewRunAgent",
    "ReviewRunAgentStatus",
    "ReviewRunCategory",
    "ReviewStatus",
    "User",
    "UserStatus",
    "native_enum",
]
