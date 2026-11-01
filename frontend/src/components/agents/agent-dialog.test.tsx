// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { AgentDialog } from "@/components/agents/agent-dialog"
import { agentsApi, type Agent, type AgentModelCatalog } from "@/lib/api"

const catalog: AgentModelCatalog = {
  providers: [
    {
      id: "openai",
      label: "OpenAI",
      models: [{ id: "gpt-5.1", label: "GPT-5.1" }],
    },
  ],
  categories: [
    {
      id: "security",
      label: "Security",
      default_personality: "Security template.",
    },
    {
      id: "legal",
      label: "Legal",
      default_personality: "Legal template.",
    },
  ],
}

const existingAgent: Agent = {
  id: "agent-1",
  name: "Custom reviewer",
  personality: "My own instructions.",
  review_category: "security",
  model_provider: "openai",
  model_name: "gpt-5.1",
  avatar: null,
  skills: [],
  credential_id: null,
  configuration_version: 1,
  created_at: "2026-10-17T00:00:00Z",
  updated_at: "2026-10-17T00:00:00Z",
  disabled_at: null,
}

function renderDialog(agent: Agent | null) {
  const client = new QueryClient()

  return render(
    <QueryClientProvider client={client}>
      <AgentDialog
        agent={agent}
        catalog={catalog}
        credentials={[]}
        open
        onOpenChange={vi.fn()}
      />
    </QueryClientProvider>,
  )
}

function personalityField() {
  return screen.getByLabelText(/personality/i) as HTMLTextAreaElement
}

async function chooseCategory(
  user: ReturnType<typeof userEvent.setup>,
  label: string,
) {
  await user.click(screen.getByRole("combobox", { name: /review category/i }))
  await user.click(await screen.findByRole("option", { name: label }))
}

describe("AgentDialog avatar", () => {
  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
  })

  it("has no avatar field and leaves an existing avatar untouched on save", async () => {
    const user = userEvent.setup()
    const update = vi.spyOn(agentsApi, "update").mockResolvedValue({
      ...existingAgent,
      avatar: "agent-defaults/example",
    })
    renderDialog({ ...existingAgent, avatar: "agent-defaults/example" })

    expect(screen.queryByLabelText(/avatar/i)).toBeNull()

    await user.click(screen.getByRole("button", { name: "Save changes" }))

    await vi.waitFor(() => expect(update).toHaveBeenCalledTimes(1))
    expect(update.mock.calls[0][1]).not.toHaveProperty("avatar")
  })
})

describe("AgentDialog personality", () => {
  afterEach(cleanup)

  it("asks for the category first and keeps the personality disabled", () => {
    renderDialog(null)

    const labels = screen
      .getAllByText(/review category|personality/i, { selector: "label" })
      .map((label) => label.textContent?.toLowerCase() ?? "")

    expect(labels[0]).toContain("review category")
    expect(labels[1]).toContain("personality")
    expect(personalityField().disabled).toBe(true)
    expect(personalityField().value).toBe("")
    expect(
      screen.getByText(/choose a review category to fill in/i),
    ).toBeTruthy()
  })

  it("fills the category template once a category is chosen", async () => {
    const user = userEvent.setup()
    renderDialog(null)

    await chooseCategory(user, "Legal")

    expect(personalityField().disabled).toBe(false)
    expect(personalityField().value).toBe("Legal template.")
    expect(screen.getByText(/starts from the legal template/i)).toBeTruthy()
  })

  it("follows the category until the personality is edited", async () => {
    const user = userEvent.setup()
    renderDialog(null)

    await chooseCategory(user, "Security")
    await chooseCategory(user, "Legal")

    expect(personalityField().value).toBe("Legal template.")

    fireEvent.change(personalityField(), { target: { value: "Edited." } })
    await chooseCategory(user, "Security")

    expect(personalityField().value).toBe("Edited.")

    fireEvent.click(screen.getByRole("button", { name: "Use category default" }))

    expect(personalityField().value).toBe("Security template.")
  })

  it("does not overwrite the personality of an existing agent", () => {
    renderDialog(existingAgent)

    expect(personalityField().disabled).toBe(false)
    expect(personalityField().value).toBe("My own instructions.")
    expect(
      screen.getByRole("button", { name: "Use category default" }),
    ).toBeTruthy()
  })

  it("still renders when the catalog has no categories", () => {
    const client = new QueryClient()

    render(
      <QueryClientProvider client={client}>
        <AgentDialog
          agent={null}
          catalog={{ providers: catalog.providers } as AgentModelCatalog}
          credentials={[]}
          open
          onOpenChange={vi.fn()}
        />
      </QueryClientProvider>,
    )

    expect(personalityField().disabled).toBe(true)
  })
})
