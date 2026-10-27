import { Skeleton } from "@/components/ui/skeleton"

export function IntegrationCardSkeleton() {
  return (
    <article className="rounded-lg border border-border bg-card p-5">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <Skeleton className="size-10 rounded-md" />
          <div className="space-y-2">
            <Skeleton className="h-4 w-20" />
            <Skeleton className="h-4 w-56 max-w-full" />
          </div>
        </div>
        <Skeleton className="h-6 w-20 rounded-full" />
      </div>
      <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4">
        <Skeleton className="h-4 w-60 max-w-full" />
        <Skeleton className="h-8 w-28" />
      </div>
    </article>
  )
}

export function IntegrationsPageSkeleton() {
  return (
    <div
      aria-busy="true"
      aria-label="Loading integrations"
      className="mt-8 grid gap-4 md:grid-cols-2"
    >
      <IntegrationCardSkeleton />
      <IntegrationCardSkeleton />
    </div>
  )
}
