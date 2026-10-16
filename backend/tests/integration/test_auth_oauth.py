from __future__ import annotations

import pytest
import sqlalchemy as sa

from auth.models import AuthIdentity, AuthUser, IdentityProvider
from auth.service import AuthService
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
    finally:
        with integration_engine.begin() as connection:
            connection.execute(sa.delete(AuthUser).where(AuthUser.email == email))
