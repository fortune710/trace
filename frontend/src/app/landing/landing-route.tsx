import { lazy, Suspense } from "react"

import { Navigate } from "react-router-dom"

import { LandingPageSkeleton } from "@/components/landing/landing-page-skeleton"
import { useRuntimeEnvironment } from "@/hooks/use-runtime-environment"

const LandingPage = lazy(() => import("@/app/landing/landing-page"))

export function LandingRoute() {
  const runtime = useRuntimeEnvironment()

  if (runtime.isTauri) {
    return (
      <Navigate
        to="/account"
        replace
      />
    )
  }

  return (
    <Suspense fallback={<LandingPageSkeleton />}>
      <LandingPage />
    </Suspense>
  )
}
