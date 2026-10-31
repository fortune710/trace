import { Skeleton } from "@/components/ui/skeleton"

export function LandingPageSkeleton() {
  return (
    <div
      aria-busy="true"
      aria-label="Loading landing page"
      className="min-h-svh bg-background"
    >
      <div className="border-b border-white/6">
        <div className="mx-auto flex h-16 w-full max-w-6xl items-center justify-between px-6 md:px-10">
          <Skeleton className="h-6 w-24" />
          <div className="hidden items-center gap-6 lg:flex">
            <Skeleton className="h-4 w-16" />
            <Skeleton className="h-4 w-20" />
            <Skeleton className="h-4 w-16" />
            <Skeleton className="h-4 w-10" />
          </div>
          <Skeleton className="h-9 w-20 rounded-md" />
        </div>
      </div>
      <div className="mx-auto flex w-full max-w-6xl flex-col items-center gap-8 px-6 pt-20 pb-16 md:px-10 md:pt-28 lg:pt-32">
        <Skeleton className="h-6 w-52 rounded-full" />
        <div className="flex w-full max-w-4xl flex-col items-center gap-3">
          <Skeleton className="h-12 w-full md:h-20" />
          <Skeleton className="h-12 w-3/4 md:h-20" />
        </div>
        <div className="flex w-full max-w-2xl flex-col items-center gap-2">
          <Skeleton className="h-5 w-full" />
          <Skeleton className="h-5 w-2/3" />
        </div>
        <div className="flex w-full flex-col items-center gap-3 sm:w-auto sm:flex-row">
          <Skeleton className="h-11 w-full rounded-md sm:h-10 sm:w-48" />
          <Skeleton className="h-11 w-full rounded-md sm:h-10 sm:w-40" />
        </div>
      </div>
      <div className="mx-auto w-full max-w-6xl px-6 md:px-10">
        <Skeleton className="h-[420px] w-full md:h-[560px]" />
      </div>
      <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center justify-center gap-8 px-6 py-16 md:px-10">
        <Skeleton className="h-5 w-24" />
        <Skeleton className="h-5 w-24" />
        <Skeleton className="h-5 w-24" />
        <Skeleton className="h-5 w-24" />
      </div>
      <div className="mx-auto grid w-full max-w-6xl gap-4 px-6 pb-24 md:grid-cols-2 md:px-10 lg:grid-cols-3">
        <Skeleton className="h-48 lg:col-span-2" />
        <Skeleton className="h-48" />
        <Skeleton className="h-48" />
        <Skeleton className="h-48" />
        <Skeleton className="h-48" />
      </div>
    </div>
  )
}
