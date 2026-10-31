import { expect, test, type Page, type Route } from "@playwright/test"

const apiBaseUrl = process.env.E2E_API_BASE_URL ?? "http://127.0.0.1:18000"
const commitSha = "a".repeat(40)

const review = {
  id: "review-1",
  project_id: "project-1",
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
  agents: [
    {
      assignment_id: "assignment-1",
      agent_id: "agent-1",
      name: "Security Scout",
      review_category: "security",
      model_provider: "openai",
      model_name: "gpt-5.1",
      personality: null,
      skills: [],
      configuration_version: 1,
      status: "completed",
      assigned_at: "2026-10-21T00:00:00Z",
      started_at: "2026-10-21T00:00:00Z",
      completed_at: "2026-10-21T00:01:00Z",
    },
  ],
}

const finding = {
  id: "finding-1",
  review_id: "review-1",
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
  project_id: "project-1",
  finding_id: finding.id,
  proposed_diff: "diff --git a/backend/routes.py b/backend/routes.py",
  generation_status: "ready",
  generation_failure: null,
  patch_available: true,
  preview_is_redacted: true,
  status: "proposed",
  approved_at: null,
  created_at: "2026-10-21T00:00:30Z",
  updated_at: "2026-10-21T00:00:30Z",
}

const codingPrompt = `# Trace coding remediation prompt

## Step 1 — Verify before changing anything

Verify that the reported issue still exists.

## Step 2 — Model-proposed implementation prompt

Fix the ownership check without changing unrelated files.

## Immutable review revision

${commitSha}`

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

async function mockFindingsApi(page: Page, promptStatus = 200, failedPatch = false) {
  await page.route(`${apiBaseUrl}/**`, async (route) => {
    const request = route.request()
    const url = new URL(request.url())

    if (request.method() === "GET" && url.pathname === "/auth/session") {
      await fulfillJson(route, { user_id: "user-1", session_id: "session-1" })
      return
    }
    if (request.method() === "GET" && url.pathname === "/auth/csrf") {
      await fulfillJson(route, { csrf_token: "csrf-token" })
      return
    }
    if (
      request.method() === "GET" &&
      url.pathname === "/api/v1/reviews/review-1"
    ) {
      await fulfillJson(route, { ...review, warnings: failedPatch ? ["remediation_generation_incomplete"] : [], remediation_generation_failed_count: failedPatch ? 1 : 0 })
      return
    }
    if (
      request.method() === "GET" &&
      url.pathname === "/api/v1/reviews/review-1/findings"
    ) {
      expect(url.searchParams.get("page")).toBe("1")
      expect(url.searchParams.get("page_size")).toBe("25")
      await fulfillJson(route, { items: [finding], next_offset: null })
      return
    }
    if (
      request.method() === "GET" &&
      url.pathname === "/api/v1/findings/finding-1"
    ) {
      await fulfillJson(route, finding)
      return
    }
    if (
      request.method() === "GET" &&
      url.pathname === "/api/v1/findings/finding-1/remediations"
    ) {
      await fulfillJson(route, [{ ...remediation, ...(failedPatch ? { generation_status: "failed", proposed_diff: "", patch_available: false, generation_failure: { code: "invalid_line_range", message: "Invalid line range" } } : {}) }])
      return
    }
    if (
      request.method() === "GET" &&
      url.pathname === "/api/v1/remediations/remediation-1/prompt"
    ) {
      expect(request.headers()["x-csrf-token"]).toBe("csrf-token")
      if (promptStatus === 200) {
        await fulfillJson(route, { prompt_text: codingPrompt })
      } else {
        await fulfillJson(
          route,
          { error: { code: "authorization_denied" } },
          promptStatus,
        )
      }
      return
    }

    await fulfillJson(route, { error: { code: "not_found" } }, 404)
  })
}

test("renders a review finding, preserves the filter URL, and opens its detail", async ({
  page,
}) => {
  await mockFindingsApi(page)
  await page.goto("/reviews/review-1?tab=findings&finding_severity=high")

  await expect(page.getByRole("heading", { name: "Missing authorization check" })).toBeVisible()
  await expect(
    page.getByRole("article").getByText("Security Scout", { exact: true }),
  ).toBeVisible()
  await expect(page.getByLabel("Severity")).toContainText("high")

  await page.getByRole("button", { name: "Clear filters" }).click()
  await expect(page).toHaveURL(/\/reviews\/review-1\?tab=findings$/)

  await page.getByRole("link", { name: "View finding" }).click()
  await expect(page).toHaveURL(/\/reviews\/review-1\/findings\/finding-1$/)
  await expect(page.getByText(finding.evidence)).toBeVisible()
  await expect(page.getByText(finding.recommendation)).toBeVisible()
})

test("an owner can copy a rendered coding prompt from finding details", async ({
  page,
  context,
}) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"], {
    origin: "http://127.0.0.1:5173",
  })
  await mockFindingsApi(page)

  await page.goto("/reviews/review-1/findings/finding-1")
  await expect(page.getByRole("heading", { name: "Coding-agent prompt" })).toBeVisible()
  await expect(page.getByText(codingPrompt)).toBeVisible()

  const copyButton = page.getByRole("button", { name: "Copy prompt" })
  await copyButton.focus()
  await page.keyboard.press("Space")

  await expect(page.getByText("Prompt copied")).toBeVisible()
  await expect
    .poll(() => page.evaluate(() => navigator.clipboard.readText()))
    .toBe(codingPrompt)
})

test("a forbidden remediation prompt is never rendered", async ({ page }) => {
  await mockFindingsApi(page, 403)

  await page.goto("/reviews/review-1/findings/finding-1")

  await expect(
    page.getByText("We could not load the coding-agent prompt."),
  ).toBeVisible()
  await expect(page.getByText(codingPrompt)).toHaveCount(0)
})

test("a completed review preserves findings and explains unavailable changes", async ({ page }) => {
  await mockFindingsApi(page, 200, true)
  await page.goto("/reviews/review-1")
  await expect(page.getByText(/Findings are saved. Automated changes are unavailable/)).toBeVisible()
  await page.goto("/reviews/review-1/findings/finding-1")
  await expect(page.getByRole("heading", { name: "Missing authorization check" })).toBeVisible()
  await expect(page.getByText(/The finding is saved. Automated changes are unavailable: Invalid line range/)).toBeVisible()
  await expect(page.getByRole("button", { name: /create pull request/i })).toBeDisabled()
})
