import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { getCurrent, onOpenUrl } from '@tauri-apps/plugin-deep-link'
import { open } from '@tauri-apps/plugin-shell'
import { consumeReturnTo } from '@/app/auth/return-to'
import { sessionQueryKey } from '@/hooks/use-session'
import { authApi } from '@/lib/api'
import { isTauri } from '@tauri-apps/api/core'

type OAuthProvider = 'github' | 'google'
type PendingOAuth = { provider: OAuthProvider; verifier: string }

let pendingOAuth: PendingOAuth | null = null
const handledCodes = new Set<string>()

function base64Url(bytes: Uint8Array) {
  let binary = ''
  bytes.forEach((byte) => { binary += String.fromCharCode(byte) })
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '')
}

async function createVerifierAndChallenge() {
  const verifier = base64Url(crypto.getRandomValues(new Uint8Array(32)))
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier))
  return { verifier, challenge: base64Url(new Uint8Array(digest)) }
}

export function useDesktopOAuth() {
  const desktop = isTauri()
  const [isPending, setIsPending] = useState(false)
  const [error, setError] = useState<Error | null>(null)

  const start = useCallback(async (provider: OAuthProvider) => {
    if (!desktop) return
    setError(null)
    setIsPending(true)
    try {
      const { verifier, challenge } = await createVerifierAndChallenge()
      pendingOAuth = { provider, verifier }
      await open(authApi.desktopOAuthUrl(provider, challenge))
    } catch {
      pendingOAuth = null
      setIsPending(false)
      setError(new Error('Unable to open the sign-in browser. Please try again.'))
    }
  }, [desktop])

  return { start, isPending, error }
}

function parseCallback(value: string) {
  let url: URL
  try { url = new URL(value) } catch { return null }
  if (url.protocol !== 'trace:' || url.hostname !== 'oauth' || url.pathname !== '/callback') return null
  const code = url.searchParams.get('code')
  const error = url.searchParams.get('error')
  if (error) return { error: 'oauth_failed' as const }
  if (!code || !/^[A-Za-z0-9_-]{16,512}$/.test(code)) return null
  return { code }
}

export function DesktopOAuthBootstrap() {
  const desktop = isTauri()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  useEffect(() => {
    if (!desktop) return
    let disposed = false
    const handleUrls = (urls: string[]) => {
      urls.forEach((value) => {
        const callback = parseCallback(value)
        if (!callback) return
        if ('error' in callback) {
          pendingOAuth = null
          navigate('/sign-in?desktop_error=oauth_failed', { replace: true })
          return
        }
        if (handledCodes.has(callback.code)) return
        handledCodes.add(callback.code)
        const pending = pendingOAuth
        if (!pending) {
          navigate('/sign-in?desktop_error=expired', { replace: true })
          return
        }
        void authApi.exchangeDesktopOAuth(callback.code, pending.verifier)
          .then(async () => {
            if (disposed) return
            pendingOAuth = null
            await queryClient.invalidateQueries({ queryKey: sessionQueryKey })
            navigate(consumeReturnTo(), { replace: true })
          })
          .catch(() => {
            pendingOAuth = null
            navigate('/sign-in?desktop_error=exchange_failed', { replace: true })
          })
      })
    }

    let unlisten: (() => void) | undefined
    const setup = async () => {
      const unregister = await onOpenUrl(handleUrls)
      if (disposed) unregister()
      else unlisten = unregister
      const current = await getCurrent()
      if (!disposed && current) handleUrls(current)
    }
    void setup()
    return () => { disposed = true; unlisten?.() }
  }, [desktop, navigate, queryClient])

  return null
}
