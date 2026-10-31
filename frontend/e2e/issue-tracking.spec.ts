import { expect, test, type Page, type Route } from "@playwright/test"

const apiBaseUrl = process.env.E2E_API_BASE_URL ?? "http://127.0.0.1:18000"
const csrfToken = "issue-tracking-csrf-token"
const teamId = "00000000-0000-0000-0000-000000000001"
const linearProjectId = "00000000-0000-0000-0000-000000000002"
const commitSha = "a".repeat(40)

const project = {
  id: "project-1",
  name: "Trace dashboard",
  source: "github",
  external_repository_id: "12345",
  external_repository_connection_id: "connection-1",
  repository_owner: "trace-labs",
  repository_name: "trace-dashboard",
  branch_name: "main",
  repository_visibility: "private",
  imported_at: "2026-10-14T12:00:00Z",
  source_hash: null,
  current_revision: commitSha,
  category: "business",
  auto_create_pull_requests: false,
  created_at: "2026-10-14T12:00:00Z",
  updated_at: "2026-10-14T12:00:00Z",
  archived_at: null,
}

const review = {
  id: "review-1",
  project_id: project.id,
  source_revision: commitSha,
  source_snapshot: {
    source_kind: "github",
    source_identifier: "12345",
    integrity_algorithm: "git-commit-sha1-v1",
    revision: commitSha,
    captured_at: "2026-10-21T00:00:00Z",
  },
  status: "completed",
  started_at: "2026-10-21T00:00:00Z",
  completed_at: "2026-10-21T00:01:00Z",
  created_at: "2026-10-21T00:00:00Z",
  updated_at: "2026-10-21T00:01:00Z",
  agents: [],
}

const finding = {
  id: "finding-1",
  review_id: review.id,
  agent_id: "agent-1",
  reviewing_agent: {
    assignment_id: "assignment-1",
    agent_id: "agent-1",
    display_name: "Security Scout",
    specialization: "security",
  },
  category: "security",
  severity: "high",
  title: "Missing authorization check",
  explanation: "The route does not validate organization ownership.",
  evidence: "The route accepts an object ID without checking its owner.",
  source_location: "backend/routes.py:42",
  recommendation: "Verify organization ownership before loading the object.",
  status: "open",
  created_at: "2026-10-21T00:00:30Z",
  updated_at: "2026-10-21T00:00:30Z",
}

const remediation = {
  id: "remediation-1",
  project_id: project.id,
  finding_id: finding.id,
  prompt_text: "Verify the ownership check and add the required authorization guard.",
  proposed_diff: "diff --git a/backend/routes.py b/backend/routes.py",
  generation_status: "ready",
  generation_failure: null,
  patch_available: true,
  preview_is_redacted: true,
  status: "proposed",
  created_at: "2026-10-21T00:00:30Z",
  updated_at: "2026-10-21T00:00:30Z",
}

const corsHeaders = {
  "access-control-allow-credentials": "true",
  "access-control-allow-origin": "http://127.0.0.1:5173",
}

async function fulfillJson(route: Route, json: unknown, status = 200) {
  await route.fulfill({
    contentType: "application/json",
    headers: corsHeaders,
    json,
    status,
  })
}

