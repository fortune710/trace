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

function FindingCardSkeleton() {
  return (
    <article className="rounded-lg border border-border bg-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-2">
          <Skeleton className="h-4 w-48" />
          <Skeleton className="h-3 w-28" />
        </div>
        <Skeleton className="h-6 w-16 rounded-md" />
      </div>
      <Skeleton className="mt-4 h-4 w-full" />
      <Skeleton className="mt-2 h-4 w-4/5" />
    </article>
  )
}

export function ProjectFindingsSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading project findings">
      <div className="grid max-w-sm gap-1">
        <Skeleton className="h-4 w-12" />
        <Skeleton className="h-9 w-full" />
      </div>
      <section className="mt-6" aria-label="Findings">
        <div className="space-y-2">
          <Skeleton className="h-5 w-20" />
          <Skeleton className="h-4 w-80 max-w-full" />
        </div>
        <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {[0, 1, 2, 3].map((index) => (
            <div key={index} className="grid gap-1">
              <Skeleton className="h-4 w-16" />
              <Skeleton className="h-9 w-full" />
            </div>
          ))}
        </div>
        <div className="mt-6 grid gap-3">
          <FindingCardSkeleton />
          <FindingCardSkeleton />
          <FindingCardSkeleton />
        </div>
      </section>
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
