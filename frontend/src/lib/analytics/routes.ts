const ROUTE_PATTERNS: Array<{ pattern: RegExp; route: string }> = [
  { pattern: /^\/$/, route: "/" },
  { pattern: /^\/sign-in\/?$/, route: "/sign-in" },
  { pattern: /^\/sign-up\/?$/, route: "/sign-up" },
  { pattern: /^\/forgot-password\/?$/, route: "/forgot-password" },
  { pattern: /^\/reset-password\/?$/, route: "/reset-password" },
  { pattern: /^\/auth\/verify\/?$/, route: "/auth/verify" },
  { pattern: /^\/auth\/callback\/?$/, route: "/auth/callback" },
  { pattern: /^\/account\/?$/, route: "/account" },
  { pattern: /^\/projects\/?$/, route: "/projects" },
  { pattern: /^\/projects\/[^/]+\/?$/, route: "/projects/:projectId" },
  { pattern: /^\/reviews\/[^/]+\/findings\/[^/]+\/?$/, route: "/reviews/:reviewId/findings/:findingId" },
  { pattern: /^\/reviews\/[^/]+\/?$/, route: "/reviews/:reviewId" },
  { pattern: /^\/agents\/?$/, route: "/agents" },
  { pattern: /^\/agents\/[^/]+\/?$/, route: "/agents/:agentId" },
  { pattern: /^\/settings\/integrations\/?$/, route: "/settings/integrations" },
  { pattern: /^\/integrations\/?$/, route: "/integrations" },
  { pattern: /^\/notifications\/?$/, route: "/notifications" },
  { pattern: /^\/settings\/api-keys\/?$/, route: "/settings/api-keys" },
  { pattern: /^\/settings\/credentials\/?$/, route: "/settings/credentials" },
  { pattern: /^\/settings\/?$/, route: "/settings" },
  { pattern: /^\/learn-more\/?$/, route: "/learn-more" },
]

export function normalizeRoutePattern(pathname: string): string {
  const path = pathname.split("?")[0] || "/"
  for (const entry of ROUTE_PATTERNS) {
    if (entry.pattern.test(path)) {
      return entry.route
    }
  }
  return path
}
