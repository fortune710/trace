import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { AuthLoading } from '@/components/auth/layout'
import { rememberReturnTo } from '@/app/auth/return-to'
import { useSession } from '@/hooks/use-session'
export function AuthenticatedOnly() { const session = useSession(); const location = useLocation(); if (session.isPending) return <AuthLoading />; if (!session.data) { rememberReturnTo(`${location.pathname}${location.search}`); return <Navigate to="/sign-in" replace /> }; return <Outlet /> }
export function GuestOnly() { const session = useSession(); if (session.isPending) return <AuthLoading />; if (session.data) return <Navigate to="/account" replace />; return <Outlet /> }
