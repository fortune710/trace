// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { AgentAvatar } from "@/components/agents/agent-avatar"
import { resolveAgentAvatarUrl } from "@/components/agents/agent-avatar-utils"

class LoadingImage {
  onload: (() => void) | null = null
  onerror: (() => void) | null = null
  referrerPolicy = ""
  crossOrigin: string | null = null

  set src(_value: string) {
    queueMicrotask(() => this.onload?.())
  }
}

describe("resolveAgentAvatarUrl", () => {
  it("resolves uploaded relative paths against the API base URL", () => {
    expect(resolveAgentAvatarUrl("/api/v1/agents/agent-1/avatar?v=abc123")).toBe(
      "http://localhost:8000/api/v1/agents/agent-1/avatar?v=abc123",
    )
  })

  it("keeps absolute http(s) URLs as they are", () => {
    expect(resolveAgentAvatarUrl("https://cdn.example.com/a.png")).toBe(
      "https://cdn.example.com/a.png",
    )
  })

  it("ignores empty values and opaque seeded keys", () => {
    expect(resolveAgentAvatarUrl(null)).toBeUndefined()
    expect(resolveAgentAvatarUrl("")).toBeUndefined()
    expect(resolveAgentAvatarUrl("agent-defaults/scout")).toBeUndefined()
    expect(resolveAgentAvatarUrl("javascript:alert(1)")).toBeUndefined()
  })
})

describe("AgentAvatar", () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it("falls back to initials when there is no avatar", () => {
    render(<AgentAvatar agent={{ name: "Security Scout", avatar: null }} />)

    expect(screen.getByText("SS")).toBeTruthy()
  })

  it("falls back to initials for unknown seeded keys", () => {
    render(
      <AgentAvatar
        agent={{ name: "Legal Eagle", avatar: "agent-defaults/eagle" }}
      />,
    )

    expect(screen.getByText("LE")).toBeTruthy()
    expect(document.querySelector("img")).toBeNull()
  })

  it("falls back to the bot icon when the name has no initials", () => {
    const { container } = render(
      <AgentAvatar agent={{ name: "", avatar: null }} />,
    )

    expect(container.querySelector("svg")).not.toBeNull()
  })

  it("shows the uploaded image from the API base URL", async () => {
    vi.stubGlobal("Image", LoadingImage)
    render(
      <AgentAvatar
        agent={{
          name: "Security Scout",
          avatar: "/api/v1/agents/agent-1/avatar?v=abc123",
        }}
      />,
    )

    const image = await vi.waitFor(() => {
      const found = document.querySelector("img")
      expect(found).not.toBeNull()
      return found as HTMLImageElement
    })
    expect(image.getAttribute("src")).toBe(
      "http://localhost:8000/api/v1/agents/agent-1/avatar?v=abc123",
    )
  })
})
