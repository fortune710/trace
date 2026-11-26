"""Authenticated HTTP client for the skills.sh catalog API."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote, urljoin, urlparse

import httpx

from agents.skills.config import SkillsSettings, get_skills_settings
from agents.skills.validation import (
    SkillValidationError,
    normalize_skill_id,
    skill_detail_path,
    validate_public_https_url,
    validate_search_query,
)

logger = logging.getLogger(__name__)

ALLOWED_SKILLS_HOSTS = frozenset({"skills.sh", "www.skills.sh"})


class SkillsShError(Exception):
    """Base error for skills.sh catalog failures."""

    def __init__(self, code: str, *, status_code: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


class SkillsShAuthError(SkillsShError):
    def __init__(self) -> None:
        super().__init__("skills_auth_failed", status_code=401)


class SkillsShNotFoundError(SkillsShError):
    def __init__(self) -> None:
        super().__init__("skills_not_found", status_code=404)


class SkillsShRateLimitError(SkillsShError):
    def __init__(self, *, retry_after: int | None = None) -> None:
        super().__init__("skills_rate_limited", status_code=429)
        self.retry_after = retry_after


class SkillsShUnavailableError(SkillsShError):
    def __init__(self) -> None:
        super().__init__("skills_unavailable", status_code=503)


class SkillsShClient:
    """Fetch skills.sh catalog data without exposing OIDC tokens to callers."""

    def __init__(
        self,
        settings: SkillsSettings | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._settings = settings or get_skills_settings()
        self._transport = transport

    def list_skills(
        self,
        *,
        view: str = "all-time",
        page: int = 0,
        per_page: int = 20,
        source: str | None = None,
    ) -> dict[str, Any]:
        if view not in {"all-time", "trending", "hot"}:
            raise SkillValidationError("view_invalid")
        if page < 0 or page > 10_000:
            raise SkillValidationError("page_invalid")
        if per_page < 1 or per_page > 100:
            raise SkillValidationError("per_page_invalid")
        params: dict[str, str | int] = {
            "view": view,
            "page": page,
            "per_page": per_page,
        }
        if source is not None:
            # Reuse skill-id source validation by appending a dummy slug.
            normalize_skill_id(f"{source}/placeholder")
            params["source"] = source
        return self._get_json("/api/v1/skills", params=params)

    def search_skills(
        self,
        *,
        query: str,
        limit: int = 20,
        owner: str | None = None,
    ) -> dict[str, Any]:
        cleaned = validate_search_query(query)
        if limit < 1 or limit > 100:
            raise SkillValidationError("limit_invalid")
        params: dict[str, str | int] = {"q": cleaned, "limit": limit}
        if owner is not None:
            if not owner or len(owner) > 100 or "/" in owner or ".." in owner:
                raise SkillValidationError("owner_invalid")
            params["owner"] = owner
        return self._get_json("/api/v1/skills/search", params=params)

    def curated_skills(self) -> dict[str, Any]:
        return self._get_json("/api/v1/skills/curated")

    def get_skill(self, skill_id: str) -> dict[str, Any]:
        path = skill_detail_path(skill_id)
        payload = self._get_json(path)
        return self._normalize_detail(payload)

    def _normalize_detail(self, payload: dict[str, Any]) -> dict[str, Any]:
        skill_id = normalize_skill_id(str(payload.get("id", "")))
        source = str(payload.get("source", ""))
        slug = str(payload.get("slug", ""))
        if f"{source}/{slug}" != skill_id:
            raise SkillsShError("skills_payload_invalid", status_code=502)

        files_raw = payload.get("files")
        files: list[dict[str, str]] = []
        skill_md = ""
        if isinstance(files_raw, list):
            if len(files_raw) > self._settings.max_files:
                raise SkillsShError("skills_payload_too_large", status_code=502)
            for entry in files_raw:
                if not isinstance(entry, dict):
                    continue
                path = entry.get("path")
                contents = entry.get("contents")
                if not isinstance(path, str) or not isinstance(contents, str):
                    continue
                if ".." in path or path.startswith("/") or len(path) > 512:
                    raise SkillsShError("skills_payload_invalid", status_code=502)
                if len(contents) > self._settings.max_file_chars:
                    raise SkillsShError("skills_payload_too_large", status_code=502)
                files.append({"path": path, "contents": contents})
                if path == "SKILL.md" or path.endswith("/SKILL.md"):
                    skill_md = contents

        if not skill_md:
            raise SkillsShError("skills_missing_skill_md", status_code=502)
        if len(skill_md) > self._settings.max_skill_md_chars:
            raise SkillsShError("skills_payload_too_large", status_code=502)

        install_url = payload.get("installUrl")
        url = payload.get("url")
        if not isinstance(url, str):
            url = f"https://skills.sh/{skill_id}"
        validate_public_https_url(url, field="url")
        if install_url is not None:
            validate_public_https_url(
                install_url if isinstance(install_url, str) else None,
                field="install_url",
            )

        source_type = payload.get("sourceType")
        if source_type not in {"github", "well-known"}:
            source_type = (
                "well-known" if "." in source and "/" not in source else "github"
            )

        return {
            "id": skill_id,
            "slug": slug,
            "name": str(payload.get("name") or slug),
            "source": source,
            "source_type": source_type,
            "installs": payload.get("installs"),
            "install_url": install_url if isinstance(install_url, str) else None,
            "url": url,
            "hash": payload.get("hash")
            if isinstance(payload.get("hash"), str)
            else None,
            "skill_md": skill_md,
            "files": files,
        }

    def _get_json(
        self,
        path: str,
        *,
        params: dict[str, str | int] | None = None,
    ) -> dict[str, Any]:
        if self._settings.proxy_url:
            return self._get_via_proxy(path, params=params)
        return self._get_direct(path, params=params)

    def _get_direct(
        self,
        path: str,
        *,
        params: dict[str, str | int] | None = None,
    ) -> dict[str, Any]:
        base = self._settings.base_url.rstrip("/") + "/"
        parsed = urlparse(base)
        if parsed.scheme != "https" or parsed.hostname not in ALLOWED_SKILLS_HOSTS:
            raise SkillsShError("skills_base_url_invalid")
        token = self._oidc_token()
        if token is None:
            raise SkillsShAuthError()
        url = urljoin(base, path.lstrip("/"))
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "trace-api/skills-sh",
        }
        try:
            with httpx.Client(
                timeout=self._settings.timeout_seconds,
                transport=self._transport,
                follow_redirects=False,
            ) as client:
                response = client.get(url, params=params, headers=headers)
        except httpx.HTTPError:
            logger.warning("skills.sh request failed", extra={"path": path})
            raise SkillsShUnavailableError() from None
        return self._parse_response(response)

    def _get_via_proxy(
        self,
        path: str,
        *,
        params: dict[str, str | int] | None = None,
    ) -> dict[str, Any]:
        proxy = self._settings.proxy_url
        if not proxy:
            raise SkillsShAuthError()
        parsed = urlparse(proxy)
        if parsed.scheme != "https" or not parsed.hostname:
            raise SkillsShError("skills_proxy_url_invalid")
        secret = self._settings.proxy_secret
        if secret is None:
            raise SkillsShAuthError()
        query = ""
        if params:
            query = "?" + "&".join(
                f"{quote(str(key))}={quote(str(value))}"
                for key, value in params.items()
            )
        target = f"{proxy.rstrip('/')}{path}{query}"
        headers = {
            "Authorization": f"Bearer {secret.get_secret_value()}",
            "Accept": "application/json",
            "User-Agent": "trace-api/skills-sh-proxy",
        }
        try:
            with httpx.Client(
                timeout=self._settings.timeout_seconds,
                transport=self._transport,
                follow_redirects=False,
            ) as client:
                response = client.get(target, headers=headers)
        except httpx.HTTPError:
            logger.warning("skills.sh proxy request failed", extra={"path": path})
            raise SkillsShUnavailableError() from None
        return self._parse_response(response)

    def _oidc_token(self) -> str | None:
        token = self._settings.oidc_token
        if token is None:
            return None
        value = token.get_secret_value().strip()
        return value or None

    def _parse_response(self, response: httpx.Response) -> dict[str, Any]:
        if response.status_code == 401:
            raise SkillsShAuthError()
        if response.status_code == 404:
            raise SkillsShNotFoundError()
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            parsed_retry: int | None = None
            if retry_after and retry_after.isdigit():
                parsed_retry = int(retry_after)
            raise SkillsShRateLimitError(retry_after=parsed_retry)
        if response.status_code >= 500:
            raise SkillsShUnavailableError()
        if response.status_code >= 400:
            raise SkillsShError(
                "skills_request_invalid", status_code=response.status_code
            )
        try:
            payload = response.json()
        except ValueError as error:
            raise SkillsShError("skills_payload_invalid", status_code=502) from error
        if not isinstance(payload, dict):
            raise SkillsShError("skills_payload_invalid", status_code=502)
        return payload
