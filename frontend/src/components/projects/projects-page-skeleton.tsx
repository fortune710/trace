import { Skeleton } from "@/components/ui/skeleton"

function ProjectCardSkeleton() {
  return (
    <article className="rounded-lg border border-border bg-card p-5">
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 items-center gap-3">
          <Skeleton className="size-9 shrink-0 rounded-md" />
          <div className="min-w-0 space-y-2">
            <Skeleton className="h-4 w-36" />
            <Skeleton className="h-3 w-48 max-w-full" />
          </div>
        </div>
        <Skeleton className="h-6 w-16 rounded-full" />
      </div>
      <div className="mt-5 grid grid-cols-2 gap-4 border-t border-border pt-4">
        <div className="space-y-2">
          <Skeleton className="h-3 w-12" />
          <Skeleton className="h-3 w-20" />
        </div>
        <div className="space-y-2">
          <Skeleton className="h-3 w-14" />
          <Skeleton className="h-3 w-16" />
        </div>
      </div>
      <Skeleton className="mt-5 h-3 w-28" />
    </article>
  )
}

export function ProjectsPageSkeleton() {
  return (
    <div
      aria-busy="true"
      aria-label="Loading projects"
      className="grid gap-4 md:grid-cols-2 xl:grid-cols-3"
    >
      <ProjectCardSkeleton />
      <ProjectCardSkeleton />
      <ProjectCardSkeleton />
    </div>
  )
}
