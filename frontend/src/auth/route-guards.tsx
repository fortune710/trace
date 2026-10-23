import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { AuthLoading } from '@/auth/layout'
import { rememberReturnTo } from '@/auth/return-to'
import { useSession } from '@/auth/session'
export function AuthenticatedOnly() { const session = useSession(); const location = useLocation(); if (session.isPending) return <AuthLoading />; if (!session.data) { rememberReturnTo(`${location.pathname}${location.search}`); return <Navigate to="/sign-in" replace /> }; return <Outlet /> }
export function GuestOnly() { const session = useSession(); if (session.isPending) return <AuthLoading />; if (session.data) return <Navigate to="/account" replace />; return <Outlet /> }
