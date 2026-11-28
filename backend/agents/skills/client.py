"""Authenticated HTTP client for the skills.sh catalog API."""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import quote, urljoin, urlparse

import httpx

from agents.skills.config import SkillsSettings, get_skills_settings
from agents.skills.logging import skills_log, timed_step
from agents.skills.validation import (
    SkillValidationError,
    normalize_skill_id,
    skill_detail_path,
    validate_public_https_url,
    validate_search_query,
)

ALLOWED_SKILLS_HOSTS = frozenset({"skills.sh", "www.skills.sh"})
_RATE_LIMIT_HEADERS = (
    "x-ratelimit-limit",
    "x-ratelimit-remaining",
    "x-ratelimit-reset",
    "retry-after",
)


class SkillsShError(Exception):
    """Base error for skills.sh catalog failures."""

    def __init__(self, code: str, *, status_code: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


class SkillsShAuthError(SkillsShError):
    def __init__(self) -> None:
        super().__init__("skills_auth_failed", status_code=401)


class SkillsShConfigError(SkillsShError):
    """Raised when neither proxy nor direct OIDC transport is usable."""

    def __init__(self, code: str = "skills_transport_unconfigured") -> None:
        super().__init__(code, status_code=503)


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
        # Production rewrite without ?path= can collapse nested detail URLs to
        # /api/v1/skills (catalog list). Catalog list/search then "works" while
        # attach fails because this payload is not a skill detail.
        if isinstance(payload.get("data"), list) and "files" not in payload:
            skills_log(
                "skills_upstream_normalize",
                level=40,
                step="normalize_detail",
                outcome="error",
                error_code="skills_proxy_path_mismatch",
                upstream_path=path,
                skill_id=skill_id,
                transport=self._settings.transport_mode(),
                provider="skills.sh",
            )
            raise SkillsShError("skills_proxy_path_mismatch", status_code=502)
        return self._normalize_detail(payload)

    def _normalize_detail(self, payload: dict[str, Any]) -> dict[str, Any]:
        with timed_step("skills_upstream_normalize", "normalize_detail") as step_fields:
            skill_id = normalize_skill_id(str(payload.get("id", "")))
            source = str(payload.get("source", ""))
            slug = str(payload.get("slug", ""))
            step_fields["skill_id"] = skill_id
            step_fields["skill_source"] = source
            step_fields["skill_slug"] = slug
            if f"{source}/{slug}" != skill_id:
                step_fields["outcome"] = "error"
                step_fields["error_code"] = "skills_payload_invalid"
                raise SkillsShError("skills_payload_invalid", status_code=502)

            files_raw = payload.get("files")
            files: list[dict[str, str]] = []
            skill_md = ""
            if isinstance(files_raw, list):
                if len(files_raw) > self._settings.max_files:
                    step_fields["outcome"] = "error"
                    step_fields["error_code"] = "skills_payload_too_large"
                    step_fields["file_count"] = len(files_raw)
                    raise SkillsShError("skills_payload_too_large", status_code=502)
                for entry in files_raw:
                    if not isinstance(entry, dict):
                        continue
                    path = entry.get("path")
                    contents = entry.get("contents")
                    if not isinstance(path, str) or not isinstance(contents, str):
                        continue
                    if ".." in path or path.startswith("/") or len(path) > 512:
                        step_fields["outcome"] = "error"
                        step_fields["error_code"] = "skills_payload_invalid"
                        raise SkillsShError("skills_payload_invalid", status_code=502)
                    if len(contents) > self._settings.max_file_chars:
                        step_fields["outcome"] = "error"
                        step_fields["error_code"] = "skills_payload_too_large"
                        raise SkillsShError("skills_payload_too_large", status_code=502)
                    files.append({"path": path, "contents": contents})
                    if path == "SKILL.md" or path.endswith("/SKILL.md"):
                        skill_md = contents

            if not skill_md:
                step_fields["outcome"] = "error"
                step_fields["error_code"] = "skills_missing_skill_md"
                raise SkillsShError("skills_missing_skill_md", status_code=502)
            if len(skill_md) > self._settings.max_skill_md_chars:
                step_fields["outcome"] = "error"
                step_fields["error_code"] = "skills_payload_too_large"
                step_fields["skill_md_chars"] = len(skill_md)
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

            step_fields["file_count"] = len(files)
            step_fields["skill_md_chars"] = len(skill_md)
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
        transport = self._settings.transport_mode()
        if transport == "proxy":
            return self._get_via_proxy(path, params=params)
        if transport == "proxy_misconfigured":
            skills_log(
                "skills_upstream_request",
                level=40,
                step="transport_config",
                outcome="error",
                error_code="skills_proxy_secret_missing",
                transport=transport,
                upstream_path=path,
            )
            raise SkillsShConfigError("skills_proxy_secret_missing")
        if transport == "direct_oidc":
            return self._get_direct(path, params=params)
        skills_log(
            "skills_upstream_request",
            level=40,
            step="transport_config",
            outcome="error",
            error_code="skills_transport_unconfigured",
            transport=transport,
            upstream_path=path,
            proxy_url_configured=bool(self._settings.proxy_url),
            proxy_secret_configured=self._settings.proxy_secret is not None,
            oidc_configured=self._settings.oidc_token is not None,
        )
        raise SkillsShConfigError()

    def _get_direct(
        self,
        path: str,
        *,
        params: dict[str, str | int] | None = None,
    ) -> dict[str, Any]:
        base = self._settings.base_url.rstrip("/") + "/"
        parsed = urlparse(base)
        if parsed.scheme != "https" or parsed.hostname not in ALLOWED_SKILLS_HOSTS:
            skills_log(
                "skills_upstream_request",
                level=40,
                step="transport_config",
                outcome="error",
                error_code="skills_base_url_invalid",
                transport="direct_oidc",
                upstream_path=path,
            )
            raise SkillsShError("skills_base_url_invalid")
        token = self._oidc_token()
        if token is None:
            skills_log(
                "skills_upstream_request",
                level=40,
                step="transport_config",
                outcome="error",
                error_code="skills_transport_unconfigured",
                transport="direct_oidc",
                upstream_path=path,
            )
            raise SkillsShConfigError()
        url = urljoin(base, path.lstrip("/"))
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "trace-api/skills-sh",
        }
        started = time.perf_counter()
        try:
            with httpx.Client(
                timeout=self._settings.timeout_seconds,
                transport=self._transport,
                follow_redirects=False,
            ) as client:
                response = client.get(url, params=params, headers=headers)
        except httpx.HTTPError as error:
            skills_log(
                "skills_upstream_request",
                level=30,
                step="upstream_fetch",
                outcome="error",
                error_code="skills_unavailable",
                error_type=type(error).__name__,
                transport="direct_oidc",
                upstream_path=path,
                upstream_latency_ms=round((time.perf_counter() - started) * 1000, 3),
            )
            raise SkillsShUnavailableError() from None
        return self._parse_response(
            response,
            path=path,
            transport="direct_oidc",
            started=started,
        )

    def _get_via_proxy(
        self,
        path: str,
        *,
        params: dict[str, str | int] | None = None,
    ) -> dict[str, Any]:
        proxy = self._settings.proxy_url
        if not proxy:
            raise SkillsShConfigError()
        parsed = urlparse(proxy)
        if parsed.scheme != "https" or not parsed.hostname:
            skills_log(
                "skills_upstream_request",
                level=40,
                step="transport_config",
                outcome="error",
                error_code="skills_proxy_url_invalid",
                transport="proxy",
                upstream_path=path,
            )
            raise SkillsShError("skills_proxy_url_invalid")
        secret = self._settings.proxy_secret
        if secret is None:
            raise SkillsShConfigError("skills_proxy_secret_missing")
        query = ""
        if params:
            query = "?" + "&".join(
                f"{quote(str(key))}={quote(str(value))}"
                for key, value in params.items()
            )
        # Nested path (for example /api/v1/skills/search) is appended to the
        # proxy base. The Vite Vercel project must route /api/skills-sh/:path*
        # to frontend/api/skills-sh/[...path].ts so sanitizePath keeps the suffix.
        target = f"{proxy.rstrip('/')}{path}{query}"
        headers = {
            "Authorization": f"Bearer {secret.get_secret_value()}",
            "Accept": "application/json",
            "User-Agent": "trace-api/skills-sh-proxy",
        }
        started = time.perf_counter()
        try:
            with httpx.Client(
                timeout=self._settings.timeout_seconds,
                transport=self._transport,
                follow_redirects=False,
            ) as client:
                response = client.get(target, headers=headers)
        except httpx.HTTPError as error:
            skills_log(
                "skills_upstream_request",
                level=30,
                step="upstream_fetch",
                outcome="error",
                error_code="skills_unavailable",
                error_type=type(error).__name__,
                transport="proxy",
                upstream_path=path,
                proxy_host=parsed.hostname,
                upstream_latency_ms=round((time.perf_counter() - started) * 1000, 3),
            )
            raise SkillsShUnavailableError() from None
        return self._parse_response(
            response,
            path=path,
            transport="proxy",
            started=started,
            proxy_host=parsed.hostname,
        )

    def _oidc_token(self) -> str | None:
        token = self._settings.oidc_token
        if token is None:
            return None
        value = token.get_secret_value().strip()
        return value or None

    def _parse_response(
        self,
        response: httpx.Response,
        *,
        path: str,
        transport: str,
        started: float,
        proxy_host: str | None = None,
    ) -> dict[str, Any]:
        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        rate_limit_fields = {
            header.replace("-", "_"): response.headers.get(header)
            for header in _RATE_LIMIT_HEADERS
            if response.headers.get(header)
        }
        common = {
            "step": "upstream_fetch",
            "transport": transport,
            "upstream_path": path,
            "upstream_status": response.status_code,
            "upstream_latency_ms": latency_ms,
            "provider": "skills.sh",
            **rate_limit_fields,
        }
        if proxy_host:
            common["proxy_host"] = proxy_host

        if response.status_code == 401:
            skills_log(
                "skills_upstream_request",
                level=40,
                outcome="error",
                error_code="skills_auth_failed",
                **common,
            )
            raise SkillsShAuthError()
        if response.status_code == 404:
            skills_log(
                "skills_upstream_request",
                level=30,
                outcome="error",
                error_code="skills_not_found",
                **common,
            )
            raise SkillsShNotFoundError()
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            parsed_retry: int | None = None
            if retry_after and retry_after.isdigit():
                parsed_retry = int(retry_after)
            rate_fields = {
                key: value for key, value in common.items() if key != "retry_after"
            }
            skills_log(
                "skills_upstream_request",
                level=30,
                outcome="error",
                error_code="skills_rate_limited",
                retry_after=parsed_retry,
                **rate_fields,
            )
            raise SkillsShRateLimitError(retry_after=parsed_retry)
        if response.status_code >= 500:
            skills_log(
                "skills_upstream_request",
                level=30,
                outcome="error",
                error_code="skills_unavailable",
                **common,
            )
            raise SkillsShUnavailableError()
        if response.status_code >= 400:
            skills_log(
                "skills_upstream_request",
                level=40,
                outcome="error",
                error_code="skills_request_invalid",
                **common,
            )
            raise SkillsShError(
                "skills_request_invalid", status_code=response.status_code
            )
        try:
            payload = response.json()
        except ValueError as error:
            skills_log(
                "skills_upstream_request",
                level=40,
                outcome="error",
                error_code="skills_payload_invalid",
                error_type=type(error).__name__,
                **common,
            )
            raise SkillsShError("skills_payload_invalid", status_code=502) from error
        if not isinstance(payload, dict):
            skills_log(
                "skills_upstream_request",
                level=40,
                outcome="error",
                error_code="skills_payload_invalid",
                **common,
            )
            raise SkillsShError("skills_payload_invalid", status_code=502)
        skills_log(
            "skills_upstream_request",
            outcome="success",
            **common,
        )
        return payload
