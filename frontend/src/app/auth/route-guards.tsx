import { Navigate, Outlet, useLocation } from "react-router-dom"

import { rememberReturnTo } from "@/app/auth/return-to"
import { AuthLoading } from "@/components/auth/layout"
import { useSessionBoundary } from "@/components/auth/session-boundary-context"
import { NotificationStream } from "@/hooks/use-notifications"
import { useSession } from "@/hooks/use-session"

export function AuthenticatedOnly() {
  const session = useSession()
  const location = useLocation()
  const boundary = useSessionBoundary()

  if (session.isPending) {
    return <AuthLoading />
  }

  if (!session.data && !boundary.isSessionExpired) {
    rememberReturnTo(`${location.pathname}${location.search}`)
    return <Navigate to="/sign-in" replace />
  }

  return (
    <>
      <NotificationStream />
      <Outlet />
    </>
  )
}

export function GuestOnly() {
  const session = useSession()

  if (session.isPending) {
    return <AuthLoading />
  }

  if (session.data) {
    return <Navigate to="/account" replace />
  }

  return <Outlet />
}
