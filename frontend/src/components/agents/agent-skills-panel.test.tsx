// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { cleanup, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { AgentSkillsPanel } from "@/components/agents/agent-skills-panel"
import type { Agent } from "@/lib/api"

const attachSkill = vi.fn()
const detachSkill = vi.fn()

vi.mock("@/hooks/use-agents", () => ({
  useSkillsSearch: (query: string) => ({
    data:
      query.trim().length >= 2
        ? {
            data: [
              {
                id: "vercel-labs/skills/find-skills",
                slug: "find-skills",
                name: "find-skills",
                source: "vercel-labs/skills",
                installs: 100,
              },
            ],
          }
        : undefined,
    isLoading: false,
    isError: false,
  }),
  useCuratedSkills: () => ({
    data: {
      data: [
        {
          id: "supabase/skills/postgres",
          slug: "postgres",
          name: "Postgres",
          source: "supabase/skills",
          installs: 50,
        },
      ],
    },
    isLoading: false,
    isError: false,
  }),
  useAttachAgentSkill: () => ({
    mutate: attachSkill,
    isPending: false,
  }),
  useDetachAgentSkill: () => ({
    mutate: detachSkill,
    isPending: false,
  }),
}))

vi.mock("@/components/ui/toast", () => ({
  toast: { add: vi.fn() },
}))

const agent: Agent = {
  id: "11111111-1111-1111-1111-111111111111",
  name: "Security",
  personality: null,
  review_category: "security",
  model_provider: "openai",
  model_name: "gpt-5.1",
  avatar: null,
  skills: [],
  credential_id: null,
  configuration_version: 1,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  disabled_at: null,
}

function renderPanel(override: Partial<Agent> = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <AgentSkillsPanel agent={{ ...agent, ...override }} disabled={false} />
    </QueryClientProvider>,
  )
}

describe("AgentSkillsPanel", () => {
  beforeEach(() => {
    attachSkill.mockReset()
    detachSkill.mockReset()
  })

  afterEach(() => {
    cleanup()
  })

  it("opens the skills dialog and attaches a catalog skill", async () => {
    const user = userEvent.setup()
    renderPanel()

    await user.click(screen.getByRole("button", { name: /no skills configured/i }))
    expect(screen.getByText("Postgres")).toBeTruthy()

    await user.type(screen.getByLabelText(/search skills/i), "find")
    expect(await screen.findByText("find-skills")).toBeTruthy()

    await user.click(screen.getByRole("button", { name: "Add" }))
    expect(attachSkill).toHaveBeenCalledWith(
      "vercel-labs/skills/find-skills",
      expect.any(Object),
    )
  })

  it("lists attached skills and supports removal", async () => {
    const user = userEvent.setup()
    renderPanel({
      skills: [
        {
          provider: "skills.sh",
          id: "vercel-labs/skills/find-skills",
          name: "find-skills",
          source: "vercel-labs/skills",
        },
      ],
    })

    expect(screen.getByRole("heading", { name: "find-skills" })).toBeTruthy()
    await user.click(screen.getByRole("button", { name: /remove find-skills/i }))
    expect(detachSkill).toHaveBeenCalledWith(
      "vercel-labs/skills/find-skills",
      expect.any(Object),
    )
  })
})
