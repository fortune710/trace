import { Skeleton } from "@/components/ui/skeleton"

function AgentCardSkeleton() {
  return (
    <article className="rounded-lg border border-white/14 bg-[#0a0a0c] p-5">
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 items-center gap-3">
          <Skeleton className="size-10 shrink-0 rounded-full" />
          <div className="space-y-2">
            <Skeleton className="h-4 w-32" />
            <Skeleton className="h-5 w-20" />
          </div>
        </div>
        <Skeleton className="h-6 w-14 rounded-full" />
      </div>
      <div className="mt-5 grid grid-cols-2 gap-4 border-t border-white/6 pt-4">
        <div className="space-y-2">
          <Skeleton className="h-3 w-12" />
          <Skeleton className="h-3 w-24" />
        </div>
        <div className="space-y-2">
          <Skeleton className="h-3 w-10" />
          <Skeleton className="h-3 w-20" />
        </div>
      </div>
    </article>
  )
}

export function AgentsPageSkeleton() {
  return (
    <div
      aria-busy="true"
      aria-label="Loading agents"
      className="grid gap-4 md:grid-cols-2 xl:grid-cols-3"
    >
      <AgentCardSkeleton />
      <AgentCardSkeleton />
      <AgentCardSkeleton />
    </div>
  )
}
