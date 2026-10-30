// @vitest-environment jsdom

import {
  type InfiniteData,
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query"
import {
  act,
  cleanup,
  render,
  renderHook,
  waitFor,
} from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import {
  NotificationStream,
  notificationsQueryKey,
  useMarkAllNotificationsRead,
  useMarkNotificationRead,
  useNotifications,
} from "@/hooks/use-notifications"
import { toast } from "@/components/ui/toast"
import type { NotificationPage } from "@/lib/api"

const apiMocks = vi.hoisted(() => ({
  list: vi.fn(),
  markAllRead: vi.fn(),
  markRead: vi.fn(),
  streamUrl: vi.fn(() => "http://api.example.test/api/v1/notifications/stream"),
}))

vi.mock("@/hooks/use-session", () => ({
  useSession: () => ({ data: { user_id: "user-1" } }),
}))
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>()
  return {
    ...actual,
    notificationsApi: {
      ...actual.notificationsApi,
      ...apiMocks,
    },
  }
})
vi.mock("@/components/ui/toast", () => ({
  toast: { add: vi.fn() },
}))

const page: NotificationPage = {
  items: [
    {
      id: "notification-1",
      category: "info",
      event_type: "review_queued",
      title: "Review queued",
      body: "Your review has been queued.",
      action_path: "/reviews/review-1",
      data: {},
      created_at: "2026-10-26T12:00:00.000Z",
      read_at: null,
    },
  ],
  next_offset: null,
  unread_count: 1,
}

const notificationPages: InfiniteData<NotificationPage> = {
  pages: [page],
  pageParams: [1],
}

function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      mutations: { retry: false },
      queries: { retry: false },
    },
  })
}

class FakeEventSource {
  static instances: FakeEventSource[] = []

  onopen: (() => void) | null = null
  close = vi.fn()
  readonly url: string
  readonly options: EventSourceInit
  private listeners = new Map<string, EventListener>()

  constructor(url: string, options: EventSourceInit) {
    this.url = url
    this.options = options
    FakeEventSource.instances.push(this)
  }

  addEventListener(type: string, listener: EventListener) {
    this.listeners.set(type, listener)
  }

  emitNotification(data: object) {
    this.listeners.get("notification")?.(
      new MessageEvent("notification", { data: JSON.stringify(data) }),
    )
  }
}

