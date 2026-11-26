import { useEffect, type ReactNode } from "react"
import { PostHogProvider } from "@posthog/react"
import posthog from "posthog-js"
import { useLocation } from "react-router-dom"

import {
  getAnalyticsStatus,
  identifyUser,
  registerRouteContext,
  resetAnalytics,
} from "@/lib/analytics"
import { useSession } from "@/hooks/use-session"

function AnalyticsIdentity() {
  const session = useSession()

  useEffect(() => {
    if (session.data?.user_id) {
      identifyUser(session.data.user_id, {
        email: session.data.email,
        display_name: session.data.display_name,
        automatic_pull_requests: session.data.automatic_pull_requests,
      })
      return
    }

    if (session.isSuccess && !session.data) {
      const status = getAnalyticsStatus()
      if (status.identifiedUserId) {
        resetAnalytics()
      }
    }
  }, [session.data, session.isSuccess])

  return null
}

function AnalyticsRouteContext() {
  const location = useLocation()

  useEffect(() => {
    registerRouteContext(location.pathname)
  }, [location.pathname])

  return null
}

export function AnalyticsProvider({ children }: { children: ReactNode }) {
  return (
    <PostHogProvider client={posthog}>
      <AnalyticsIdentity />
      <AnalyticsRouteContext />
      {children}
    </PostHogProvider>
  )
}
