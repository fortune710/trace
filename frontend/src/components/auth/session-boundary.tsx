import { useEffect, useMemo, useReducer, type ReactNode } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { useSession } from '@/hooks/use-session'
import { rememberReturnTo } from '@/app/auth/return-to'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { SessionBoundaryContext } from '@/components/auth/session-boundary-context'

function isGuestRoute(pathname: string) {
  return pathname === '/sign-in'
    || pathname === '/sign-up'
    || pathname === '/forgot-password'
    || pathname === '/reset-password'
    || pathname.startsWith('/auth/')
}

function authenticatedSessionReducer(previous: boolean, action: 'authenticated') {
  return previous || action === 'authenticated'
}

function intentionalLogoutReducer(_previous: boolean, action: 'mark' | 'clear') {
  return action === 'mark'
}

export function SessionBoundary({ children }: { children: ReactNode }) {
  const session = useSession()
  const location = useLocation()
  const navigate = useNavigate()
  const [hadAuthenticatedSession, markAuthenticatedSession] = useReducer(
    authenticatedSessionReducer,
    Boolean(session.data),
  )
  const [intentionalLogout, updateIntentionalLogout] = useReducer(intentionalLogoutReducer, false)

  useEffect(() => {
    if (session.data) {
      markAuthenticatedSession('authenticated')
      updateIntentionalLogout('clear')
    }
  }, [session.data])

  const isSessionExpired = session.isSuccess
    && !session.data
    && hadAuthenticatedSession
    && !intentionalLogout
    && !isGuestRoute(location.pathname)

  const contextValue = useMemo(() => ({
    isSessionExpired,
    markIntentionalLogout: () => updateIntentionalLogout('mark'),
    clearIntentionalLogout: () => updateIntentionalLogout('clear'),
  }), [isSessionExpired])

  function goToSignIn() {
    rememberReturnTo(`${location.pathname}${location.search}`)
    navigate('/sign-in', { replace: true })
  }

  return (
    <SessionBoundaryContext.Provider value={contextValue}>
      {children}
      <Dialog open={isSessionExpired} onOpenChange={() => undefined}>
        <DialogContent showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>Your session has ended</DialogTitle>
            <DialogDescription>
              Your Trace session is no longer active. Sign in again to continue.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button onClick={goToSignIn}>Go to sign in</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </SessionBoundaryContext.Provider>
  )
}
