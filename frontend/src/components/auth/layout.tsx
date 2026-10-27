import type { ReactNode } from "react"
import { Link } from "react-router-dom"

import { Separator } from "@/components/ui/separator"
import { Skeleton } from "@/components/ui/skeleton"

export function AuthShell({ children }: { children: ReactNode }) {
  return (
    <main className="relative grid min-h-screen place-items-center overflow-hidden bg-background px-4 py-10 text-foreground">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 top-0 h-96 bg-[radial-gradient(ellipse_at_top,rgba(0,117,255,0.16),transparent_64%)]"
      />
      <section className="relative w-full max-w-md rounded-xl border border-border bg-card p-6 sm:p-8">
        <Link className="font-mono text-sm tracking-tight text-foreground" to="/account">
          trace
        </Link>
        <Separator className="my-6" />
        {children}
      </section>
    </main>
  )
}

/** Shared by each auth route, which uses the same title-and-form page layout. */
export function AuthPageSkeleton() {
  return (
    <AuthShell>
      <div aria-busy="true" aria-label="Loading authentication page">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="mt-3 h-4 w-full" />
        <div className="mt-6 grid gap-4">
          <div className="space-y-2">
            <Skeleton className="h-4 w-12" />
            <Skeleton className="h-9 w-full" />
          </div>
          <div className="space-y-2">
            <Skeleton className="h-4 w-16" />
            <Skeleton className="h-9 w-full" />
          </div>
          <Skeleton className="h-9 w-full" />
        </div>
        <div className="my-6 flex items-center gap-3">
          <Skeleton className="h-px flex-1" />
          <Skeleton className="h-3 w-4" />
          <Skeleton className="h-px flex-1" />
        </div>
        <div className="grid gap-3">
          <Skeleton className="h-9 w-full" />
          <Skeleton className="h-9 w-full" />
        </div>
        <Skeleton className="mt-6 h-4 w-3/4" />
      </div>
    </AuthShell>
  )
}

export function AuthLoading() {
  return <AuthPageSkeleton />
}

export function RequestError({ error }: { error: unknown }) {
  return (
    <p className="mt-3 text-sm text-destructive" role="alert">
      {error instanceof Error ? error.message : "Unable to complete the request."}
    </p>
  )
}
