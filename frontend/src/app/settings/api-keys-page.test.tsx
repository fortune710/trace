// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { cleanup, render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { ApiKeysPage } from "@/app/settings/api-keys-page"
import { toast } from "@/components/ui/toast"
import { ApiError } from "@/lib/api"

const agentMocks = vi.hoisted(() => ({
  catalog: vi.fn(),
  credentials: vi.fn(),
  create: vi.fn(),
  revoke: vi.fn(),
}))

vi.mock("@/hooks/use-session", () => ({
  useSession: () => ({
    data: { display_name: "Trace User", email: "user@example.test" },
    isPending: false,
  }),
  useLogout: () => ({ isPending: false, mutate: vi.fn() }),
}))

vi.mock("@/hooks/use-agents", () => ({
  useAgentModelCatalog: agentMocks.catalog,
  useProviderCredentials: agentMocks.credentials,
  useCreateProviderCredential: agentMocks.create,
  useRevokeProviderCredential: agentMocks.revoke,
}))

vi.mock("@/components/ui/toast", () => ({
  toast: { add: vi.fn() },
}))

const catalogData = {
  providers: [
    {
      id: "openai",
      label: "OpenAI",
      models: [{ id: "gpt-5.1", label: "GPT-5.1" }],
    },
    {
      id: "anthropic",
      label: "Anthropic",
      models: [{ id: "claude-opus-4-5", label: "Claude Opus 4.5" }],
    },
  ],
}

