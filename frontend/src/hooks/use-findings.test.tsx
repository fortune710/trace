// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { renderHook, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { useFindingRemediationPrompt } from "@/hooks/use-findings"
import { remediationsApi, type Remediation } from "@/lib/api"

function remediation(id: string): Remediation {
  return {
    id,
    project_id: "project-a",
    finding_id: "finding-a",
    proposed_diff: "diff --git a/file b/file",
    pull_request: null,
    status: "proposed",
    approved_at: null,
    created_at: "2026-10-27T00:00:00Z",
    updated_at: "2026-10-27T00:00:00Z",
  }
}

function wrapper({ children }: { children: React.ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
}

describe("useFindingRemediationPrompt", () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it("loads the finding remediation before loading its prompt", async () => {
    const listForFinding = vi
      .spyOn(remediationsApi, "listForFinding")
      .mockResolvedValue([remediation("remediation-a")])
    const getPrompt = vi
      .spyOn(remediationsApi, "getPrompt")
      .mockResolvedValue({ prompt_text: "Resolve the finding." })

    const { result } = renderHook(
      () => useFindingRemediationPrompt("finding-a"),
      { wrapper },
    )

    await waitFor(() => {
      expect(result.current.prompt).toBe("Resolve the finding.")
    })
    expect(listForFinding).toHaveBeenCalledWith("finding-a")
    expect(getPrompt).toHaveBeenCalledWith("remediation-a")
  })

  it("uses the empty state without requesting a prompt when no remediation exists", async () => {
    const listForFinding = vi
      .spyOn(remediationsApi, "listForFinding")
      .mockResolvedValue([])
    const getPrompt = vi.spyOn(remediationsApi, "getPrompt")

    const { result } = renderHook(
      () => useFindingRemediationPrompt("finding-a"),
      { wrapper },
    )

    await waitFor(() => {
      expect(result.current.isNoPrompt).toBe(true)
    })
    expect(listForFinding).toHaveBeenCalledWith("finding-a")
    expect(getPrompt).not.toHaveBeenCalled()
  })
})
