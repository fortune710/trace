from __future__ import annotations

from fastapi import Response

from auth.config import AuthSettings


def set_auth_cookies(response: Response, *, access_token: str, refresh_token: str, settings: AuthSettings) -> None:
    """Set HttpOnly bearer cookies without ever serializing tokens into JSON."""
    response.set_cookie(
        key=settings.access_cookie_name,
        value=access_token,
        max_age=settings.access_token_minutes * 60,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite=settings.cookie_same_site,
    )
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=refresh_token,
        max_age=settings.refresh_token_days * 24 * 60 * 60,
        path="/auth",
        secure=settings.cookie_secure,
        httponly=True,
        samesite=settings.cookie_same_site,
    )


def set_csrf_cookie(response: Response, *, csrf_token: str, settings: AuthSettings) -> None:
    response.set_cookie(
        key=settings.csrf_cookie_name,
        value=csrf_token,
        max_age=settings.refresh_token_days * 24 * 60 * 60,
        path="/",
        secure=settings.cookie_secure,
        httponly=False,
        samesite=settings.cookie_same_site,
    )


def clear_auth_cookies(response: Response, settings: AuthSettings) -> None:
    response.delete_cookie(key=settings.access_cookie_name, path="/")
    response.delete_cookie(key=settings.refresh_cookie_name, path="/auth")
    response.delete_cookie(key=settings.csrf_cookie_name, path="/")
