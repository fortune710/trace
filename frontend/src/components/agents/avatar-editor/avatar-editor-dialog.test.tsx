// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { cleanup, render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { AvatarEditorDialog } from "@/components/agents/avatar-editor/avatar-editor-dialog"
import type { Agent, AvatarConfig } from "@/lib/api"

vi.mock("@/components/agents/avatar-editor/render-avatar-png", () => ({
  renderAvatarPng: vi.fn(async () => new Blob(["png"], { type: "image/png" })),
}))

const savedConfig: AvatarConfig = {
  eyes: "variant02",
  brows: "variant03",
  nose: "variant04",
  lips: "variant05",
  hair: "variant06",
  body: "variant07",
  backgroundColor: "#bfe0ff",
  flip: false,
}

const agent: Agent = {
  id: "agent-1",
  name: "Security Scout",
  personality: null,
  review_category: "security",
  model_provider: "openai",
  model_name: "gpt-5.1",
  avatar: null,
  avatar_config: savedConfig,
  skills: [],
  credential_id: null,
  configuration_version: 1,
  created_at: "2026-10-17T00:00:00Z",
  updated_at: "2026-10-17T00:00:00Z",
  disabled_at: null,
}

function renderEditor(
  overrides: Partial<Agent> = {},
  onOpenChange = vi.fn(),
) {
  const client = new QueryClient({
    defaultOptions: { mutations: { retry: false } },
  })

  render(
    <QueryClientProvider client={client}>
      <AvatarEditorDialog
        agent={{ ...agent, ...overrides }}
        open
        onOpenChange={onOpenChange}
      />
    </QueryClientProvider>,
  )

  return onOpenChange
}

function previewSource() {
  return (screen.getByAltText("Avatar preview") as HTMLImageElement).src
}

async function waitForEngine() {
  await screen.findByAltText("Avatar preview", {}, { timeout: 5000 })
}

describe("AvatarEditorDialog", () => {
  const fetchMock = vi.fn()

  beforeEach(() => {
    document.cookie = "trace_csrf=editor-token"
    fetchMock.mockReset()
    vi.stubGlobal("fetch", fetchMock)
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    document.cookie = "trace_csrf=; Max-Age=0"
  })

  it("opens on the saved config with the first category selected", async () => {
    renderEditor()
    await waitForEngine()

    expect(
      screen.getByRole("tab", { name: "Eyes" }).getAttribute("aria-selected"),
    ).toBe("true")
    const eyes = screen.getByRole("radiogroup", { name: "Eyes" })
    expect(
      within(eyes)
        .getByRole("radio", { name: "Eyes 2" })
        .getAttribute("aria-checked"),
    ).toBe("true")
    expect(within(eyes).getAllByRole("radio")).toHaveLength(5)
  })

  it("opens on a random config when the agent has none", async () => {
    renderEditor({ avatar_config: null })
    await waitForEngine()

    const eyes = screen.getByRole("radiogroup", { name: "Eyes" })
    expect(
      within(eyes)
        .getAllByRole("radio")
        .filter((radio) => radio.getAttribute("aria-checked") === "true"),
    ).toHaveLength(1)
  })

  it("lists every part category as an accessible tab", async () => {
    renderEditor()
    await waitForEngine()

    const labels = screen
      .getAllByRole("tab")
      .map((tab) => tab.textContent)

    expect(labels).toEqual([
      "Eyes",
      "Brows",
      "Nose",
      "Mouth",
      "Hair",
      "Glasses",
      "Beard",
      "Outfit",
      "Background",
    ])
  })

  it("updates the preview when an option is picked", async () => {
    const user = userEvent.setup()
    renderEditor()
    await waitForEngine()
    const before = previewSource()

    await user.click(screen.getByRole("tab", { name: "Hair" }))
    await user.click(
      within(screen.getByRole("radiogroup", { name: "Hair" })).getByRole(
        "radio",
        { name: "Hair 12" },
      ),
    )

    expect(
      screen
        .getByRole("radio", { name: "Hair 12" })
        .getAttribute("aria-checked"),
    ).toBe("true")
    expect(previewSource()).not.toBe(before)
  })

  it("lets optional parts be switched off", async () => {
    const user = userEvent.setup()
    renderEditor({ avatar_config: { ...savedConfig, glasses: "variant03" } })
    await waitForEngine()

    await user.click(screen.getByRole("tab", { name: "Glasses" }))
    expect(
      screen
        .getByRole("radio", { name: "Glasses 3" })
        .getAttribute("aria-checked"),
    ).toBe("true")

    await user.click(screen.getByRole("radio", { name: "No glasses" }))

    expect(
      screen
        .getByRole("radio", { name: "No glasses" })
        .getAttribute("aria-checked"),
    ).toBe("true")
  })

  it("randomizes the avatar", async () => {
    const user = userEvent.setup()
    vi.spyOn(Math, "random").mockReturnValue(0.9)
    renderEditor()
    await waitForEngine()
    const before = previewSource()

    await user.click(screen.getByRole("button", { name: "Randomize" }))

    expect(previewSource()).not.toBe(before)
  })

  it("saves a PNG and the config as multipart form data", async () => {
    const user = userEvent.setup()
    const onOpenChange = renderEditor()
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          ...agent,
          avatar: "/api/v1/agents/agent-1/avatar?v=abc",
        }),
        { status: 200 },
      ),
    )
    await waitForEngine()

    await user.click(screen.getByRole("tab", { name: "Hair" }))
    await user.click(screen.getByRole("radio", { name: "Hair 12" }))
    await user.click(screen.getByRole("button", { name: "Save avatar" }))

    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "http://localhost:8000/api/v1/agents/agent-1/avatar",
    )
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit
    expect(init.method).toBe("POST")
    expect(init.body).toBeInstanceOf(FormData)
    const headers = new Headers(init.headers)
    expect(headers.get("Content-Type")).toBeNull()
    expect(headers.get("X-CSRF-Token")).toBe("editor-token")
    const body = init.body as FormData
    expect(body.get("file")).toBeInstanceOf(Blob)
    expect(JSON.parse(String(body.get("config")))).toEqual({
      ...savedConfig,
      hair: "variant12",
    })
    await vi.waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false))
  })

  it("keeps the dialog open and does not close when the upload fails", async () => {
    const user = userEvent.setup()
    const onOpenChange = renderEditor()
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ detail: "bad" }), { status: 422 }),
    )
    await waitForEngine()

    await user.click(screen.getByRole("button", { name: "Save avatar" }))

    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    await vi.waitFor(() =>
      expect(
        (screen.getByRole("button", { name: "Save avatar" }) as HTMLButtonElement)
          .disabled,
      ).toBe(false),
    )
    expect(onOpenChange).not.toHaveBeenCalledWith(false)
  })

  it("hides removal when the agent has no avatar", async () => {
    renderEditor()
    await waitForEngine()

    expect(screen.queryByRole("button", { name: "Remove avatar" })).toBeNull()
  })

  it("removes an existing avatar", async () => {
    const user = userEvent.setup()
    const onOpenChange = renderEditor({
      avatar: "/api/v1/agents/agent-1/avatar?v=abc",
    })
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }))
    await waitForEngine()

    await user.click(screen.getByRole("button", { name: "Remove avatar" }))

    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "http://localhost:8000/api/v1/agents/agent-1/avatar",
    )
    expect((fetchMock.mock.calls[0]?.[1] as RequestInit).method).toBe("DELETE")
    await vi.waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false))
  })
})
