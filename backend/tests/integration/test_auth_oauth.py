from __future__ import annotations

import pytest
import sqlalchemy as sa

from agents.defaults import DEFAULT_AGENTS
from agents.models import Agent
from auth.models import AuthIdentity, AuthUser, IdentityProvider
from auth.service import AuthService
from db.rls import principal_transaction
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
                sa.select(AuthUser.id, AuthUser.email, User.display_name)
                .join(User, User.id == AuthUser.id)
                .join(AuthIdentity, AuthIdentity.user_id == AuthUser.id)
                .where(
                    AuthIdentity.provider == IdentityProvider.GOOGLE,
                    AuthIdentity.provider_subject == subject,
                )
            ).one()
        assert row.email == email
        assert row.display_name == "Google Test User"
        with principal_transaction(integration_engine, row.id) as connection:
            defaults = connection.execute(
                sa.select(
                    Agent.default_key,
                    Agent.model_provider,
                    Agent.model_name,
                    Agent.credential_id,
                )
                .where(Agent.owner_id == row.id)
                .order_by(Agent.default_key)
            ).all()
        assert [default.default_key for default in defaults] == sorted(
            agent.key for agent in DEFAULT_AGENTS
        )
        assert all(
            default.model_provider == "openai"
            and default.model_name == "gpt-6.1-sol"
            and default.credential_id is None
            for default in defaults
        )

        repeated = service.oauth_login(
            provider=IdentityProvider.GOOGLE,
            subject=subject,
            email=email,
            display_name="Changed Name Is Ignored",
        )
        assert repeated.outcome == "authenticated"
        with principal_transaction(integration_engine, row.id) as connection:
            assert connection.execute(
                sa.select(sa.func.count())
                .select_from(Agent)
                .where(Agent.owner_id == row.id)
            ).scalar_one() == len(DEFAULT_AGENTS)
    finally:
        with integration_engine.begin() as connection:
            connection.execute(sa.delete(AuthUser).where(AuthUser.email == email))
