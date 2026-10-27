import { Skeleton } from "@/components/ui/skeleton"

function ReviewerCardSkeleton() {
  return (
    <article className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-start justify-between gap-3">
        <Skeleton className="h-5 w-36" />
        <Skeleton className="h-6 w-20" />
      </div>
      <Skeleton className="mt-3 h-4 w-48" />
      <Skeleton className="mt-2 h-3 w-36" />
    </article>
  )
}

export function ReviewDetailsPageSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading review" className="mt-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-3">
          <Skeleton className="h-6 w-40" />
          <Skeleton className="h-4 w-96 max-w-full" />
        </div>
        <Skeleton className="h-9 w-40" />
      </div>
      <dl className="mt-8 grid grid-cols-1 gap-x-6 gap-y-5 sm:grid-cols-2 md:grid-cols-4">
        {[0, 1, 2, 3].map((index) => (
          <div key={index} className="space-y-2">
            <Skeleton className="h-4 w-20" />
            <Skeleton className="h-4 w-28" />
          </div>
        ))}
      </dl>
      <div className="mt-8 flex gap-5 border-b border-border">
        <Skeleton className="mb-3 h-4 w-16" />
        <Skeleton className="mb-3 h-4 w-16" />
      </div>
      <section className="mt-8">
        <Skeleton className="h-5 w-20" />
        <div className="mt-3 grid gap-3">
          <ReviewerCardSkeleton />
          <ReviewerCardSkeleton />
        </div>
      </section>
    </div>
  )
}
