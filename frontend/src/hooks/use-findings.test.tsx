// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { renderHook, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import {
  findingsQueryKey,
  useFindingRemediationPrompt,
  useUpdateFindingStatus,
} from "@/hooks/use-findings"
import {
  findingsApi,
  remediationsApi,
  type Finding,
  type FindingPage,
  type Remediation,
} from "@/lib/api"

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

function finding(id: string, reviewId: string, status: Finding["status"]): Finding {
  return {
    id,
    review_id: reviewId,
    agent_id: "agent-a",
    reviewing_agent: {
      assignment_id: "assignment-a",
      agent_id: "agent-a",
      display_name: "Security reviewer",
      specialization: "security",
    },
    category: "security",
    severity: "high",
    title: "Unsafe access",
    explanation: "The access is unsafe.",
    evidence: null,
    source_location: null,
    recommendation: null,
    status,
    created_at: "2026-10-27T00:00:00Z",
    updated_at: "2026-10-27T00:00:00Z",
  }
}

function findingPage(items: Finding[]): FindingPage {
  return { items, next_offset: null }
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

describe("useUpdateFindingStatus", () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it("updates only the finding's review and removes it from a mismatched status page", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    const reviewAFinding = finding("finding-a", "review-a", "open")
    const reviewBFinding = finding("finding-b", "review-b", "accepted")
    const reviewAOpenKey = [
      ...findingsQueryKey,
      "review",
      "review-a",
      1,
      { status: "open" },
    ]
    const reviewBAcceptedKey = [
      ...findingsQueryKey,
      "review",
      "review-b",
      1,
      { status: "accepted" },
    ]
    queryClient.setQueryData(reviewAOpenKey, findingPage([reviewAFinding]))
    queryClient.setQueryData(reviewBAcceptedKey, findingPage([reviewBFinding]))
    vi.spyOn(findingsApi, "updateStatus").mockResolvedValue({
      ...reviewAFinding,
      status: "accepted",
    })

    const queryWrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    )
    const { result } = renderHook(() => useUpdateFindingStatus(), {
      wrapper: queryWrapper,
    })

    await result.current.mutateAsync({
      findingId: reviewAFinding.id,
      status: "accepted",
    })

    expect(queryClient.getQueryData<FindingPage>(reviewAOpenKey)?.items).toEqual(
      [],
    )
    expect(
      queryClient.getQueryData<FindingPage>(reviewBAcceptedKey)?.items,
    ).toEqual([reviewBFinding])
  })
})
