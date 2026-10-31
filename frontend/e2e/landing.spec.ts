import { expect, test, type Page, type Route } from "@playwright/test"

const apiBaseUrl = process.env.E2E_API_BASE_URL ?? "http://127.0.0.1:18000"

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

async function mockSession(page: Page, signedIn: boolean) {
  await page.route(`${apiBaseUrl}/**`, async (route) => {
    const url = new URL(route.request().url())

    if (signedIn && url.pathname === "/auth/session") {
      await fulfillJson(route, { user_id: "user-1", session_id: "session-1" })
      return
    }

    await fulfillJson(route, { detail: "Not authenticated" }, 401)
  })
}

test.describe("landing page", () => {
  test("introduces Trace to signed-out visitors", async ({ page }) => {
    await mockSession(page, false)
    await page.goto("/")

    await expect(
      page.getByRole("heading", {
        level: 1,
        name: "Review your app before the world does.",
      }),
    ).toBeVisible()
    await expect(
      page.getByRole("banner").getByRole("link", { name: "Sign in" }),
    ).toBeVisible()

    const hero = page.getByRole("region", {
      name: "Review your app before the world does.",
    })
    const download = hero.getByRole("link", { name: "Download for macOS" })

    await expect(download).toBeVisible()
    await expect(download).toHaveAttribute("href", /^https:\/\//)
  })

  test("Continue on web opens sign in", async ({ page }) => {
    await mockSession(page, false)
    await page.goto("/")

    await page
      .getByRole("region", { name: "Review your app before the world does." })
      .getByRole("link", { name: "Continue on web" })
      .click()

    await expect(page).toHaveURL(/\/sign-in$/)
    await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible()
  })

  test("signed-in visitors can open the app from the landing page", async ({
    page,
  }) => {
    await mockSession(page, true)
    await page.goto("/")

    const openApp = page
      .getByRole("banner")
      .getByRole("link", { name: "Open app" })

    await expect(openApp).toBeVisible()
    await expect(openApp).toHaveAttribute("href", "/account")
  })

  test("the FAQ opens and the page fits a phone", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 })
    await mockSession(page, false)
    await page.goto("/")

    const question = page.getByText("Will Trace change my code on its own?")

    await question.scrollIntoViewIfNeeded()
    await question.click()
    await expect(page.getByText(/shows you the diff/)).toBeVisible()

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    )

    expect(overflow).toBeLessThanOrEqual(0)
  })
})