describe("notification hooks", () => {
  afterEach(() => {
    cleanup()
    vi.useRealTimers()
    vi.clearAllMocks()
    localStorage.clear()
    FakeEventSource.instances = []
  })

  beforeEach(() => {
    vi.stubGlobal("EventSource", FakeEventSource)
    vi.stubGlobal("BroadcastChannel", undefined)
    vi.stubGlobal("crypto", { randomUUID: () => "tab-1" })
  })

  it("optimistically marks one notification read and restores it after failure", async () => {
    const queryClient = createQueryClient()
    queryClient.setQueryData([...notificationsQueryKey, 20], notificationPages)
    let rejectMutation: (error: Error) => void = () => undefined
    apiMocks.markRead.mockReturnValueOnce(
      new Promise((_, reject) => {
        rejectMutation = reject
      }),
    )
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    )
    const { result } = renderHook(() => useMarkNotificationRead(), { wrapper })

    act(() => result.current.mutate("notification-1"))
    await waitFor(() => {
      expect(
        queryClient.getQueryData<InfiniteData<NotificationPage>>([
          ...notificationsQueryKey,
          20,
        ])?.pages[0]?.unread_count,
      ).toBe(0)
    })
    act(() => rejectMutation(new Error("network unavailable")))
    await waitFor(() => expect(result.current.isError).toBe(true))

    expect(
      queryClient.getQueryData<InfiniteData<NotificationPage>>([
        ...notificationsQueryKey,
        20,
      ]),
    ).toEqual(notificationPages)
  })

  it("fetches another notification page on demand", async () => {
    const queryClient = createQueryClient()
    apiMocks.list
      .mockResolvedValueOnce({
        ...page,
        next_offset: 20,
      })
      .mockResolvedValueOnce({
        ...page,
        items: [{ ...page.items[0], id: "notification-2" }],
      })
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    )
    const { result } = renderHook(() => useNotifications(), { wrapper })

    await waitFor(() => expect(result.current.notifications).toHaveLength(1))
    await act(async () => {
      await result.current.fetchNextPage()
    })

    await waitFor(() => expect(result.current.notifications).toHaveLength(2))

    expect(apiMocks.list).toHaveBeenNthCalledWith(1, {
      page: 1,
      pageSize: 20,
    })
    expect(apiMocks.list).toHaveBeenNthCalledWith(2, {
      page: 2,
      pageSize: 20,
    })
  })

  it("optimistically marks all notifications read and restores them after failure", async () => {
    const queryClient = createQueryClient()
    queryClient.setQueryData([...notificationsQueryKey, 20], notificationPages)
    let rejectMutation: (error: Error) => void = () => undefined
    apiMocks.markAllRead.mockReturnValueOnce(
      new Promise((_, reject) => {
        rejectMutation = reject
      }),
    )
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    )
    const { result } = renderHook(() => useMarkAllNotificationsRead(), {
      wrapper,
    })

    act(() => result.current.mutate())
    await waitFor(() => {
      expect(
        queryClient.getQueryData<InfiniteData<NotificationPage>>([
          ...notificationsQueryKey,
          20,
        ])?.pages[0]?.unread_count,
      ).toBe(0)
    })
    act(() => rejectMutation(new Error("network unavailable")))
    await waitFor(() => expect(result.current.isError).toBe(true))

    expect(
      queryClient.getQueryData<InfiniteData<NotificationPage>>([
        ...notificationsQueryKey,
        20,
      ]),
    ).toEqual(notificationPages)
  })

  it("creates one leader stream, refreshes on reconnect, deduplicates events, and cleans up", async () => {
    const queryClient = createQueryClient()
    const invalidateQueries = vi.spyOn(queryClient, "invalidateQueries")
    const { unmount } = render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <NotificationStream />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1))
    const stream = FakeEventSource.instances[0]
    act(() => stream.onopen?.())
    act(() => {
      stream.emitNotification({
        ...page.items[0],
        id: "live-notification",
      })
      stream.emitNotification({
        ...page.items[0],
        id: "live-notification",
      })
    })

    expect(invalidateQueries).toHaveBeenCalled()
    expect(toast.add).toHaveBeenCalledTimes(1)
    expect(toast.add).toHaveBeenCalledWith(
      expect.objectContaining({
        title: "Review queued",
        actionProps: expect.objectContaining({ children: "View" }),
      }),
    )
    unmount()
    expect(stream.close).toHaveBeenCalledOnce()
  })

  it("does not attach an unsafe toast navigation action", async () => {
    const queryClient = createQueryClient()
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <NotificationStream />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1))
    act(() => {
      FakeEventSource.instances[0].emitNotification({
        ...page.items[0],
        action_path: "https://untrusted.example",
      })
    })

    expect(toast.add).toHaveBeenCalledWith(
      expect.not.objectContaining({ actionProps: expect.anything() }),
    )
  })

  it("opens a pull-request toast action in a new tab", async () => {
    const open = vi.spyOn(window, "open").mockImplementation(() => null)
    const queryClient = createQueryClient()
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <NotificationStream />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1))
    act(() => {
      FakeEventSource.instances[0].emitNotification({
        ...page.items[0],
        event_type: "pull_request_created",
        action_path: "https://github.com/trace/example/pull/42",
      })
    })

    const toastAction = vi.mocked(toast.add).mock.calls[0][0].actionProps
    const onClick = toastAction?.onClick as (() => void) | undefined
    onClick?.()

    expect(open).toHaveBeenCalledWith(
      "https://github.com/trace/example/pull/42",
      "_blank",
      "noopener,noreferrer",
    )
  })
})
