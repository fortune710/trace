import { expect, test, type Page, type Route } from "@playwright/test"

const apiBaseUrl = "http://127.0.0.1:18000"
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

const corsHeaders = {
  "access-control-allow-credentials": "true",
  "access-control-allow-origin": "http://127.0.0.1:5173",
}

async function fulfillJson(route: Route, json: unknown, status = 200) {
  await route.fulfill({ contentType: "application/json", headers: corsHeaders, json, status })
}

async function mockProjectApi(page: Page, options: { failFirstCreate?: boolean; githubStatus?: "connected" | "needs_reconnection" } = {}) {
  let createAttempts = 0

  await page.route(`${apiBaseUrl}/**`, async (route) => {
    const request = route.request()
    const url = new URL(request.url())

    if (request.method() === "GET" && url.pathname === "/auth/session") {
      await fulfillJson(route, { user_id: "user-1", session_id: "session-1" })
      return
    }
    if (request.method() === "GET" && url.pathname === "/auth/oauth/github/connection") {
      await fulfillJson(route, { provider: "github", status: options.githubStatus ?? "connected" })
      return
    }
    if (request.method() === "GET" && url.pathname === "/api/v1/projects") {
      await fulfillJson(route, { items: [], next_offset: null })
      return
    }
    if (request.method() === "GET" && url.pathname === "/api/v1/projects/project-1") {
      await fulfillJson(route, project)
      return
    }
    if (request.method() === "GET" && url.pathname === "/api/v1/repositories") {
      await fulfillJson(route, {
        items: [{
          source: "github",
          repository_id: "12345",
          owner_login: "trace-labs",
          name: "trace-dashboard",
          full_name: "trace-labs/trace-dashboard",
          visibility: "private",
          private: true,
          default_branch: "main",
          web_url: "https://github.com/trace-labs/trace-dashboard",
        }],
        next_page: null,
      })
      return
    }
    if (request.method() === "GET" && url.pathname === "/api/v1/repositories/12345/branches") {
      await fulfillJson(route, {
        items: [{ source: "github", repository_id: "12345", name: "main", commit_sha: commitSha, protected: false }],
        next_page: null,
      })
      return
    }
    if (request.method() === "POST" && url.pathname === "/api/v1/projects") {
      createAttempts += 1
      if (options.failFirstCreate && createAttempts === 1) {
        await fulfillJson(route, { error: { code: "provider_unavailable" } }, 503)
        return
      }
      await fulfillJson(route, { ...project, name: (request.postDataJSON() as { name: string }).name }, 201)
      return
    }

    await fulfillJson(route, { error: { code: "not_found" } }, 404)
  })
}

async function chooseRepositoryAndBranch(page: Page) {
  await page.getByRole("button", { name: /GitHub repository/ }).click()
  await page.getByLabel("Repository").click()
  await page.getByText("trace-labs/trace-dashboard", { exact: true }).click()
  await page.getByLabel("Branch").click()
  await page.getByText("main", { exact: true }).click()
}

test("project import shows the selected SHA and opens the imported project", async ({ page }) => {
  await mockProjectApi(page)
  await page.goto("/projects")
  await page.getByRole("button", { name: "Create project" }).last().click()

  await chooseRepositoryAndBranch(page)
  await page.getByRole("button", { name: "Continue" }).click()
  await expect(page.getByText(commitSha, { exact: true })).toBeVisible()

  await page.getByLabel("Project name").fill("Imported dashboard")
  await page.getByRole("button", { name: "Create project" }).first().click()

  await expect(page).toHaveURL(/\/projects\/project-1$/)
  await expect(page.getByRole("heading", { name: "Trace dashboard" })).toBeVisible()
  await expect(page.getByText(commitSha, { exact: true })).toBeVisible()
})

test("project import requires a repository and branch before continuing", async ({ page }) => {
  await mockProjectApi(page)
  await page.goto("/projects")
  await page.getByRole("button", { name: "Create project" }).first().click()
  await page.getByRole("button", { name: /GitHub repository/ }).click()

  await expect(page.getByRole("button", { name: "Continue" })).toBeDisabled()
})

test("project import preserves the form after a transient creation failure", async ({ page }) => {
  await mockProjectApi(page, { failFirstCreate: true })
  await page.goto("/projects")
  await page.getByRole("button", { name: "Create project" }).first().click()

  await chooseRepositoryAndBranch(page)
  await page.getByRole("button", { name: "Continue" }).click()
  await page.getByLabel("Project name").fill("Retry dashboard")
  await page.getByRole("button", { name: "Create project" }).last().click()

  await expect(page.getByText("Project could not be created")).toBeVisible()
  await expect(page.getByLabel("Project name")).toHaveValue("Retry dashboard")
  await page.getByRole("button", { name: "Create project" }).last().click()
  await expect(page).toHaveURL(/\/projects\/project-1$/)
})

test("reconnection-required GitHub status provides a clear path to reconnect", async ({ page }) => {
  await mockProjectApi(page, { githubStatus: "needs_reconnection" })
  await page.goto("/integrations")

  await expect(page.getByText("Reconnect required")).toBeVisible()
  await expect(page.getByRole("button", { name: "Reconnect" })).toBeEnabled()
})
