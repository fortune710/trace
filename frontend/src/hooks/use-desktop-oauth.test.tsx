// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, useLocation } from "react-router-dom"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import {
  DesktopOAuthBootstrap,
  useDesktopOAuth,
} from "@/hooks/use-desktop-oauth"

const testState = vi.hoisted(() => ({
  deepLinkHandler: null as ((urls: string[]) => void) | null,
  open: vi.fn(async () => undefined),
  exchange: vi.fn(async () => undefined),
  toastAdd: vi.fn(),
}))

vi.mock("@tauri-apps/api/core", () => ({ isTauri: () => true }))
vi.mock("@tauri-apps/plugin-shell", () => ({ open: testState.open }))
vi.mock("@tauri-apps/plugin-deep-link", () => ({
  onOpenUrl: async (handler: (urls: string[]) => void) => {
    testState.deepLinkHandler = handler
    return () => {
      testState.deepLinkHandler = null
    }
  },
  getCurrent: async () => null,
}))
vi.mock("@/lib/api", () => ({
  authApi: {
    desktopOAuthUrl: (provider: string) => `https://api.example.test/${provider}`,
    exchangeDesktopOAuth: testState.exchange,
  },
}))
vi.mock("@/components/ui/toast", () => ({
  toast: { add: testState.toastAdd },
}))

function DesktopSignIn() {
  const oauth = useDesktopOAuth()
  const location = useLocation()

  return (
    <>
      <button
        disabled={oauth.isPending}
        onClick={() => void oauth.start("google")}
      >
        Continue with Google
      </button>
      <output data-testid="location">{`${location.pathname}${location.search}`}</output>
      <DesktopOAuthBootstrap />
    </>
  )
}

function renderDesktopSignIn() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={["/sign-in"]}>
        <DesktopSignIn />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe("desktop OAuth handoff", () => {
  beforeEach(() => {
    vi.stubGlobal("crypto", {
      getRandomValues: (bytes: Uint8Array) => bytes.fill(1),
      subtle: {
        digest: async () => new Uint8Array(32).buffer,
      },
    })
    testState.open.mockClear()
    testState.exchange.mockClear()
    testState.toastAdd.mockClear()
  })

  afterEach(() => {
    cleanup()
    sessionStorage.clear()
    vi.unstubAllGlobals()
  })

  it("exchanges the deep-link ticket and navigates to the account", async () => {
    renderDesktopSignIn()
    await userEvent.setup().click(screen.getByRole("button", { name: "Continue with Google" }))

    await waitFor(() => expect(testState.open).toHaveBeenCalledOnce())
    expect(screen.getByRole("button", { name: "Continue with Google" }).hasAttribute("disabled")).toBe(true)

    testState.deepLinkHandler?.(["trace://oauth/callback?code=abcdefghijklmnop"])

    await waitFor(() => expect(testState.exchange).toHaveBeenCalledOnce())
    expect(await screen.findByTestId("location")).toHaveProperty("textContent", "/account")
    expect(screen.getByRole("button", { name: "Continue with Google" }).hasAttribute("disabled")).toBe(false)
  })

  it("shows a toast and reenables sign-in after a callback error", async () => {
    renderDesktopSignIn()
    await userEvent.setup().click(screen.getByRole("button", { name: "Continue with Google" }))
    await waitFor(() => expect(testState.open).toHaveBeenCalledOnce())

    testState.deepLinkHandler?.(["trace://oauth/callback?error=oauth_failed"])
    await waitFor(() => {
      expect(screen.getByTestId("location").textContent).toBe("/sign-in")
      expect(screen.getByRole("button", { name: "Continue with Google" }).hasAttribute("disabled")).toBe(false)
      expect(testState.toastAdd).toHaveBeenCalledWith(
        expect.objectContaining({
          type: "error",
          title: "Desktop sign-in was not completed",
        }),
      )
    })
  })
})
