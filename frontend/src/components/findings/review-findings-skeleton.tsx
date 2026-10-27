import { Skeleton } from "@/components/ui/skeleton"

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

export function ReviewFindingsSkeleton() {
  return (
    <div
      aria-busy="true"
      aria-label="Loading findings"
      className="mt-6 grid gap-3"
    >
      <FindingCardSkeleton />
      <FindingCardSkeleton />
      <FindingCardSkeleton />
    </div>
  )
}
