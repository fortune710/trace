import { expect, test, type Page, type Route } from "@playwright/test"

const apiBaseUrl = process.env.E2E_API_BASE_URL ?? "http://127.0.0.1:18000"

const firstNotification = {
  id: "notification-1",
  category: "security",
  event_type: "password_signed_in",
  title: "Signed in",
  body: "You signed in with your password.",
  action_path: "/reviews/review-1",
  data: {},
  created_at: "2026-10-26T12:00:00.000Z",
  read_at: null,
}

const secondNotification = {
  ...firstNotification,
  id: "notification-2",
  title: "Review completed",
  category: "info",
  event_type: "review_completed",
  action_path: null,
  read_at: "2026-10-26T12:05:00.000Z",
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

async function mockNotificationsApi(page: Page) {
  let firstNotificationRead = false

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
      url.pathname === "/api/v1/notifications"
    ) {
      const firstPage = url.searchParams.get("page") === "1"
      await fulfillJson(route, {
        items: firstPage
          ? [
              {
                ...firstNotification,
                read_at: firstNotificationRead
                  ? "2026-10-26T12:10:00.000Z"
                  : null,
              },
            ]
          : [secondNotification],
        next_offset: firstPage ? 20 : null,
        unread_count: firstPage && !firstNotificationRead ? 1 : 0,
      })
      return
    }
    if (
      request.method() === "PATCH" &&
      url.pathname === "/api/v1/notifications/notification-1/read"
    ) {
      expect(request.headers()["x-csrf-token"]).toBe("csrf-token")
      firstNotificationRead = true
      await fulfillJson(route, {
        item: { ...firstNotification, read_at: "2026-10-26T12:10:00.000Z" },
        changed: true,
      })
      return
    }
    if (
      request.method() === "GET" &&
      url.pathname === "/api/v1/reviews/review-1"
    ) {
      await fulfillJson(route, { error: { code: "not_found" } }, 404)
      return
    }

    await fulfillJson(route, { error: { code: "not_found" } }, 404)
  })
}

test("shows durable notifications, marks an item read, and loads more on scroll", async ({
  page,
}) => {
  await mockNotificationsApi(page)
  await page.goto("/notifications")

  await expect(
    page.getByRole("article", {
      name: "Unread Security notification: Signed in",
    }),
  ).toBeVisible()
  await expect(
    page
      .getByRole("article", {
        name: "Unread Security notification: Signed in",
      })
      .getByRole("link", { name: "View" }),
  ).toHaveAttribute(
    "href",
    "/reviews/review-1",
  )

  await page.getByRole("button", { name: "Mark read" }).click()
  await expect(page.getByText("You are all caught up.")).toBeVisible()

  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight))
  await expect(
    page.getByRole("article", {
      name: "Read Info notification: Review completed",
    }),
  ).toBeVisible()
})
