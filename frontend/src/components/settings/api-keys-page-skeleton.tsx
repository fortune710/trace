import { Skeleton } from "@/components/ui/skeleton"

function ApiKeyCardSkeleton() {
  return (
    <section className="space-y-4">
      <div className="space-y-2">
        <Skeleton className="h-6 w-48" />
        <Skeleton className="h-5 w-96 max-w-full" />
      </div>
      <div className="rounded-lg border border-white/6 bg-card p-4">
        <div className="flex items-center justify-between gap-4">
          <Skeleton className="h-5 w-20" />
          <Skeleton className="h-10 w-80 max-w-full" />
        </div>
        <Skeleton className="mt-4 h-4 w-80 max-w-full" />
      </div>
    </section>
  )
}

export function ApiKeysPageSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading API keys">
      <div className="space-y-12">
        <div className="space-y-2">
          <Skeleton className="h-6 w-24" />
          <Skeleton className="h-4 w-96 max-w-full" />
          <Skeleton className="h-4 w-80 max-w-full" />
        </div>
        <ApiKeyCardSkeleton />
        <ApiKeyCardSkeleton />
        <ApiKeyCardSkeleton />
      </div>
    </div>
  )
}

export function ApiKeysListSkeleton() {
  return (
    <div
      aria-busy="true"
      aria-label="Loading API keys"
      className="mt-8 grid gap-14"
    >
      <ApiKeyCardSkeleton />
      <ApiKeyCardSkeleton />
    </div>
  )
}
