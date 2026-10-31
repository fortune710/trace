// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { cleanup, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { ApiKeysPage } from "@/app/settings/api-keys-page"
import { toast } from "@/components/ui/toast"

const agentMocks = vi.hoisted(() => ({
  create: vi.fn(),
  credentials: vi.fn(),
  rotate: vi.fn(),
}))

vi.mock("@/hooks/use-session", () => ({
  useSession: () => ({
    data: { display_name: "Trace User", email: "user@example.test" },
    isPending: false,
  }),
  useLogout: () => ({ isPending: false, mutate: vi.fn() }),
}))

vi.mock("@/hooks/use-agents", () => ({
  useCreateProviderCredential: agentMocks.create,
  useProviderCredentials: agentMocks.credentials,
  useRotateProviderCredential: agentMocks.rotate,
}))

vi.mock("@/components/ui/toast", () => ({
  toast: { add: vi.fn() },
}))

const savedKeys = [
  {
    id: "key-1",
    provider: "openai",
    kind: "api_key",
    name: null,
    active: true,
    created_at: "2026-10-25T00:00:00.000Z",
    updated_at: "2026-10-25T00:00:00.000Z",
    revoked_at: null,
  },
]

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/settings/api-keys"]}>
        <ApiKeysPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe("ApiKeysPage", () => {
  afterEach(() => {
    cleanup()
  })

  beforeEach(() => {
    vi.restoreAllMocks()
    vi.mocked(toast.add).mockReset()
    agentMocks.credentials.mockReturnValue({
      credentials: savedKeys,
      isLoading: false,
      isError: false,
    })
    agentMocks.create.mockReturnValue({ mutate: vi.fn(), isPending: false })
    agentMocks.rotate.mockReturnValue({ mutate: vi.fn(), isPending: false })
    window.matchMedia = vi.fn().mockImplementation(() => ({
      addEventListener: vi.fn(),
      matches: false,
      removeEventListener: vi.fn(),
    }))
  })

  it("renders one direct key field for every model provider", () => {
    renderPage()

    expect(screen.getByRole("heading", { name: "OpenAI API Key" })).toBeTruthy()
    expect(
      screen.getByRole("heading", { name: "Anthropic API Key" }),
    ).toBeTruthy()
    expect(screen.getByRole("heading", { name: "Google API Key" })).toBeTruthy()
    expect(screen.getByRole("heading", { name: "xAI API Key" })).toBeTruthy()
    expect(
      screen
        .getByLabelText("API Key", { selector: "#openai-api-key" })
        .getAttribute("placeholder"),
    ).toBe("API key saved — enter a new key")
    const openAiInput = screen.getByLabelText("API Key", {
      selector: "#openai-api-key",
    })
    expect(openAiInput.className).toContain("sm:w-80")
    expect(openAiInput.className).toContain("border-transparent")
    expect(openAiInput.className).toContain("bg-black/50")
    expect(openAiInput.className).toContain("focus:border-foreground")
    expect(openAiInput.closest("form")?.className).toContain("p-3")
    expect(
      screen.getAllByText(
        "Press Enter to save. Keys are encrypted and never shown again.",
      ),
    ).toHaveLength(4)
    expect(screen.queryByRole("button", { name: /create api key/i })).toBeNull()
  })

  it("creates the single provider key without a name", async () => {
    const user = userEvent.setup()
    const createMutate = vi.fn()
    agentMocks.create.mockReturnValue({
      mutate: createMutate,
      isPending: false,
    })
    renderPage()

    const input = screen.getByLabelText("API Key", {
      selector: "#google-api-key",
    })
    await user.type(input, "google-key")
    await user.keyboard("{Enter}")

    expect(createMutate).toHaveBeenCalledWith(
      {
        provider: "google",
        kind: "api_key",
        payload: { api_key: "google-key" },
      },
      expect.anything(),
    )
  })

  it("rotates an existing provider key to preserve its agent links", async () => {
    const user = userEvent.setup()
    const rotateMutate = vi.fn()
    agentMocks.rotate.mockReturnValue({
      mutate: rotateMutate,
      isPending: false,
    })
    renderPage()

    const input = screen.getByLabelText("API Key", {
      selector: "#openai-api-key",
    })
    await user.type(input, "replacement-key")
    await user.keyboard("{Enter}")

    expect(rotateMutate).toHaveBeenCalledWith(
      {
        credentialId: "key-1",
        credential: {
          provider: "openai",
          kind: "api_key",
          payload: { api_key: "replacement-key" },
        },
      },
      expect.anything(),
    )
  })

  it("keeps the settings sidebar visible", () => {
    renderPage()

    expect(screen.getByText("Back to app")).toBeTruthy()
    expect(screen.getByText("Integrations")).toBeTruthy()
    expect(screen.queryByText("Projects")).toBeNull()
    expect(screen.queryByText("Agents")).toBeNull()
  })

  it("reports a credential-loading error without hiding the provider fields", () => {
    agentMocks.credentials.mockReturnValue({
      credentials: [],
      isLoading: false,
      isError: true,
    })
    renderPage()

    expect(screen.getByRole("heading", { name: "OpenAI API Key" })).toBeTruthy()
    expect(screen.getByRole("alert").textContent).toContain(
      "Could not load your saved API keys",
    )
  })
})