async function mockIssueTrackingApi(page: Page) {
  let issueTrackingDetails = {
    connected_projects: [
      {
        provider: "github",
        owner: "trace-labs",
        project: "trace-dashboard",
      },
    ],
  }
  let issueLinks: Array<Record<string, unknown>> = []
  let findingStatus = finding.status

  await page.route(`${apiBaseUrl}/**`, async (route) => {
    const request = route.request()
    const url = new URL(request.url())

    if (request.method() === "GET" && url.pathname === "/auth/session") {
      await fulfillJson(route, { user_id: "user-1", session_id: "session-1" })
      return
    }
    if (request.method() === "GET" && url.pathname === "/auth/csrf") {
      await fulfillJson(route, { csrf_token: csrfToken })
      return
    }
    if (
      request.method() === "GET" &&
      url.pathname === "/auth/oauth/github/connection"
    ) {
      await fulfillJson(route, { status: "connected" })
      return
    }
    if (
      request.method() === "POST" &&
      url.pathname === "/auth/oauth/linear/connect/start"
    ) {
      await fulfillJson(route, {
        authorization_url: "http://127.0.0.1:5173/oauth/linear-test",
      })
      return
    }
    if (request.method() === "GET" && url.pathname === "/api/v1/projects/project-1") {
      await fulfillJson(route, project)
      return
    }
    if (request.method() === "GET" && url.pathname === "/api/v1/projects/project-1/issue-tracking") {
      await fulfillJson(route, issueTrackingDetails)
      return
    }
    if (request.method() === "PATCH" && url.pathname === "/api/v1/projects/project-1/issue-tracking") {
      expect(request.headers()["x-csrf-token"]).toBe(csrfToken)
      expect(request.postDataJSON()).toEqual({
        connected_projects: [
          {
            provider: "linear",
            owner: teamId,
            project: linearProjectId,
          },
        ],
      })
      issueTrackingDetails = {
        connected_projects: [
          issueTrackingDetails.connected_projects[0],
          {
            provider: "linear",
            owner: teamId,
            project: linearProjectId,
          },
        ],
      }
      await fulfillJson(route, issueTrackingDetails)
      return
    }
    if (request.method() === "GET" && url.pathname === "/api/v1/issue-tracking/linear/teams") {
      await fulfillJson(route, [{ id: teamId, name: "Engineering", key: "ENG" }])
      return
    }
    if (
      request.method() === "GET" &&
      url.pathname === `/api/v1/issue-tracking/linear/teams/${teamId}/projects`
    ) {
      await fulfillJson(route, [{ id: linearProjectId, name: "Trace" }])
      return
    }
    if (request.method() === "GET" && url.pathname === "/api/v1/reviews") {
      await fulfillJson(route, { items: [], next_offset: null })
      return
    }
    if (request.method() === "GET" && url.pathname === "/api/v1/reviews/review-1") {
      await fulfillJson(route, review)
      return
    }
    if (request.method() === "GET" && url.pathname === "/api/v1/findings/finding-1") {
      await fulfillJson(route, { ...finding, status: findingStatus })
      return
    }
    if (request.method() === "PATCH" && url.pathname === "/api/v1/findings/finding-1") {
      expect(request.headers()["x-csrf-token"]).toBe(csrfToken)
      expect(request.postDataJSON()).toEqual({ status: "accepted" })
      findingStatus = "accepted"
      await fulfillJson(route, { ...finding, status: findingStatus })
      return
    }
    if (request.method() === "GET" && url.pathname === "/api/v1/findings/finding-1/remediations") {
      await fulfillJson(route, [remediation])
      return
    }
    if (request.method() === "GET" && url.pathname === "/api/v1/findings/finding-1/issue-links") {
      await fulfillJson(route, issueLinks)
      return
    }
    if (
      request.method() === "POST" &&
      url.pathname === "/api/v1/findings/finding-1/issue-links/preview"
    ) {
      expect(request.postDataJSON()).toEqual({ provider: "linear" })
      await fulfillJson(route, {
        title: "Missing authorization check",
        body_markdown: "## Finding\n\nVerify organization ownership.",
      })
      return
    }
    if (
      request.method() === "POST" &&
      url.pathname === "/api/v1/remediations/remediation-1/issue"
    ) {
      expect(request.headers()["x-csrf-token"]).toBe(csrfToken)
      expect(request.postDataJSON()).toEqual({ destination: { provider: "linear" } })
      const link = {
        id: "issue-link-1",
        finding_id: finding.id,
        provider: "linear",
        destination_id: `${teamId}/${linearProjectId}`,
        external_identifier: "ENG-21",
        external_url: "https://linear.app/trace/issue/ENG-21",
        state: "created",
        failure_code: null,
        created_at: "2026-10-28T00:00:00Z",
        updated_at: "2026-10-28T00:00:00Z",
      }
      issueLinks = [link]
      await fulfillJson(route, link, 201)
      return
    }

    await fulfillJson(route, { error: { code: "not_found" } }, 404)
  })
}

test("starts a Linear OAuth connection", async ({ page }) => {
  await mockIssueTrackingApi(page)
  await page.goto("/settings/integrations")

  await page.getByRole("button", { name: "Connect Linear" }).click()

  await expect(page).toHaveURL("http://127.0.0.1:5173/oauth/linear-test")
})

test("configures a Linear destination while preserving the GitHub source", async ({ page }) => {
  await mockIssueTrackingApi(page)
  await page.goto("/projects/project-1")

  await page.getByRole("tab", { name: "Issues" }).click()

  await expect(page.getByRole("heading", { name: "GitHub Issues" })).toBeVisible()
  await expect(page.getByText("Repository")).toBeVisible()
  await expect(
    page
      .getByRole("tabpanel", { name: "Issues" })
      .getByText("trace-labs/trace-dashboard", { exact: true }),
  ).toBeVisible()
  await page.getByRole("combobox", { name: "Team" }).click()
  await page.getByText("Engineering (ENG)", { exact: true }).click()
  await page.getByRole("combobox", { name: "Project" }).click()
  await page.getByText("Trace", { exact: true }).click()
  await page.getByRole("button", { name: "Save Linear destination" }).click()

  await expect(page.getByRole("combobox", { name: "Team" })).toContainText("Engineering")
  await expect(page.getByRole("combobox", { name: "Project" })).toContainText("Trace")
  await expect(page.getByText("Project", { exact: true })).toBeVisible()
})

test("creates a Linear issue from a finding and renders the linked issue", async ({ page }) => {
  await mockIssueTrackingApi(page)
  await page.goto("/reviews/review-1/findings/finding-1")

  await page.getByRole("button", { name: "Accept" }).click()
  const issueTracker = page.getByLabel("Choose issue tracker")
  await expect(issueTracker).toBeEnabled()
  await issueTracker.click()
  await page.getByRole("option", { name: "Linear issue" }).click()
  await expect(page.getByRole("dialog", { name: "Create Linear issue" })).toBeVisible()
  await expect(page.getByText("Verify organization ownership.")).toBeVisible()
  await page.getByRole("button", { name: "Create issue" }).click()

  await expect(page.getByText("Issue created")).toBeVisible()
  await expect(page.getByRole("heading", { name: "Linked issues" })).toBeVisible()
  await expect(page.getByRole("link", { name: "ENG-21" })).toHaveAttribute(
    "href",
    "https://linear.app/trace/issue/ENG-21",
  )
})
