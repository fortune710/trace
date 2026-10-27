import { Skeleton } from "@/components/ui/skeleton"

export function AgentDetailsPageSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading agent" className="mt-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-3">
          <Skeleton className="h-6 w-40" />
          <Skeleton className="h-5 w-24" />
        </div>
        <Skeleton className="h-9 w-20" />
      </div>
      <div className="mt-8 flex gap-5 border-b border-white/10">
        <Skeleton className="mb-3 h-4 w-20" />
        <Skeleton className="mb-3 h-4 w-12" />
        <Skeleton className="mb-3 h-4 w-14" />
      </div>
      <div className="mt-6 px-4">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="mt-2 h-4 w-96 max-w-full" />
      </div>
      <section className="mt-4 overflow-hidden rounded-lg border border-white/14 bg-[#0a0a0c] p-5">
        <Skeleton className="h-4 w-28" />
        <div className="mt-3 space-y-2">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-11/12" />
          <Skeleton className="h-4 w-3/4" />
        </div>
      </section>
    </div>
  )
}
