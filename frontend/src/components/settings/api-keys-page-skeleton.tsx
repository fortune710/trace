import { Skeleton } from "@/components/ui/skeleton"

function ApiKeyRowSkeleton() {
  return (
    <article className="flex flex-wrap items-start justify-between gap-4 rounded-lg border border-white/14 bg-[#0a0a0c] p-5">
      <div className="space-y-2">
        <Skeleton className="h-4 w-36" />
        <Skeleton className="h-3 w-48" />
      </div>
      <div className="flex items-center gap-3">
        <Skeleton className="h-6 w-14 rounded-full" />
        <Skeleton className="h-8 w-16" />
      </div>
    </article>
  )
}

export function ApiKeysPageSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading API keys">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-2">
          <Skeleton className="h-6 w-24" />
          <Skeleton className="h-4 w-96 max-w-full" />
          <Skeleton className="h-4 w-80 max-w-full" />
        </div>
        <Skeleton className="h-9 w-28" />
      </div>
      <div className="mt-8 grid gap-4">
        <ApiKeyRowSkeleton />
        <ApiKeyRowSkeleton />
      </div>
    </div>
  )
}

export function ApiKeysListSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading API keys" className="mt-8 grid gap-4">
      <ApiKeyRowSkeleton />
      <ApiKeyRowSkeleton />
    </div>
  )
}
