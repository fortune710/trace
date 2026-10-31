import { useQueryClient } from "@tanstack/react-query"
import { isTauri } from "@tauri-apps/api/core"
import { getCurrent, onOpenUrl } from "@tauri-apps/plugin-deep-link"
import { open } from "@tauri-apps/plugin-shell"
import { useCallback, useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"

import { consumeReturnTo } from "@/app/auth/return-to"
import { sessionQueryKey } from "@/hooks/use-session"
import { authApi } from "@/lib/api"
import { toast } from "@/components/ui/toast"

type OAuthProvider = "github" | "google"
type PendingOAuth = { provider: OAuthProvider; verifier: string }

let pendingOAuth: PendingOAuth | null = null
let pendingTimeout: number | null = null
const handledCodes = new Set<string>()
const oauthFinishedEvent = "trace:desktop-oauth-finished"

function finishPendingOAuth() {
  pendingOAuth = null
  if (pendingTimeout !== null) {
    window.clearTimeout(pendingTimeout)
    pendingTimeout = null
  }
  window.dispatchEvent(new Event(oauthFinishedEvent))
}

function showDesktopOAuthError(description: string) {
  finishPendingOAuth()
  toast.add({
    type: "error",
    title: "Desktop sign-in was not completed",
    description,
  })
}

function base64Url(bytes: Uint8Array) {
  let binary = ""
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte)
  })
  return btoa(binary)
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/g, "")
}

async function createVerifierAndChallenge() {
  const verifier = base64Url(crypto.getRandomValues(new Uint8Array(32)))
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(verifier),
  )
  return { verifier, challenge: base64Url(new Uint8Array(digest)) }
}

export function useDesktopOAuth() {
  const desktop = isTauri()
  const [isPending, setIsPending] = useState(false)

  useEffect(() => {
    const resetPending = () => setIsPending(false)
    window.addEventListener(oauthFinishedEvent, resetPending)
    return () => window.removeEventListener(oauthFinishedEvent, resetPending)
  }, [])

  const start = useCallback(async (provider: OAuthProvider) => {
    if (!desktop) return
    setIsPending(true)
    try {
      const { verifier, challenge } = await createVerifierAndChallenge()
      pendingOAuth = { provider, verifier }
      pendingTimeout = window.setTimeout(() => {
        if (pendingOAuth?.verifier !== verifier) return
        showDesktopOAuthError("Sign-in timed out. Please try again.")
      }, 5 * 60_000)
      await open(authApi.desktopOAuthUrl(provider, challenge))
    } catch {
      showDesktopOAuthError("Unable to open the sign-in browser. Please try again.")
    }
  }, [desktop])

  return { start, isPending }
}

function parseCallback(value: string) {
  let url: URL
  try {
    url = new URL(value)
  } catch {
    return null
  }
  if (
    url.protocol !== "trace:" ||
    url.hostname !== "oauth" ||
    url.pathname !== "/callback"
  ) {
    return null
  }
  const code = url.searchParams.get("code")
  const error = url.searchParams.get("error")
  if (error) return { error: "oauth_failed" as const }
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
        if ("error" in callback) {
          showDesktopOAuthError("The provider did not complete sign-in. Please try again.")
          navigate("/sign-in", { replace: true })
          return
        }
        if (handledCodes.has(callback.code)) return
        handledCodes.add(callback.code)
        const pending = pendingOAuth
        if (!pending) {
          showDesktopOAuthError("This sign-in attempt expired. Please try again.")
          navigate("/sign-in", { replace: true })
          return
        }
        void authApi.exchangeDesktopOAuth(callback.code, pending.verifier)
          .then(async () => {
            if (disposed) return
            finishPendingOAuth()
            await queryClient.invalidateQueries({ queryKey: sessionQueryKey })
            navigate(consumeReturnTo(), { replace: true })
          })
          .catch(() => {
            if (disposed) return
            showDesktopOAuthError("Unable to finish sign-in. Please try again.")
            navigate("/sign-in", { replace: true })
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
    void setup().catch(() => {
      if (disposed) return
      showDesktopOAuthError("Unable to receive the sign-in callback. Please try again.")
      navigate("/sign-in", { replace: true })
    })
    return () => {
      disposed = true
      unlisten?.()
    }
  }, [desktop, navigate, queryClient])

  return null
}
