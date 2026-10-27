import { Skeleton } from "@/components/ui/skeleton"

export function WorkspacePageSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading workspace page">
      <Skeleton className="h-6 w-36" />
    </div>
  )
}
