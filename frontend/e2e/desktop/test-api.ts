type RecordedRequest = {
  method: string
  path: string
  body: unknown
}

type DesktopTestApi = {
  baseUrl: string
  requests: RecordedRequest[]
  projectCreateRequests: RecordedRequest[]
  localApplyRequests: RecordedRequest[]
  failNextLocalApply: () => void
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
  const localApplyRequests: RecordedRequest[] = []
  let failNextLocalApply = false
  const createdAt = "2026-10-29T00:00:00.000Z"
  const projectId = "project-desktop-e2e"
  const reviewId = "review-desktop-e2e"
  const findingId = "finding-desktop-e2e"
  const remediationId = "remediation-desktop-e2e"
  const executableDiff = "diff --git a/first.txt b/first.txt\n--- a/first.txt\n+++ b/first.txt\n@@ -1 +1 @@\n-before-one\n+after-one\ndiff --git a/second.txt b/second.txt\n--- a/second.txt\n+++ b/second.txt\n@@ -1 +1 @@\n-before-two\n+after-two\n"
  function hash(value: string) {
    return new Bun.CryptoHasher("sha256").update(value).digest("hex")
  }
  const review = {
    id: reviewId,
    project_id: projectId,
    source_revision: "a".repeat(64),
    source_snapshot: {
      source_kind: "local",
      source_identifier: "source-desktop-e2e",
      integrity_algorithm: "sha256-directory-manifest-v1",
      revision: "a".repeat(64),
      captured_at: createdAt,
    },
    status: "completed",
    started_at: createdAt,
    completed_at: createdAt,
    created_at: createdAt,
    updated_at: createdAt,
    agents: [],
  }
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
        return response(request, {
          id: projectId,
          name: "Desktop E2E project",
          source: "local",
          external_repository_id: null,
          external_repository_connection_id: null,
          repository_owner: null,
          repository_name: null,
          branch_name: null,
          repository_visibility: null,
          imported_at: createdAt,
          source_hash: null,
          current_revision: null,
          category: "productivity",
          auto_create_pull_requests: false,
          created_at: createdAt,
          updated_at: createdAt,
          archived_at: null,
        })
      }

      if (url.pathname === "/api/v1/agents" && request.method === "GET") {
        return response(request, {
          items: [{
            id: "agent-desktop-e2e",
            name: "Desktop reviewer",
            personality: null,
            review_category: "engineering",
            model_provider: "openai",
            model_name: "gpt-5",
            avatar: null,
            skills: [],
            credential_id: null,
            configuration_version: 1,
            created_at: createdAt,
            updated_at: createdAt,
            disabled_at: null,
          }],
          next_offset: null,
        })
      }

      if (url.pathname === "/api/v1/reviews" && request.method === "POST") {
        return response(request, review)
      }

      if (url.pathname === `/api/v1/reviews/${reviewId}` && request.method === "GET") {
        return response(request, review)
      }

      if (url.pathname === `/api/v1/findings/${findingId}` && request.method === "GET") {
        return response(request, {
          id: findingId,
          review_id: reviewId,
          agent_id: "agent-desktop-e2e",
          reviewing_agent: {
            assignment_id: "assignment-desktop-e2e",
            agent_id: "agent-desktop-e2e",
            display_name: "Desktop reviewer",
            specialization: "engineering",
          },
          category: "engineering",
          severity: "high",
          title: "Desktop remediation",
          explanation: "Apply a two-file local remediation.",
          evidence: null,
          source_location: null,
          recommendation: null,
          status: "accepted",
          created_at: createdAt,
          updated_at: createdAt,
        })
      }

      if (
        url.pathname === `/api/v1/findings/${findingId}/remediations` &&
        request.method === "GET"
      ) {
        return response(request, [{
          id: remediationId,
          project_id: projectId,
          finding_id: findingId,
          proposed_diff: "diff --git a/first.txt b/first.txt\n--- a/first.txt\n+++ b/first.txt\n@@ -1 +1 @@\n-before-one\n+after-one\ndiff --git a/second.txt b/second.txt\n--- a/second.txt\n+++ b/second.txt\n@@ -1 +1 @@\n-before-two\n+after-two\n",
          generation_status: "ready",
          generation_failure: null,
          patch_available: true,
          preview_is_redacted: true,
          pull_request: null,
          status: "proposed",
          approved_at: null,
          created_at: createdAt,
          updated_at: createdAt,
        }])
      }

      if (url.pathname === `/api/v1/remediations/${remediationId}/patch` && request.method === "GET") {
        return response(request, {
          diff: executableDiff,
          sha256: hash(executableDiff),
          source_snapshot: review.source_snapshot,
          files: ["one", "two"].map((name, index) => ({
            path: index === 0 ? "first.txt" : "second.txt",
            operation: "replace",
            original_sha256: hash(`before-${name}\n`),
            result_sha256: hash(`after-${name}\n`),
          })),
          warnings: [],
        })
      }

      if (
        url.pathname === `/api/v1/remediations/${remediationId}/apply-local` &&
        request.method === "POST"
      ) {
        localApplyRequests.push(recorded)
        if (failNextLocalApply) {
          failNextLocalApply = false
          return response(request, {
            error: {
              code: "request_failed",
              message: "The remediation could not be recorded.",
              request_id: "desktop-e2e-request-failure",
            },
          }, 503)
        }
        return response(request, {
          id: remediationId,
          project_id: projectId,
          finding_id: findingId,
          proposed_diff: "",
          pull_request: null,
          status: "applied",
          approved_at: createdAt,
          created_at: createdAt,
          updated_at: createdAt,
        })
      }

      return response(request, { error: { code: "not_found" } }, 404)
    },
  })

  return {
    baseUrl: `http://127.0.0.1:${server.port}`,
    requests,
    projectCreateRequests,
    localApplyRequests,
    failNextLocalApply: () => {
      failNextLocalApply = true
    },
    expireSession: () => {
      sessionExpired = true
    },
    close: () => server.stop(true),
  }
}
