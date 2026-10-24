import { createContext, useContext } from 'react'

type SessionBoundaryContextValue = {
  isSessionExpired: boolean
  markIntentionalLogout: () => void
  clearIntentionalLogout: () => void
}

const defaultValue: SessionBoundaryContextValue = {
  isSessionExpired: false,
  markIntentionalLogout: () => undefined,
  clearIntentionalLogout: () => undefined,
}

export const SessionBoundaryContext = createContext<SessionBoundaryContextValue>(defaultValue)

export function useSessionBoundary() {
  return useContext(SessionBoundaryContext)
}
