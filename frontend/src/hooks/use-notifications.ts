import {
  type InfiniteData,
  useInfiniteQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query"
import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"

import {
  notificationsApi,
  type Notification,
  type NotificationPage,
} from "@/lib/api"
import { toast } from "@/components/ui/toast"
import { useSession } from "@/hooks/use-session"

export const notificationsQueryKey = ["notifications"] as const
const PAGE_SIZE = 20

type NotificationCacheSnapshot = Array<
  [readonly unknown[], InfiniteData<NotificationPage> | undefined]
>

function unreadNotifications(
  data: InfiniteData<NotificationPage>,
  notificationId: string,
  readAt: string,
): InfiniteData<NotificationPage> {
  const wasUnread = data.pages.some((page) =>
    page.items.some(
    (notification) =>
      notification.id === notificationId && notification.read_at === null,
    ),
  )
  const unreadCount = data.pages[0]?.unread_count ?? 0

  return {
    ...data,
    pages: data.pages.map((page) => ({
      ...page,
      items: page.items.map((notification) =>
        notification.id === notificationId && notification.read_at === null
          ? { ...notification, read_at: readAt }
          : notification,
      ),
      unread_count: wasUnread
        ? Math.max(0, unreadCount - 1)
        : page.unread_count,
    })),
  }
}

function allReadNotifications(
  data: InfiniteData<NotificationPage>,
  readAt: string,
): InfiniteData<NotificationPage> {
  return {
    ...data,
    pages: data.pages.map((page) => ({
      ...page,
      items: page.items.map((notification) =>
        notification.read_at === null
          ? { ...notification, read_at: readAt }
          : notification,
      ),
      unread_count: 0,
    })),
  }
}

function restoreNotificationCache(
  queryClient: ReturnType<typeof useQueryClient>,
  snapshot: NotificationCacheSnapshot | undefined,
) {
  snapshot?.forEach(([key, value]) => {
    queryClient.setQueryData<InfiniteData<NotificationPage>>(key, value)
  })
}

export function useNotifications() {
  const query = useInfiniteQuery({
    queryKey: [...notificationsQueryKey, PAGE_SIZE],
    initialPageParam: 1,
    queryFn: ({ pageParam }) =>
      notificationsApi.list({ page: pageParam, pageSize: PAGE_SIZE }),
    getNextPageParam: (lastPage) =>
      lastPage.next_offset === null
        ? undefined
        : Math.floor(lastPage.next_offset / PAGE_SIZE) + 1,
    retry: false,
  })

  return {
    ...query,
    notifications: query.data?.pages.flatMap((page) => page.items) ?? [],
    unreadCount: query.data?.pages[0]?.unread_count ?? 0,
  }
}

export function useMarkNotificationRead() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: notificationsApi.markRead,
    onMutate: async (notificationId) => {
      await queryClient.cancelQueries({ queryKey: notificationsQueryKey })
      const previous = queryClient.getQueriesData<InfiniteData<NotificationPage>>({
        queryKey: notificationsQueryKey,
      }) as NotificationCacheSnapshot
      const readAt = new Date().toISOString()

      queryClient.setQueriesData<InfiniteData<NotificationPage>>(
        { queryKey: notificationsQueryKey },
        (data) =>
          data ? unreadNotifications(data, notificationId, readAt) : data,
      )

      return { previous }
    },
    onError: (_error, _notificationId, context) => {
      restoreNotificationCache(queryClient, context?.previous)
    },
    onSettled: () =>
      queryClient.invalidateQueries({ queryKey: notificationsQueryKey }),
  })
}

export function useMarkAllNotificationsRead() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: notificationsApi.markAllRead,
    onMutate: async () => {
      await queryClient.cancelQueries({ queryKey: notificationsQueryKey })
      const previous = queryClient.getQueriesData<InfiniteData<NotificationPage>>({
        queryKey: notificationsQueryKey,
      }) as NotificationCacheSnapshot
      const readAt = new Date().toISOString()

      queryClient.setQueriesData<InfiniteData<NotificationPage>>(
        { queryKey: notificationsQueryKey },
        (data) => (data ? allReadNotifications(data, readAt) : data),
      )

      return { previous }
    },
    onError: (_error, _variables, context) => {
      restoreNotificationCache(queryClient, context?.previous)
    },
    onSettled: () =>
      queryClient.invalidateQueries({ queryKey: notificationsQueryKey }),
  })
}

