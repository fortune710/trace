import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { authApi, isUnauthenticated, type Session } from '@/lib/api'
import { getDesktopCsrfToken } from '@/lib/desktop-auth-state'
import { isTauri } from '@tauri-apps/api/core'
import { useSessionBoundary } from '@/components/auth/session-boundary-context'

export const sessionQueryKey = ['auth', 'session'] as const

let refreshInFlight: Promise<void> | undefined

function refreshOnce() {
  const hasCsrfToken = isTauri()
    ? Boolean(getDesktopCsrfToken())
    : document.cookie.includes('trace_csrf=')

  if (!hasCsrfToken) {
    return Promise.reject(new Error('No active session'))
  }

  refreshInFlight ??= authApi
    .refresh()
    .then(() => undefined)
    .finally(() => {
      refreshInFlight = undefined
    })

  return refreshInFlight
}

async function loadSession(): Promise<Session | null> {
  try {
    return await authApi.session()
  } catch (error) {
    if (!isUnauthenticated(error)) {
      throw error
    }
  }

  try {
    await refreshOnce()
    return await authApi.session()
  } catch {
    return null
  }
}

export function useSession() {
  return useQuery({
    queryKey: sessionQueryKey,
    queryFn: loadSession,
    staleTime: 0,
    gcTime: 0,
    retry: false,
  })
}

export function useLogout() {
  const queryClient = useQueryClient()
  const boundary = useSessionBoundary()

  return useMutation({
    mutationFn: authApi.logout,
    retry: false,
    onMutate: () => boundary.markIntentionalLogout(),
    onError: () => boundary.clearIntentionalLogout(),
    onSettled: () => queryClient.setQueryData(sessionQueryKey, null),
  })
}
