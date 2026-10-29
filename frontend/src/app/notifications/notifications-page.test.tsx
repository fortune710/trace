// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { NotificationsPage } from "@/app/notifications/notifications-page"
import {
  useMarkAllNotificationsRead,
  useMarkNotificationRead,
  useNotifications,
} from "@/hooks/use-notifications"
import type { Notification } from "@/lib/api"

vi.mock("@/components/layout/app-shell", () => ({
  AppShell: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))
vi.mock("@/hooks/use-notifications", () => ({
  useMarkAllNotificationsRead: vi.fn(),
  useMarkNotificationRead: vi.fn(),
  useNotifications: vi.fn(),
}))

const notification: Notification = {
  id: "notification-1",
  category: "security",
  event_type: "password_signed_in",
  title: "Signed in",
  body: "<strong>This must remain text.</strong>",
  action_path: "/reviews/review-1",
  data: {},
  created_at: "2026-10-26T12:00:00.000Z",
  read_at: null,
}

const mockedUseNotifications = vi.mocked(useNotifications)
const mockedMarkRead = vi.mocked(useMarkNotificationRead)
const mockedMarkAllRead = vi.mocked(useMarkAllNotificationsRead)

function notificationQuery(overrides = {}) {
  return {
    notifications: [notification],
    unreadCount: 1,
    hasNextPage: true,
    isError: false,
    isFetching: false,
    isLoading: false,
    refetch: vi.fn(),
    ...overrides,
  } as unknown as ReturnType<typeof useNotifications>
}

function renderPage() {
  return render(
    <MemoryRouter>
      <NotificationsPage />
    </MemoryRouter>,
  )
}

describe("NotificationsPage", () => {
  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  beforeEach(() => {
    mockedUseNotifications.mockReturnValue(notificationQuery())
    mockedMarkRead.mockReturnValue({
      isPending: false,
      mutate: vi.fn(),
    } as unknown as ReturnType<typeof useMarkNotificationRead>)
    mockedMarkAllRead.mockReturnValue({
      isPending: false,
      mutate: vi.fn(),
    } as unknown as ReturnType<typeof useMarkAllNotificationsRead>)
  })

  it("renders unread category, accessible time, action, and body as text", () => {
    renderPage()

    expect(
      screen.getByRole("article", {
        name: "Unread Security notification: Signed in",
      }),
    ).toBeTruthy()
    expect(screen.getByText("Security")).toBeTruthy()
    expect(screen.getByText(notification.body)).toBeTruthy()
    expect(screen.queryByRole("strong")).toBeNull()
    expect(document.querySelector("time")?.getAttribute("dateTime")).toBe(
      notification.created_at,
    )
    expect(
      screen.getByRole("link", { name: "View" }).getAttribute("href"),
    ).toBe("/reviews/review-1")
  })

  it("shows loading, retry, and empty states without conflating them", () => {
    const refetch = vi.fn()
    mockedUseNotifications.mockReturnValue(
      notificationQuery({
        notifications: [],
        unreadCount: 0,
        isLoading: true,
      }),
    )
    const { rerender } = renderPage()
    expect(
      screen.getByLabelText("Loading notifications").getAttribute("aria-busy"),
    ).toBe("true")
    expect(screen.queryByText("No notifications yet.")).toBeNull()

    mockedUseNotifications.mockReturnValue(
      notificationQuery({
        notifications: [],
        unreadCount: 0,
        isError: true,
        refetch,
      }),
    )
    rerender(
      <MemoryRouter>
        <NotificationsPage />
      </MemoryRouter>,
    )
    fireEvent.click(screen.getByRole("button", { name: "Try again" }))
    expect(refetch).toHaveBeenCalledOnce()

    mockedUseNotifications.mockReturnValue(
      notificationQuery({ notifications: [], unreadCount: 0 }),
    )
    rerender(
      <MemoryRouter>
        <NotificationsPage />
      </MemoryRouter>,
    )
    expect(screen.getByText("No notifications yet.")).toBeTruthy()
  })

  it("marks one notification read, marks all read, and advances pagination", () => {
    const markRead = vi.fn()
    const markAllRead = vi.fn()
    mockedMarkRead.mockReturnValue({
      isPending: false,
      mutate: markRead,
    } as unknown as ReturnType<typeof useMarkNotificationRead>)
    mockedMarkAllRead.mockReturnValue({
      isPending: false,
      mutate: markAllRead,
    } as unknown as ReturnType<typeof useMarkAllNotificationsRead>)
    renderPage()

    fireEvent.click(screen.getByRole("button", { name: "Mark read" }))
    fireEvent.click(screen.getByRole("button", { name: "Mark all read" }))
    fireEvent.click(screen.getByRole("button", { name: "Next" }))

    expect(markRead).toHaveBeenCalledWith(notification.id)
    expect(markAllRead).toHaveBeenCalledOnce()
    expect(mockedUseNotifications).toHaveBeenLastCalledWith(2)
  })

  it("does not render an unsafe action path", () => {
    mockedUseNotifications.mockReturnValue(
      notificationQuery({
        notifications: [
          { ...notification, action_path: "https://untrusted.example" },
        ],
      }),
    )

    renderPage()

    expect(screen.queryByRole("link", { name: "View" })).toBeNull()
  })

  it("opens a pull-request notification action in a new tab", () => {
    mockedUseNotifications.mockReturnValue(
      notificationQuery({
        notifications: [
          {
            ...notification,
            event_type: "pull_request_created",
            action_path: "https://github.com/trace/example/pull/42",
          },
        ],
      }),
    )

    renderPage()

    const view = screen.getByRole("link", { name: "View" })
    expect(view.getAttribute("href")).toBe(
      "https://github.com/trace/example/pull/42",
    )
    expect(view.getAttribute("target")).toBe("_blank")
    expect(view.getAttribute("rel")).toBe("noopener noreferrer")
  })

  it("does not render View when no action path is provided", () => {
    mockedUseNotifications.mockReturnValue(
      notificationQuery({
        notifications: [{ ...notification, action_path: null }],
      }),
    )

    renderPage()

    expect(screen.queryByRole("link", { name: "View" })).toBeNull()
  })
})