const savedKeys = [
  {
    id: "key-1",
    provider: "openai",
    kind: "api_key",
    name: "Primary OpenAI key",
    active: true,
    created_at: "2026-10-25T00:00:00.000Z",
    updated_at: "2026-10-25T00:00:00.000Z",
    revoked_at: null,
  },
  {
    id: "key-2",
    provider: "anthropic",
    kind: "api_key",
    name: "Secondary Anthropic key",
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
    agentMocks.catalog.mockReturnValue({
      data: catalogData,
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    })
    agentMocks.credentials.mockReturnValue({
      credentials: savedKeys,
      isLoading: false,
      isError: false,
    })
    agentMocks.create.mockReturnValue({ mutate: vi.fn(), isPending: false })
    agentMocks.revoke.mockReturnValue({ mutate: vi.fn(), isPending: false })
    window.matchMedia = vi.fn().mockImplementation(() => ({
      addEventListener: vi.fn(),
      matches: false,
      removeEventListener: vi.fn(),
    }))
  })

  it("lists saved keys with their names and providers", () => {
    renderPage()

    expect(screen.getByText("Primary OpenAI key")).toBeTruthy()
    expect(screen.getByText("Secondary Anthropic key")).toBeTruthy()
    expect(screen.getByText(/OpenAI · Created/)).toBeTruthy()
    expect(screen.getAllByText("Active")).toHaveLength(2)
  })

  it("switches the sidebar to the settings view", () => {
    renderPage()

    expect(screen.getByText("Back to app")).toBeTruthy()
    expect(screen.getAllByText("API keys").length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText("Integrations")).toBeTruthy()
    expect(screen.queryByText("Projects")).toBeNull()
    expect(screen.queryByText("Agents")).toBeNull()
  })

  it("shows an empty state when no keys exist", () => {
    agentMocks.credentials.mockReturnValue({
      credentials: [],
      isLoading: false,
      isError: false,
    })
    renderPage()

    expect(screen.getByText("No API keys yet")).toBeTruthy()
  })

  it("does not show the empty state when loading saved keys fails", () => {
    agentMocks.credentials.mockReturnValue({
      credentials: [],
      isLoading: false,
      isError: true,
    })
    renderPage()

    expect(screen.queryByText("No API keys yet")).toBeNull()
    expect(screen.getByRole("alert").textContent).toContain(
      "Could not load your saved API keys",
    )
  })

  it("keeps cached keys visible when refreshing them fails", () => {
    agentMocks.credentials.mockReturnValue({
      credentials: savedKeys,
      isLoading: false,
      isError: true,
    })
    renderPage()

    expect(screen.getByText("Primary OpenAI key")).toBeTruthy()
    expect(screen.getByText("Secondary Anthropic key")).toBeTruthy()
    expect(screen.getByRole("alert").textContent).toContain(
      "Could not load your saved API keys",
    )
  })

  it("creates a named key for the chosen provider", async () => {
    const user = userEvent.setup()
    const createMutate = vi.fn()
    agentMocks.create.mockReturnValue({ mutate: createMutate, isPending: false })
    renderPage()

    await user.click(screen.getByRole("button", { name: "Create API key" }))
    const dialog = screen.getByRole("dialog")
    await user.type(within(dialog).getByLabelText("Name"), "Primary OpenAI key")
    await user.click(within(dialog).getByText("Choose provider"))
    await user.click(await screen.findByRole("option", { name: "OpenAI" }))
    await user.type(within(dialog).getByLabelText("API key"), "sk-test-key")
    await user.click(
      within(dialog).getByRole("button", { name: "Create API key" }),
    )

    expect(createMutate).toHaveBeenCalledWith(
      {
        provider: "openai",
        kind: "api_key",
        name: "Primary OpenAI key",
        payload: { api_key: "sk-test-key" },
      },
      expect.anything(),
    )
  })

  it("explains whether saving failed because the key name is already active", async () => {
    const user = userEvent.setup()
    const createMutate = vi.fn((_, callbacks) => {
      callbacks.onError?.(new ApiError(409, { error: { code: "duplicate_name" } }))
    })
    agentMocks.create.mockReturnValue({ mutate: createMutate, isPending: false })
    renderPage()

    await user.click(screen.getByRole("button", { name: "Create API key" }))
    const dialog = screen.getByRole("dialog")
    await user.type(within(dialog).getByLabelText("Name"), "Primary OpenAI key")
    await user.click(within(dialog).getByText("Choose provider"))
    await user.click(await screen.findByRole("option", { name: "OpenAI" }))
    await user.type(within(dialog).getByLabelText("API key"), "sk-test-key")
    await user.click(
      within(dialog).getByRole("button", { name: "Create API key" }),
    )

    expect(toast.add).toHaveBeenCalledWith({
      type: "error",
      title: "Key could not be saved",
      description: "A key with that name already exists. Please try another name.",
    })
  })

  it("shows a general error when saving fails for another reason", async () => {
    const user = userEvent.setup()
    const createMutate = vi.fn((_, callbacks) => {
      callbacks.onError?.(new ApiError(500, { error: { code: "request_failed" } }))
    })
    agentMocks.create.mockReturnValue({ mutate: createMutate, isPending: false })
    renderPage()

    await user.click(screen.getByRole("button", { name: "Create API key" }))
    const dialog = screen.getByRole("dialog")
    await user.type(within(dialog).getByLabelText("Name"), "Primary OpenAI key")
    await user.click(within(dialog).getByText("Choose provider"))
    await user.click(await screen.findByRole("option", { name: "OpenAI" }))
    await user.type(within(dialog).getByLabelText("API key"), "sk-test-key")
    await user.click(
      within(dialog).getByRole("button", { name: "Create API key" }),
    )

    expect(toast.add).toHaveBeenCalledWith({
      type: "error",
      title: "Key could not be saved",
      description: "Your API key could not be saved. Please try again.",
    })
  })

  it("revokes a key from the list", async () => {
    const user = userEvent.setup()
    const revokeMutate = vi.fn()
    agentMocks.revoke.mockReturnValue({ mutate: revokeMutate, isPending: false })
    renderPage()

    const rows = screen.getAllByRole("button", { name: "Revoke" })
    await user.click(rows[0])

    expect(revokeMutate).toHaveBeenCalledWith("key-1", expect.anything())
  })
})
