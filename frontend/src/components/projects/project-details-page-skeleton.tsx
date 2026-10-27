import { Skeleton } from "@/components/ui/skeleton"

function ReviewCardSkeleton() {
  return (
    <article className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center justify-between gap-2">
        <Skeleton className="h-4 w-28" />
        <Skeleton className="h-6 w-16 rounded-full" />
      </div>
      <Skeleton className="mt-3 h-3 w-64 max-w-full" />
    </article>
  )
}

export function ProjectActivitySkeleton() {
  return (
    <div className="grid gap-3" aria-busy="true" aria-label="Loading project activity">
      <ReviewCardSkeleton />
      <ReviewCardSkeleton />
    </div>
  )
}

export function ProjectDetailsPageSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading project" className="mt-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-3">
          <Skeleton className="h-6 w-48" />
          <Skeleton className="h-4 w-64 max-w-full" />
        </div>
        <Skeleton className="h-9 w-28" />
      </div>
      <dl className="mt-8 grid grid-cols-1 gap-x-6 gap-y-5 sm:grid-cols-2 md:grid-cols-4">
        {[0, 1, 2, 3].map((index) => (
          <div key={index} className="space-y-2">
            <Skeleton className="h-4 w-20" />
            <Skeleton className="h-4 w-28" />
          </div>
        ))}
      </dl>
      <div className="mt-8 flex gap-5 border-b border-white/10">
        <Skeleton className="mb-3 h-4 w-16" />
        <Skeleton className="mb-3 h-4 w-16" />
      </div>
      <div className="mt-6">
        <ProjectActivitySkeleton />
      </div>
    </div>
  )
}
