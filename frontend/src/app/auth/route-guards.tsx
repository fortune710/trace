import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { AuthLoading } from '@/components/auth/layout'
import { rememberReturnTo } from '@/app/auth/return-to'
import { useSession } from '@/hooks/use-session'
import { useSessionBoundary } from '@/components/auth/session-boundary-context'

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

  return <Outlet />
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
