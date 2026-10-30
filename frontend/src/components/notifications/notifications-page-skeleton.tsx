import { Skeleton } from "@/components/ui/skeleton"

function NotificationRowSkeleton() {
  return (
    <article className="rounded-lg border p-4">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 space-y-2">
          <Skeleton className="h-3 w-16" />
          <Skeleton className="h-4 w-48 max-w-full" />
          <Skeleton className="h-4 w-80 max-w-full" />
          <Skeleton className="h-3 w-28" />
        </div>
        <Skeleton className="h-8 w-20 shrink-0" />
      </div>
      <Skeleton className="mt-3 h-4 w-10" />
    </article>
  )
}

function NotificationDateGroupSkeleton({ rows }: { rows: number }) {
  return (
    <section className="space-y-3">
      <Skeleton className="h-4 w-32" />
      <div className="space-y-3">
        {Array.from({ length: rows }, (_, index) => (
          <NotificationRowSkeleton key={index} />
        ))}
      </div>
    </section>
  )
}

export function NotificationsPageSkeleton() {
  return (
    <div
      aria-busy="true"
      aria-label="Loading notifications"
      className="space-y-6"
    >
      <NotificationDateGroupSkeleton rows={2} />
      <NotificationDateGroupSkeleton rows={1} />
    </div>
  )
}
