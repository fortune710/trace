// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { AgentDialog } from "@/components/agents/agent-dialog"
import type { Agent, AgentModelCatalog } from "@/lib/api"

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

describe("AgentDialog personality", () => {
  afterEach(cleanup)

  it("fills the category template when creating an agent", () => {
    renderDialog(null)

    expect(personalityField().value).toBe("Security template.")
    expect(screen.getByText(/starts from the security template/i)).toBeTruthy()
  })

  it("keeps an edited personality and offers to restore the default", () => {
    renderDialog(null)

    fireEvent.change(personalityField(), { target: { value: "Edited." } })

    expect(personalityField().value).toBe("Edited.")

    fireEvent.click(screen.getByRole("button", { name: "Use category default" }))

    expect(personalityField().value).toBe("Security template.")
  })

  it("does not overwrite the personality of an existing agent", () => {
    renderDialog(existingAgent)

    expect(personalityField().value).toBe("My own instructions.")
    expect(
      screen.getByRole("button", { name: "Use category default" }),
    ).toBeTruthy()
  })
})
