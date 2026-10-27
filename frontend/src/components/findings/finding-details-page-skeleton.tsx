import { Skeleton } from "@/components/ui/skeleton"

export function FindingDetailsPageSkeleton() {
  return (
    <article
      aria-busy="true"
      aria-label="Loading finding"
      className="mt-6 rounded-lg border border-border bg-card p-6"
    >
      <Skeleton className="h-3 w-28" />
      <Skeleton className="mt-3 h-6 w-2/3 max-w-full" />
      <div className="mt-5 space-y-2">
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-11/12" />
        <Skeleton className="h-4 w-4/5" />
      </div>
      <dl className="mt-6 grid gap-5">
        {[0, 1, 2, 3].map((index) => (
          <div key={index} className="space-y-2">
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-4 w-3/4" />
          </div>
        ))}
      </dl>
    </article>
  )
}
