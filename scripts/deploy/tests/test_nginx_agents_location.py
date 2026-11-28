"""Regression: bare /api/v1/agents must not be redirected by the avatar prefix."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

HTTPS_CONF = (
    Path(__file__).resolve().parents[3] / "config" / "nginx" / "https.conf"
)

COMMENT_RE = re.compile(r"#.*?$", re.MULTILINE)
SERVER_RE = re.compile(r"server\s*\{", re.MULTILINE)
LOCATION_RE = re.compile(
    r"location\s+(=|\^~|~)?\s*([^\s{]+)\s*\{",
    re.MULTILINE,
)


def _strip_comments(source: str) -> str:
    return COMMENT_RE.sub("", source)


def _block_body(source: str, open_brace_index: int) -> str:
    depth = 0
    for index in range(open_brace_index, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[open_brace_index + 1 : index]
    raise AssertionError("Unbalanced braces in NGINX config")


def _parse_servers(source: str) -> list[str]:
    cleaned = _strip_comments(source)
    servers: list[str] = []
    for match in SERVER_RE.finditer(cleaned):
        servers.append(_block_body(cleaned, match.end() - 1))
    return servers


def _parse_locations(server_body: str) -> list[tuple[str, str, str]]:
    """Return (modifier, path, body) for each location in a server body."""
    locations: list[tuple[str, str, str]] = []
    for match in LOCATION_RE.finditer(server_body):
        modifier = match.group(1) or ""
        path = match.group(2)
        body = _block_body(server_body, match.end() - 1)
        locations.append((modifier, path, body))
    return locations


def _direct_location_directives(body: str) -> str:
    """Return a location body with nested location blocks removed."""

    cleaned = body
    while True:
        match = LOCATION_RE.search(cleaned)
        if match is None:
            return cleaned
        open_brace = match.end() - 1
        depth = 0
        end: int | None = None
        for index in range(open_brace, len(cleaned)):
            char = cleaned[index]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    end = index + 1
                    break
        if end is None:
            raise AssertionError("Unbalanced braces while stripping nested locations")
        cleaned = cleaned[: match.start()] + cleaned[end:]


class NginxAgentsLocationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conf = HTTPS_CONF.read_text(encoding="utf-8")
        self.servers = _parse_servers(self.conf)
        self.https_server = next(
            (
                body
                for body in self.servers
                if "listen 8443 ssl;" in body
                and "traceapi.fortunealebiosu.dev" in body
            ),
            None,
        )
        self.assertIsNotNone(
            self.https_server,
            "Expected an HTTPS server for traceapi.fortunealebiosu.dev",
        )
        assert self.https_server is not None
        self.locations = _parse_locations(self.https_server)

    def test_exact_agents_collection_location_proxies_backend(self) -> None:
        exact = [
            (modifier, path, body)
            for modifier, path, body in self.locations
            if modifier == "=" and path == "/api/v1/agents"
        ]
        self.assertEqual(
            len(exact),
            1,
            "NGINX must exact-match /api/v1/agents so the agents/ prefix "
            "does not emit a trailing-slash redirect with the internal :8443 port",
        )
        self.assertIn(
            "include /etc/nginx/trace/backend-proxy.conf;",
            exact[0][2],
        )

    def test_agents_prefix_still_covers_avatars(self) -> None:
        prefix = [
            (modifier, path, body)
            for modifier, path, body in self.locations
            if modifier == "^~" and path == "/api/v1/agents/"
        ]
        self.assertEqual(len(prefix), 1)
        nested = _parse_locations(prefix[0][2])
        avatar = [
            (modifier, path, body)
            for modifier, path, body in nested
            if modifier == "~" and path == "^/api/v1/agents/[^/]+/avatar$"
        ]
        self.assertEqual(len(avatar), 1)
        self.assertIn("client_max_body_size 512k;", avatar[0][2])
        self.assertIn(
            "include /etc/nginx/trace/backend-proxy.conf;",
            avatar[0][2],
        )

    def test_internal_port_redirects_are_disabled_on_https_server(self) -> None:
        assert self.https_server is not None
        self.assertIn("absolute_redirect off;", self.https_server)
        self.assertIn("port_in_redirect off;", self.https_server)

    def test_exact_agents_location_precedes_prefix(self) -> None:
        paths = [
            (modifier, path)
            for modifier, path, _body in self.locations
            if path in {"/api/v1/agents", "/api/v1/agents/"}
        ]
        self.assertEqual(
            paths,
            [
                ("=", "/api/v1/agents"),
                ("^~", "/api/v1/agents/"),
            ],
            "Exact /api/v1/agents must be declared before the agents/ prefix",
        )

    def test_skills_and_agent_skill_paths_proxy_without_collection_redirect(self) -> None:
        """Attach/list skill URLs already include a path under /agents/ or /api/.

        They match `^~ /api/v1/agents/` or `^~ /api/` and must not depend on the
        bare `/api/v1/agents` exact-match workaround (that bug was collection-only).
        """

        agents_prefix = [
            body
            for modifier, path, body in self.locations
            if modifier == "^~" and path == "/api/v1/agents/"
        ]
        api_prefix = [
            body
            for modifier, path, body in self.locations
            if modifier == "^~" and path == "/api/"
        ]
        self.assertEqual(len(agents_prefix), 1)
        self.assertEqual(len(api_prefix), 1)
        # Nested avatar location also includes the backend proxy; assert the
        # parent prefix has its own include so skill paths stay proxied if the
        # nested block is removed.
        self.assertIn(
            "include /etc/nginx/trace/backend-proxy.conf;",
            _direct_location_directives(agents_prefix[0]),
        )
        self.assertIn(
            "include /etc/nginx/trace/backend-proxy.conf;",
            _direct_location_directives(api_prefix[0]),
        )
        # No dedicated trailing-slash trap for /skills — catalog lives under /api/.
        skills_exact = [
            path
            for _modifier, path, _body in self.locations
            if path in {"/api/v1/skills", "/api/v1/skills/"}
        ]
        self.assertEqual(skills_exact, [])


if __name__ == "__main__":
    unittest.main()
