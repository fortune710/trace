// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ComponentProps } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { ReviewSubmissionDialog } from "@/components/reviews/review-submission-dialog"
import { toast } from "@/components/ui/toast"
import { useCreateReview } from "@/hooks/use-reviews"
import { agentsApi, type Agent, type Project } from "@/lib/api"

vi.mock("@/hooks/use-reviews", () => ({ useCreateReview: vi.fn() }))
vi.mock("@/lib/api", () => ({
  agentsApi: { list: vi.fn() },
}))
vi.mock("@/components/ui/toast", () => ({
  toast: { add: vi.fn() },
}))

const mockedUseCreateReview = vi.mocked(useCreateReview)
const mockedListAgents = vi.mocked(agentsApi.list)

const activeAgent: Agent = {
  id: "agent-active",
  name: "Security Scout",
  personality: null,
  review_category: "security",
  model_provider: "openai",
  model_name: "gpt-5.1",
  avatar: null,
  skills: [],
  credential_id: null,
  configuration_version: 1,
  created_at: "2026-10-21T00:00:00Z",
  updated_at: "2026-10-21T00:00:00Z",
  disabled_at: null,
}

const project: Project = {
  id: "project-a",
  name: "Trace",
  source: "github",
  external_repository_id: "123",
  external_repository_connection_id: "connection-a",
  repository_owner: "fortune710",
  repository_name: "trace",
  branch_name: "main",
  repository_visibility: "private",
  imported_at: null,
  source_hash: null,
  current_revision: "a".repeat(40),
  category: "productivity",
  auto_create_pull_requests: false,
  created_at: "2026-10-21T00:00:00Z",
  updated_at: "2026-10-21T00:00:00Z",
  archived_at: null,
}

function renderDialog(overrides: Partial<ComponentProps<typeof ReviewSubmissionDialog>> = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const props: ComponentProps<typeof ReviewSubmissionDialog> = {
    open: true,
    project,
    onOpenChange: vi.fn(),
    onCreated: vi.fn(),
    ...overrides,
  }

  return {
    ...render(
      <QueryClientProvider client={queryClient}>
        <ReviewSubmissionDialog {...props} />
      </QueryClientProvider>,
    ),
    props,
  }
}

describe("ReviewSubmissionDialog", () => {
  beforeEach(() => {
    vi.resetAllMocks()
    mockedUseCreateReview.mockReturnValue({
      isPending: false,
      mutate: vi.fn(),
    } as unknown as ReturnType<typeof useCreateReview>)
  })

  afterEach(cleanup)

  it("lists and submits exactly the selected enabled agents", async () => {
    const mutate = vi.fn((_, callbacks) => callbacks.onSuccess?.({ id: "review-a" }))
    mockedUseCreateReview.mockReturnValue({
      isPending: false,
      mutate,
    } as unknown as ReturnType<typeof useCreateReview>)
    mockedListAgents.mockResolvedValue({
      items: [activeAgent, { ...activeAgent, id: "agent-disabled", name: "Archived", disabled_at: "2026-10-21T01:00:00Z" }],
      next_offset: null,
    })
    const { props } = renderDialog()

    await screen.findByRole("checkbox", { name: /security scout/i })
    expect(screen.queryByRole("checkbox", { name: /archived/i })).toBeNull()
    expect(mockedListAgents).toHaveBeenCalledWith({
      page: 1,
      pageSize: 100,
      includeDisabled: false,
    })

    fireEvent.click(screen.getByRole("checkbox", { name: /security scout/i }))
    fireEvent.click(screen.getByRole("button", { name: "Start review" }))

    expect(mutate).toHaveBeenCalledWith(
      { project, agentIds: ["agent-active"] },
      expect.any(Object),
    )
    expect(props.onCreated).toHaveBeenCalledWith("review-a")
    expect(props.onOpenChange).toHaveBeenCalledWith(false)
  })

  it("explains when no enabled agents are available", async () => {
    mockedListAgents.mockResolvedValue({ items: [], next_offset: null })
    renderDialog()

    expect(await screen.findByText(/create and enable at least one agent/i)).toBeTruthy()
    expect(screen.getByRole("button", { name: "Start review" })).toHaveProperty("disabled", true)
  })

  it("dismisses the dialog while the review request is pending", async () => {
    mockedListAgents.mockResolvedValue({ items: [activeAgent], next_offset: null })
    const mutate = vi.fn()
    mockedUseCreateReview.mockReturnValue({
      isPending: false,
      mutate,
    } as unknown as ReturnType<typeof useCreateReview>)
    const { props } = renderDialog()

    await screen.findByRole("checkbox", { name: /security scout/i })
    fireEvent.click(screen.getByRole("checkbox", { name: /security scout/i }))
    fireEvent.click(screen.getByRole("button", { name: "Start review" }))

    expect(mutate).toHaveBeenCalledOnce()
    expect(props.onOpenChange).toHaveBeenCalledWith(false)
    expect(props.onCreated).not.toHaveBeenCalled()
    expect(toast.add).not.toHaveBeenCalled()
  })

  it("shows a path-free failure message when submission fails", async () => {
    mockedListAgents.mockResolvedValue({ items: [activeAgent], next_offset: null })
    const mutate = vi.fn((_, callbacks) => callbacks.onError?.(new Error("/private/path")))
    mockedUseCreateReview.mockReturnValue({
      isPending: false,
      mutate,
    } as unknown as ReturnType<typeof useCreateReview>)
    renderDialog()

    await screen.findByRole("checkbox", { name: /security scout/i })
    fireEvent.click(screen.getByRole("checkbox", { name: /security scout/i }))
    fireEvent.click(screen.getByRole("button", { name: "Start review" }))

    await waitFor(() => expect(mutate).toHaveBeenCalled())
    expect(toast.add).toHaveBeenCalledWith({
      type: "error",
      title: "Review could not be started",
      description: "The source could not be captured or the review request was rejected. Try again.",
    })
  })

  it("explains when GitHub authorization prevents review submission", async () => {
    mockedListAgents.mockResolvedValue({ items: [activeAgent], next_offset: null })
    const error = Object.assign(new Error("GitHub authorization is required"), {
      code: "github_authorization_required",
    })
    const mutate = vi.fn((_, callbacks) => callbacks.onError?.(error))
    mockedUseCreateReview.mockReturnValue({
      isPending: false,
      mutate,
    } as unknown as ReturnType<typeof useCreateReview>)
    const { props } = renderDialog()

    await screen.findByRole("checkbox", { name: /security scout/i })
    fireEvent.click(screen.getByRole("checkbox", { name: /security scout/i }))
    fireEvent.click(screen.getByRole("button", { name: "Start review" }))

    expect(props.onOpenChange).toHaveBeenCalledWith(false)
    expect(toast.add).toHaveBeenCalledWith({
      type: "error",
      title: "Review could not be started",
      description: "GitHub access is unavailable. Reconnect GitHub in Settings → Integrations and confirm access to this repository before trying again.",
    })
  })
})
