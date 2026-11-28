"""Regression: bare /api/v1/agents must not be redirected by the avatar prefix."""

from __future__ import annotations

import unittest
from pathlib import Path

HTTPS_CONF = (
    Path(__file__).resolve().parents[3] / "config" / "nginx" / "https.conf"
)


class NginxAgentsLocationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conf = HTTPS_CONF.read_text(encoding="utf-8")

    def test_exact_agents_collection_location_exists(self) -> None:
        self.assertIn(
            "location = /api/v1/agents {",
            self.conf,
            "NGINX must exact-match /api/v1/agents so the agents/ prefix "
            "does not emit a trailing-slash redirect with the internal :8443 port",
        )

    def test_agents_prefix_still_covers_avatars(self) -> None:
        self.assertIn("location ^~ /api/v1/agents/ {", self.conf)
        self.assertIn(
            "location ~ ^/api/v1/agents/[^/]+/avatar$",
            self.conf,
        )

    def test_internal_port_redirects_are_disabled(self) -> None:
        self.assertIn("absolute_redirect off;", self.conf)
        self.assertIn("port_in_redirect off;", self.conf)

    def test_exact_agents_location_precedes_prefix(self) -> None:
        exact = self.conf.index("location = /api/v1/agents {")
        prefix = self.conf.index("location ^~ /api/v1/agents/ {")
        self.assertLess(
            exact,
            prefix,
            "Exact /api/v1/agents must be declared before the agents/ prefix",
        )


if __name__ == "__main__":
    unittest.main()
