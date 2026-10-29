import { useState } from "react"
import { ArrowLeft01Icon, ArrowRight01Icon } from "@hugeicons/core-free-icons"
import { HugeiconsIcon } from "@hugeicons/react"
import { Link } from "react-router-dom"

import { AppShell } from "@/components/layout/app-shell"
import { NotificationsPageSkeleton } from "@/components/notifications/notifications-page-skeleton"
import { Button } from "@/components/ui/button"
import {
  useMarkAllNotificationsRead,
  useMarkNotificationRead,
  useNotifications,
} from "@/hooks/use-notifications"

function isSafeActionPath(actionPath: string | null): actionPath is string {
  return Boolean(actionPath && /^\/[^/]/.test(actionPath))
}

function isSafePullRequestUrl(notification: {
  action_path: string | null
  event_type: string
}): notification is {
  action_path: string
  event_type: "pull_request_created"
} {
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

function formatCategory(category: "info" | "security" | "warning") {
  return category[0].toUpperCase() + category.slice(1)
}

function formatTimestamp(createdAt: string) {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(createdAt))
}

export function NotificationsPage() {
  const [page, setPage] = useState(1)
  const notifications = useNotifications(page)
  const markRead = useMarkNotificationRead()
  const markAllRead = useMarkAllNotificationsRead()

  return (
    <AppShell>
      <section className="mx-auto w-full max-w-6xl px-6 pt-8 pb-28 md:px-10 md:pt-10">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h1 className="text-xl font-medium tracking-tight">
              Notifications
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              {notifications.unreadCount
                ? `${notifications.unreadCount} unread`
                : "You are all caught up."}
            </p>
          </div>
          <Button
            type="button"
            variant="outline"
            disabled={!notifications.unreadCount || markAllRead.isPending}
            onClick={() => markAllRead.mutate()}
          >
            Mark all read
          </Button>
        </div>
        <div className="mt-8 space-y-3">
          {notifications.isLoading ? <NotificationsPageSkeleton /> : null}
          {notifications.isError ? (
            <Button
              type="button"
              variant="outline"
              onClick={() => void notifications.refetch()}
            >
              Try again
            </Button>
          ) : null}
          {!notifications.isLoading &&
          !notifications.isError &&
          notifications.notifications.length === 0 ? (
            <p className="rounded-lg border p-6 text-sm text-muted-foreground">
              No notifications yet.
            </p>
          ) : null}
          {notifications.notifications.map((notification) => (
            <article
              key={notification.id}
              aria-label={`${notification.read_at ? "Read" : "Unread"} ${formatCategory(notification.category)} notification: ${notification.title}`}
              className={`rounded-lg border p-4 ${
                notification.read_at
                  ? "bg-card"
                  : "border-primary/30 bg-primary/5"
              }`}
            >
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    {formatCategory(notification.category)}
                  </p>
                  <p className="text-sm font-medium">{notification.title}</p>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {notification.body}
                  </p>
                  <time
                    className="mt-2 block text-xs text-muted-foreground"
                    dateTime={notification.created_at}
                  >
                    {formatTimestamp(notification.created_at)}
                  </time>
                </div>
                {!notification.read_at ? (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={markRead.isPending}
                    onClick={() => markRead.mutate(notification.id)}
                  >
                    Mark read
                  </Button>
                ) : null}
              </div>
              {isSafeActionPath(notification.action_path) ? (
                <Link
                  to={notification.action_path}
                  className="mt-3 inline-block text-sm text-primary hover:underline"
                >
                  View
                </Link>
              ) : isSafePullRequestUrl(notification) ? (
                <a
                  href={notification.action_path}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-3 inline-block text-sm text-primary hover:underline"
                >
                  View
                </a>
              ) : null}
            </article>
          ))}
        </div>
        <nav
          className="fixed right-6 bottom-6 z-20 flex items-center gap-2 md:right-10"
          aria-label="Notification pagination"
        >
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={page === 1 || notifications.isFetching}
            onClick={() => setPage((value) => value - 1)}
          >
            <HugeiconsIcon icon={ArrowLeft01Icon} size={15} strokeWidth={2} />
            Previous
          </Button>
          <span
            className="min-w-16 text-center text-xs text-muted-foreground"
            aria-live="polite"
          >
            Page {page}
          </span>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={!notifications.hasNextPage || notifications.isFetching}
            onClick={() => setPage((value) => value + 1)}
          >
            Next
            <HugeiconsIcon icon={ArrowRight01Icon} size={15} strokeWidth={2} />
          </Button>
        </nav>
      </section>
    </AppShell>
  )
}
