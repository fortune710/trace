// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { CodingAgentPrompt } from "@/components/findings/coding-agent-prompt"
import { toast } from "@/components/ui/toast"
import { useFindingRemediationPrompt } from "@/hooks/use-findings"

vi.mock("@/hooks/use-findings", () => ({
  useFindingRemediationPrompt: vi.fn(),
}))
vi.mock("@/components/ui/toast", () => ({
  toast: { add: vi.fn() },
}))

const mockedUseFindingRemediationPrompt = vi.mocked(useFindingRemediationPrompt)
const promptText = "Resolve the authorization issue without changing unrelated files."
const originalClipboard = Object.getOwnPropertyDescriptor(
  window.navigator,
  "clipboard",
)

function setClipboard(writeText: ReturnType<typeof vi.fn>) {
  Object.defineProperty(window.navigator, "clipboard", {
    configurable: true,
    value: { writeText },
  })
}

describe("CodingAgentPrompt", () => {
  beforeEach(() => {
    mockedUseFindingRemediationPrompt.mockReturnValue({
      prompt: promptText,
      isLoading: false,
      isError: false,
      isNoPrompt: false,
      refetch: vi.fn(),
    })
  })

  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
    if (originalClipboard) {
      Object.defineProperty(window.navigator, "clipboard", originalClipboard)
    } else {
      Reflect.deleteProperty(window.navigator, "clipboard")
    }
  })

  it("copies the prompt and shows feedback without exposing its content in a toast", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    setClipboard(writeText)

    render(<CodingAgentPrompt findingId="finding-a" />)
    fireEvent.click(screen.getByRole("button", { name: "Copy prompt" }))

    await waitFor(() => expect(writeText).toHaveBeenCalledWith(promptText))
    expect(toast.add).toHaveBeenCalledWith({
      type: "success",
      title: "Prompt copied",
      description: "Paste it into your coding agent.",
    })
    expect(String(vi.mocked(toast.add).mock.calls)).not.toContain(promptText)
  })

  it("exposes the copy button to keyboard navigation", async () => {
    const user = userEvent.setup()

    render(<CodingAgentPrompt findingId="finding-a" />)
    await user.tab()
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: "Copy prompt" }),
    )
  })

  it("selects the prompt and provides manual-copy guidance when clipboard access fails", async () => {
    const writeText = vi.fn().mockRejectedValue(new Error("permission_denied"))
    setClipboard(writeText)

    render(<CodingAgentPrompt findingId="finding-a" />)
    fireEvent.click(screen.getByRole("button", { name: "Copy prompt" }))

    expect(
      await screen.findByText(
        "Clipboard access is unavailable. The prompt is selected so you can copy it manually.",
      ),
    ).toBeTruthy()
    expect(document.getSelection()?.toString()).toBe(promptText)
    expect(toast.add).not.toHaveBeenCalled()
  })

  it("uses the shared empty state when the finding has no prompt", () => {
    mockedUseFindingRemediationPrompt.mockReturnValue({
      prompt: null,
      isLoading: false,
      isError: false,
      isNoPrompt: true,
      refetch: vi.fn(),
    })

    render(<CodingAgentPrompt findingId="finding-a" />)

    expect(screen.getByText("No coding-agent prompt available")).toBeTruthy()
    expect(document.querySelector("[data-slot=empty]")).toBeTruthy()
  })

  it("renders retry UI for prompt load errors", async () => {
    const refetch = vi.fn()
    mockedUseFindingRemediationPrompt.mockReturnValue({
      prompt: null,
      isLoading: false,
      isError: true,
      isNoPrompt: false,
      refetch,
    })
    const user = userEvent.setup()

    render(<CodingAgentPrompt findingId="finding-a" />)
    await user.click(screen.getByRole("button", { name: "Try again" }))

    expect(refetch).toHaveBeenCalledTimes(1)
  })
})
