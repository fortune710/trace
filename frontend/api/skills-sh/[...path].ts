/// <reference types="node" />
/**
 * Vercel serverless OIDC proxy for skills.sh.
 *
 * Catch-all route covers nested paths such as
 * `/api/skills-sh/api/v1/skills/search`. Pair with the vercel.json rewrite so
 * Vite SPA hosting still invokes this function for every nested proxy URL
 * while preserving the suffix that sanitizePath maps to skills.sh.
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

function resolveProxyPathname(url: URL): string {
  // Vercel splat rewrites may surface the remainder as ?path=a/b/c while the
  // request pathname is the literal catch-all route `/api/skills-sh/[...path]`.
  // Prefer the query splat so nested proxy paths survive sanitizePath.
  const splat = url.searchParams.getAll("path").join("/")
  if (splat) {
    return `/api/skills-sh/${splat.replace(/^\/+/, "")}`
  }
  if (url.pathname.startsWith("/api/skills-sh/")) {
    return url.pathname
  }
  return url.pathname
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

function upstreamSearch(url: URL): string {
  const params = new URLSearchParams(url.search)
  params.delete("path")
  const serialized = params.toString()
  return serialized ? `?${serialized}` : ""
}

function proxyLog(
  fields: Record<string, string | number | boolean | null | undefined>,
): void {
  // Never log Authorization, OIDC tokens, proxy secrets, or response bodies.
  console.log(
    JSON.stringify({
      event: "skills_sh_proxy",
      ...fields,
    }),
  )
}

export default {
  async fetch(request: Request): Promise<Response> {
    const started = Date.now()
    if (request.method !== "GET" && request.method !== "HEAD") {
      proxyLog({
        step: "method_check",
        outcome: "error",
        error_code: "method_not_allowed",
        method: request.method,
        status_code: 405,
        duration_ms: Date.now() - started,
      })
      return json(405, {
        error: "method_not_allowed",
        message: "Only GET is supported.",
      })
    }
    if (!authorized(request)) {
      proxyLog({
        step: "auth",
        outcome: "error",
        error_code: "unauthorized",
        proxy_secret_configured: Boolean(process.env.SKILLS_SH_PROXY_SECRET),
        status_code: 401,
        duration_ms: Date.now() - started,
      })
      return json(401, {
        error: "unauthorized",
        message: "Invalid proxy credentials.",
      })
    }

    const url = new URL(request.url)
    const resolvedPath = resolveProxyPathname(url)
    const upstreamPath = sanitizePath(resolvedPath)
    if (!upstreamPath) {
      proxyLog({
        step: "path_sanitize",
        outcome: "error",
        error_code: "invalid_path",
        resolved_path: resolvedPath.slice(0, 200),
        status_code: 400,
        duration_ms: Date.now() - started,
      })
      return json(400, {
        error: "invalid_path",
        message: "Path is not allowed.",
      })
    }

    let token: string
    let oidcSource: "vercel_oidc" | "env_fallback" = "vercel_oidc"
    try {
      token = await getVercelOidcToken()
    } catch {
      const fallback = process.env.VERCEL_OIDC_TOKEN
      if (!fallback) {
        proxyLog({
          step: "oidc",
          outcome: "error",
          error_code: "oidc_unavailable",
          upstream_path: upstreamPath,
          status_code: 503,
          duration_ms: Date.now() - started,
        })
        return json(503, {
          error: "oidc_unavailable",
          message: "Vercel OIDC token is unavailable.",
        })
      }
      oidcSource = "env_fallback"
      token = fallback
    }

    const upstream = new URL(upstreamPath, SKILLS_SH_ORIGIN)
    upstream.search = upstreamSearch(url)
    const upstreamStarted = Date.now()

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
      proxyLog({
        step: "upstream_fetch",
        outcome: "error",
        error_code: "upstream_unavailable",
        upstream_path: upstreamPath,
        oidc_source: oidcSource,
        transport: "proxy",
        provider: "skills.sh",
        status_code: 503,
        upstream_latency_ms: Date.now() - upstreamStarted,
        duration_ms: Date.now() - started,
      })
      return json(503, {
        error: "upstream_unavailable",
        message: "skills.sh is temporarily unavailable.",
      })
    }

    const body = await response.text()
    proxyLog({
      step: "upstream_fetch",
      outcome: response.ok ? "success" : "error",
      upstream_path: upstreamPath,
      upstream_status: response.status,
      oidc_source: oidcSource,
      transport: "proxy",
      provider: "skills.sh",
      ratelimit_limit: response.headers.get("x-ratelimit-limit"),
      ratelimit_remaining: response.headers.get("x-ratelimit-remaining"),
      ratelimit_reset: response.headers.get("x-ratelimit-reset"),
      retry_after: response.headers.get("retry-after"),
      upstream_latency_ms: Date.now() - upstreamStarted,
      duration_ms: Date.now() - started,
      status_code: response.status,
    })
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
