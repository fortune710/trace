type RecordedRequest = {
  method: string
  path: string
  body: unknown
}

type DesktopTestApi = {
  baseUrl: string
  requests: RecordedRequest[]
  projectCreateRequests: RecordedRequest[]
  expireSession: () => void
  close: () => void
}

function response(request: Request, body: unknown, status = 200) {
  const headers = {
    "access-control-allow-origin": request.headers.get("origin") ?? "*",
    "access-control-allow-credentials": "true",
    "access-control-allow-headers": "content-type, x-csrf-token",
    "access-control-allow-methods": "GET, POST, OPTIONS",
  }

  if (status === 204) {
    return new Response(null, { status, headers })
  }

  return Response.json(body, {
    status,
    headers,
  })
}

export function startDesktopTestApi(): DesktopTestApi {
  let sessionExpired = false
  const requests: RecordedRequest[] = []
  const projectCreateRequests: RecordedRequest[] = []
  const server = Bun.serve({
    hostname: "127.0.0.1",
    port: 0,
    async fetch(request) {
      if (request.method === "OPTIONS") return response(request, null, 204)

      const url = new URL(request.url)
      const body = request.method === "POST"
        ? await request.json().catch(() => undefined)
        : undefined
      const recorded = { method: request.method, path: url.pathname, body }
      requests.push(recorded)

      if (url.pathname === "/auth/session" && request.method === "GET") {
        return sessionExpired
          ? response(request, { error: { code: "unauthenticated" } }, 401)
          : response(request, { user_id: "desktop-e2e-user", session_id: "desktop-e2e-session" })
      }

      if (url.pathname === "/auth/refresh" && request.method === "POST") {
        return sessionExpired
          ? response(request, { error: { code: "unauthenticated" } }, 401)
          : response(request, { message: "refreshed", csrf_token: "desktop-e2e-csrf" })
      }

      if (url.pathname === "/auth/login" && request.method === "POST") {
        sessionExpired = false
        return response(request, { message: "signed in", csrf_token: "desktop-e2e-csrf" })
      }

      if (url.pathname === "/auth/logout" && request.method === "POST") {
        return response(request, null, 204)
      }

      if (url.pathname === "/api/v1/projects" && request.method === "GET") {
        return response(request, { items: [], next_offset: null })
      }

      if (url.pathname === "/api/v1/projects" && request.method === "POST") {
        projectCreateRequests.push(recorded)
        return response(request, { error: { code: "unexpected_project_api_request" } }, 500)
      }

      return response(request, { error: { code: "not_found" } }, 404)
    },
  })

  return {
    baseUrl: `http://127.0.0.1:${server.port}`,
    requests,
    projectCreateRequests,
    expireSession: () => {
      sessionExpired = true
    },
    close: () => server.stop(true),
  }
}
