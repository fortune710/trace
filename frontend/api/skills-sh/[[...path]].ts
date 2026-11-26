/**
 * Vercel serverless OIDC proxy for skills.sh.
 *
 * Optional catch-all covers both `/api/skills-sh` and nested paths such as
 * `/api/skills-sh/api/v1/skills/search` while preserving the pathname that
 * sanitizePath uses to build the upstream skills.sh URL.
 *
 * Trace's FastAPI API runs on a VPS and cannot mint Vercel OIDC tokens.
 * Point SKILLS_SH_PROXY_URL at `/api/skills-sh` and set SKILLS_SH_PROXY_SECRET
 * on both sides. Enable OIDC Federation on the Vercel project first.
 *
 * Auth: Authorization: Bearer <SKILLS_SH_PROXY_SECRET>
 * Never expose the OIDC token or proxy secret to browsers.
 */

import { getVercelOidcToken } from "@vercel/oidc"

const SKILLS_SH_ORIGIN = "https://skills.sh"
const ALLOWED_PREFIXES = ["/api/v1/skills"] as const

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
  })
}

function authorized(request: Request): boolean {
  const expected = process.env.SKILLS_SH_PROXY_SECRET
  if (!expected) {
    return false
  }
  const header = request.headers.get("authorization")
  if (!header?.startsWith("Bearer ")) {
    return false
  }
  const provided = header.slice("Bearer ".length)
  if (provided.length !== expected.length) {
    return false
  }
  let mismatch = 0
  for (let index = 0; index < provided.length; index += 1) {
    mismatch |= provided.charCodeAt(index) ^ expected.charCodeAt(index)
  }
  return mismatch === 0
}

function sanitizePath(pathname: string): string | null {
  if (!pathname.startsWith("/api/skills-sh")) {
    return null
  }
  const upstream = pathname.replace(/^\/api\/skills-sh/, "") || "/api/v1/skills"
  if (
    upstream.includes("..") ||
    upstream.includes("\\") ||
    upstream.includes("://")
  ) {
    return null
  }
  if (
    !ALLOWED_PREFIXES.some(
      (prefix) => upstream === prefix || upstream.startsWith(`${prefix}/`),
    )
  ) {
    return null
  }
  return upstream
}

export default {
  async fetch(request: Request): Promise<Response> {
    if (request.method !== "GET" && request.method !== "HEAD") {
      return json(405, {
        error: "method_not_allowed",
        message: "Only GET is supported.",
      })
    }
    if (!authorized(request)) {
      return json(401, {
        error: "unauthorized",
        message: "Invalid proxy credentials.",
      })
    }

    const url = new URL(request.url)
    const upstreamPath = sanitizePath(url.pathname)
    if (!upstreamPath) {
      return json(400, {
        error: "invalid_path",
        message: "Path is not allowed.",
      })
    }

    let token: string
    try {
      token = await getVercelOidcToken()
    } catch {
      const fallback = process.env.VERCEL_OIDC_TOKEN
      if (!fallback) {
        return json(503, {
          error: "oidc_unavailable",
          message: "Vercel OIDC token is unavailable.",
        })
      }
      token = fallback
    }

    const upstream = new URL(upstreamPath, SKILLS_SH_ORIGIN)
    upstream.search = url.search

    let response: Response
    try {
      response = await fetch(upstream, {
        method: "GET",
        headers: {
          Authorization: `Bearer ${token}`,
          Accept: "application/json",
          "User-Agent": "trace-skills-sh-proxy",
        },
        redirect: "manual",
      })
    } catch {
      return json(503, {
        error: "upstream_unavailable",
        message: "skills.sh is temporarily unavailable.",
      })
    }

    const body = await response.text()
    return new Response(body, {
      status: response.status,
      headers: {
        "content-type":
          response.headers.get("content-type") ?? "application/json",
        "cache-control": "no-store",
        "x-ratelimit-limit": response.headers.get("x-ratelimit-limit") ?? "",
        "x-ratelimit-remaining":
          response.headers.get("x-ratelimit-remaining") ?? "",
        "x-ratelimit-reset": response.headers.get("x-ratelimit-reset") ?? "",
        "retry-after": response.headers.get("retry-after") ?? "",
      },
    })
  },
}
