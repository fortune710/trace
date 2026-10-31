from __future__ import annotations

import pytest
import sqlalchemy as sa

from agents.defaults import DEFAULT_AGENTS
from agents.models import Agent
from auth.models import AuthIdentity, AuthUser, IdentityProvider
from auth.service import AuthService
from db.rls import principal_transaction
from notifications.models import Notification, NotificationEventType
from users.models import User

pytestmark = pytest.mark.integration


def test_google_oauth_persists_the_provider_display_name(
    integration_engine, integration_settings
) -> None:
    service = AuthService.from_settings(
        engine=integration_engine,
        settings=integration_settings,
    )
    subject = "google-display-name-test"
    email = "google-display-name-test@example.test"

    try:
        result = service.oauth_login(
            provider=IdentityProvider.GOOGLE,
            subject=subject,
            email=email,
            display_name="Google Test User",
        )

        assert result.outcome == "authenticated"
        with integration_engine.begin() as connection:
            row = connection.execute(
                sa.select(AuthUser.email, User.display_name)
                .join(User, User.id == AuthUser.id)
                .join(AuthIdentity, AuthIdentity.user_id == AuthUser.id)
                .where(
                    AuthIdentity.provider == IdentityProvider.GOOGLE,
                    AuthIdentity.provider_subject == subject,
                )
            ).one()
        assert row.email == email
        assert row.display_name == "Google Test User"
        assert result.user_id is not None
        with principal_transaction(integration_engine, result.user_id) as connection:
            keys = set(
                connection.execute(
                    sa.select(Agent.default_key).where(Agent.owner_id == result.user_id)
                ).scalars()
            )
        assert keys == {agent.key for agent in DEFAULT_AGENTS}

        repeated = service.oauth_login(
            provider=IdentityProvider.GOOGLE,
            subject=subject,
            email=email,
            display_name="Google Test User",
        )
        assert repeated.user_id == result.user_id
        with principal_transaction(integration_engine, result.user_id) as connection:
            count = connection.scalar(
                sa.select(sa.func.count())
                .select_from(Agent)
                .where(Agent.owner_id == result.user_id)
            )
        assert count == len(DEFAULT_AGENTS)
    finally:
        with integration_engine.begin() as connection:
            connection.execute(sa.delete(AuthUser).where(AuthUser.email == email))


def test_email_registration_seeds_default_agents(
    integration_engine, integration_settings
) -> None:
    service = AuthService.from_settings(
        engine=integration_engine,
        settings=integration_settings,
    )
    email = "default-agents-registration@example.test"

    try:
        user_id = service.register(
            email=email,
            password="InitialPassword123!",
            display_name="Default Agent Test",
            destination="https://trace.example.test/verify-email",
        )
        assert user_id is not None
        with principal_transaction(integration_engine, user_id) as connection:
            keys = set(
                connection.execute(
                    sa.select(Agent.default_key).where(Agent.owner_id == user_id)
                ).scalars()
            )
        assert keys == {agent.key for agent in DEFAULT_AGENTS}
    finally:
        with integration_engine.begin() as connection:
            connection.execute(sa.delete(AuthUser).where(AuthUser.email == email))


def test_successful_authentication_events_create_durable_notifications(
    integration_engine,
    integration_settings,
    monkeypatch,
) -> None:
    service = AuthService.from_settings(
        engine=integration_engine,
        settings=integration_settings,
    )
    tokens = iter(
        (
            "verification-token",
            "first-refresh-token",
            "recovery-token",
            "second-refresh-token",
            "oauth-refresh-token",
        )
    )
    monkeypatch.setattr("auth.service.generate_opaque_token", lambda: next(tokens))
    email = "notification-auth-test@example.test"
    oauth_email = "notification-oauth-test@example.test"
    oauth_subject = "notification-oauth-test"

    try:
        user_id = service.register(
            email=email,
            password="InitialPassword123!",
            display_name="Notification Auth Test",
            destination="https://trace.example.test/verify-email",
        )
        assert user_id is not None
        assert service.verify_email(token="verification-token") == user_id

        first_login = service.login(email=email, password="InitialPassword123!")
        assert first_login.outcome == "authenticated"
        assert first_login.tokens is not None

        service.recover_password(
            email=email,
            destination="https://trace.example.test/reset-password",
        )
        assert (
            service.reset_password(
                token="recovery-token", password="ReplacementPassword123!"
            )
            == user_id
        )

        second_login = service.login(
            email=email,
            password="ReplacementPassword123!",
        )
        assert second_login.outcome == "authenticated"
        assert second_login.tokens is not None
        service.logout(refresh_token=second_login.tokens.refresh_token)
        assert (
            service.login(email=email, password="wrong password").outcome == "rejected"
        )

        oauth_login = service.oauth_login(
            provider=IdentityProvider.GOOGLE,
            subject=oauth_subject,
            email=oauth_email,
            display_name="Notification OAuth Test",
        )
        assert oauth_login.outcome == "authenticated"
        assert oauth_login.user_id is not None

        with principal_transaction(integration_engine, user_id) as connection:
            event_types = (
                connection.execute(
                    sa.select(Notification.event_type)
                    .where(Notification.owner_id == user_id)
                    .order_by(Notification.created_at, Notification.id)
                )
                .scalars()
                .all()
            )
        with principal_transaction(
            integration_engine, oauth_login.user_id
        ) as connection:
            oauth_event_types = (
                connection.execute(
                    sa.select(Notification.event_type).where(
                        Notification.owner_id == oauth_login.user_id
                    )
                )
                .scalars()
                .all()
            )

        assert event_types.count(NotificationEventType.ACCOUNT_REGISTERED) == 1
        assert event_types.count(NotificationEventType.EMAIL_VERIFIED) == 1
        assert event_types.count(NotificationEventType.PASSWORD_SIGNED_IN) == 2
        assert event_types.count(NotificationEventType.PASSWORD_RESET) == 1
        assert event_types.count(NotificationEventType.LOGGED_OUT) == 1
        assert oauth_event_types == [NotificationEventType.OAUTH_SIGNED_IN]
    finally:
        with integration_engine.begin() as connection:
            connection.execute(
                sa.delete(AuthUser).where(AuthUser.email.in_((email, oauth_email)))
            )
