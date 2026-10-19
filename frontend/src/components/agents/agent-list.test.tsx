// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { MemoryRouter } from "react-router-dom"

import { AgentList } from "@/components/agents/agent-list"
import type { Agent } from "@/lib/api"

const activeAgent: Agent = {
  id: "active-agent",
  name: "Security Scout",
  personality: "Find security risks.",
  review_category: "security",
  model_provider: "openai",
  model_name: "gpt-5.1",
  avatar: null,
  skills: ["auth", { id: { value: "structured-skill" } }],
  credential_id: null,
  created_at: "2026-10-17T00:00:00Z",
  updated_at: "2026-10-17T00:00:00Z",
  disabled_at: null,
}

function renderList(agent: Agent) {
  return render(<MemoryRouter><AgentList agents={[agent]} onCreate={vi.fn()} /></MemoryRouter>)
}

describe("AgentList", () => {
  afterEach(cleanup)

  it("shows summary metadata and links to the agent details page", () => {
    renderList(activeAgent)

    expect(screen.getByText("Security Scout")).toBeTruthy()
    expect(screen.getByText("Security")).toBeTruthy()
    expect(screen.getByText("openai/gpt-5.1")).toBeTruthy()
    expect(screen.getByText("auth · 1 configured skill")).toBeTruthy()
    expect(screen.getByRole("link", { name: /security scout/i }).getAttribute("href")).toBe("/agents/active-agent")
    expect(screen.queryByText("Access")).toBeNull()
    expect(screen.queryByText("Trace-managed")).toBeNull()
    expect(screen.queryByText("Find security risks.")).toBeNull()
    expect(screen.queryByText(/security reviewer/i)).toBeNull()
    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull()
    expect(screen.queryByRole("button", { name: "Disable" })).toBeNull()
  })

  it("keeps disabled agents visible and links to their read-only details", () => {
    renderList({ ...activeAgent, id: "disabled-agent", disabled_at: "2026-10-17T01:00:00Z" })

    expect(screen.getByText("Disabled")).toBeTruthy()
    expect(screen.getByRole("link", { name: /security scout/i }).getAttribute("href")).toBe("/agents/disabled-agent")
  })
})
