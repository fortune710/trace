// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter, useLocation } from "react-router-dom"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { IntegrationsPage } from "@/app/integrations/integrations-page"
import { toast } from "@/components/ui/toast"

const apiMocks = vi.hoisted(() => ({
  beginGitHubConnection: vi.fn(),
  githubConnection: vi.fn(),
}))

vi.mock("@/hooks/use-session", () => ({
  useSession: () => ({
    data: { display_name: "Trace User", email: "user@example.test" },
    isPending: false,
  }),
  useLogout: () => ({ isPending: false, mutate: vi.fn() }),
}))

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>()
  return {
    ...actual,
    authApi: {
      ...actual.authApi,
      beginGitHubConnection: apiMocks.beginGitHubConnection,
      githubConnection: apiMocks.githubConnection,
    },
  }
})

function Location() {
  const location = useLocation()
  return <output data-testid="location">{`${location.pathname}${location.search}`}</output>
}

function renderPage(route = "/integrations") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]}>
        <IntegrationsPage />
        <Location />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe("IntegrationsPage", () => {
  afterEach(() => {
    cleanup()
  })

  beforeEach(() => {
    apiMocks.beginGitHubConnection.mockReset()
    apiMocks.githubConnection.mockReset()
    apiMocks.githubConnection.mockResolvedValue({ provider: "github", status: "never_connected" })
    vi.restoreAllMocks()
    window.matchMedia = vi.fn().mockImplementation(() => ({
      addEventListener: vi.fn(),
      matches: false,
      removeEventListener: vi.fn(),
    }))
  })

  it.each([
    ["connected", "Connected", "Reconnect", "bg-emerald-500/15"],
    ["never_connected", "Not connected", "Connect GitHub", "bg-red-500/15"],
    ["needs_reconnection", "Reconnect required", "Reconnect", "bg-amber-500/15"],
  ] as const)("renders the %s GitHub state", async (status, label, action, badgeClass) => {
    apiMocks.githubConnection.mockResolvedValueOnce({ provider: "github", status })

    renderPage()

    const badge = await screen.findByText(label)
    expect(badge.className).toContain(badgeClass)
    expect(screen.getByRole("button", { name: action }).hasAttribute("disabled")).toBe(false)
  })

  it("shows GitLab as coming soon without a connection action", async () => {
    renderPage()

    expect(await screen.findByText("Coming soon")).toBeTruthy()
    expect(screen.queryByRole("button", { name: /gitlab/i })).toBeNull()
  })

  it("shows a success toast and clears the OAuth callback parameters", async () => {
    const addToast = vi.spyOn(toast, "add")

    renderPage("/integrations?github=connected&request_id=request-123")

    await waitFor(() => {
      expect(addToast).toHaveBeenCalledWith(
        expect.objectContaining({ type: "success", title: "GitHub connected" }),
      )
    })
    expect(screen.getByTestId("location").textContent).toBe("/integrations")
  })

  it("shows an error toast for a failed OAuth callback", async () => {
    const addToast = vi.spyOn(toast, "add")

    renderPage("/integrations?github=failed&request_id=request-123")

    await waitFor(() => {
      expect(addToast).toHaveBeenCalledWith(
        expect.objectContaining({
          type: "error",
          title: "GitHub connection failed",
          description: expect.stringContaining("request-123"),
        }),
      )
    })
  })

  it("shows an error toast when starting the connection fails", async () => {
    const addToast = vi.spyOn(toast, "add")
    apiMocks.beginGitHubConnection.mockRejectedValueOnce(new Error("request failed"))

    renderPage()

    fireEvent.click(await screen.findByRole("button", { name: "Connect GitHub" }))
    await waitFor(() => {
      expect(addToast).toHaveBeenCalledWith(
        expect.objectContaining({
          type: "error",
          title: "GitHub connection could not start",
        }),
      )
    })
  })

  it("allows reconnection when the GitHub status check fails", async () => {
    apiMocks.githubConnection.mockRejectedValueOnce(new Error("status unavailable"))
    apiMocks.beginGitHubConnection.mockImplementationOnce(
      () => new Promise(() => {}),
    )

    renderPage()

    expect(await screen.findByRole("button", { name: "Try again" })).toBeTruthy()
    const reconnectButton = screen.getByRole("button", { name: "Reconnect" })
    expect(reconnectButton.hasAttribute("disabled")).toBe(false)

    fireEvent.click(reconnectButton)

    await waitFor(() => {
      expect(apiMocks.beginGitHubConnection).toHaveBeenCalledOnce()
    })
  })

  it("disables the GitHub action while connection initiation is pending", async () => {
    let resolveConnection: ((value: { authorization_url: string }) => void) | undefined
    apiMocks.beginGitHubConnection.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveConnection = resolve
        }),
    )

    renderPage()

    const button = await screen.findByRole("button", { name: "Connect GitHub" })
    fireEvent.click(button)

    await waitFor(() => {
      expect(button.hasAttribute("disabled")).toBe(true)
      expect(button.textContent).toBe("Connecting…")
    })
    expect(resolveConnection).toBeDefined()
  })
})