function isSafeActionPath(actionPath: string | null): actionPath is string {
  return Boolean(actionPath && /^\/[^/]/.test(actionPath))
}

function isSafePullRequestUrl(notification: Notification): boolean {
  if (
    notification.event_type !== "pull_request_created" ||
    !notification.action_path
  ) {
    return false
  }
  try {
    const url = new URL(notification.action_path)
    return url.protocol === "https:" && Boolean(url.hostname)
  } catch {
    return false
  }
}

export function NotificationStream() {
  const session = useSession()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [isLeader, setIsLeader] = useState(false)

  useEffect(() => {
    if (!session.data) {
      return
    }
    const tabId = crypto.randomUUID()
    const leaderKey = "trace.notifications.stream.leader"
    const claimLeadership = () => {
      const now = Date.now()
      try {
        const current = JSON.parse(
          localStorage.getItem(leaderKey) ?? "null",
        ) as { id?: string; expiresAt?: number } | null
        if (
          !current ||
          !current.expiresAt ||
          current.expiresAt < now ||
          current.id === tabId
        ) {
          localStorage.setItem(
            leaderKey,
            JSON.stringify({ id: tabId, expiresAt: now + 10_000 }),
          )
          setIsLeader(true)
          return
        }
        setIsLeader(false)
      } catch {
        setIsLeader(true)
      }
    }
    claimLeadership()
    const heartbeat = window.setInterval(claimLeadership, 4_000)
    const onStorage = (event: StorageEvent) => {
      if (event.key === leaderKey) claimLeadership()
    }
    window.addEventListener("storage", onStorage)
    return () => {
      window.clearInterval(heartbeat)
      window.removeEventListener("storage", onStorage)
      try {
        const current = JSON.parse(
          localStorage.getItem(leaderKey) ?? "null",
        ) as { id?: string } | null
        if (current?.id === tabId) {
          localStorage.removeItem(leaderKey)
        }
      } catch {
        // Storage can be unavailable in privacy-restricted contexts.
      }
    }
  }, [session.data])

  useEffect(() => {
    if (!session.data || !isLeader || typeof EventSource === "undefined") {
      return
    }

    const channel =
      typeof BroadcastChannel === "undefined"
        ? null
        : new BroadcastChannel("trace.notifications")
    const stream = new EventSource(notificationsApi.streamUrl(), {
      withCredentials: true,
    })
    const seen = new Set<string>()
    const refreshNotifications = () =>
      void queryClient.invalidateQueries({ queryKey: notificationsQueryKey })
    const handleNotification = (event: MessageEvent<string>) => {
      let notification: Notification
      try {
        notification = JSON.parse(event.data) as Notification
      } catch {
        return
      }
      refreshNotifications()
      channel?.postMessage({ type: "notification" })
      if (seen.has(notification.id)) return
      seen.add(notification.id)
      const actionPath = isSafeActionPath(notification.action_path)
        ? notification.action_path
        : null
      const pullRequestUrl = isSafePullRequestUrl(notification)
        ? notification.action_path
        : null
      toast.add({
        type: notification.category === "warning" ? "warning" : "info",
        title: notification.title,
        description: notification.body,
        ...(actionPath || pullRequestUrl
          ? {
              actionProps: {
                children: "View",
                onClick: () => {
                  if (pullRequestUrl) {
                    window.open(pullRequestUrl, "_blank", "noopener,noreferrer")
                    return
                  }
                  navigate(actionPath!)
                },
              },
            }
          : {}),
      })
    }
    stream.onopen = refreshNotifications
    stream.addEventListener("notification", handleNotification as EventListener)
    return () => {
      stream.onopen = null
      stream.close()
      channel?.close()
    }
  }, [isLeader, navigate, queryClient, session.data])

  useEffect(() => {
    if (!session.data || isLeader || typeof BroadcastChannel === "undefined") {
      return
    }
    const channel = new BroadcastChannel("trace.notifications")
    channel.onmessage = () =>
      void queryClient.invalidateQueries({ queryKey: notificationsQueryKey })
    return () => channel.close()
  }, [isLeader, queryClient, session.data])

  return null
}
