// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { renderHook, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import {
  findingsQueryKey,
  useApplyLocalRemediation,
  useFindingRemediationPrompt,
  useUpdateFindingStatus,
} from "@/hooks/use-findings"
import { useRuntimeEnvironment } from "@/hooks/use-runtime-environment"
import { useSession } from "@/hooks/use-session"
import {
  findingsApi,
  remediationsApi,
  type Finding,
  type FindingPage,
  type Remediation,
} from "@/lib/api"
import {
  applyLocalRemediation,
  restoreLocalRemediation,
} from "@/lib/local-source-snapshot"
import { getLocalProjectsDatabase } from "@/lib/local-projects-database"
import { desktopTelemetry } from "@/lib/desktop-telemetry"

vi.mock("@/hooks/use-runtime-environment", () => ({
  useRuntimeEnvironment: vi.fn(),
}))
vi.mock("@/hooks/use-session", () => ({ useSession: vi.fn() }))
vi.mock("@/lib/local-projects-database", () => ({
  getLocalProjectsDatabase: vi.fn(),
}))
vi.mock("@/lib/local-source-snapshot", () => ({
  applyLocalRemediation: vi.fn(),
  restoreLocalRemediation: vi.fn(),
}))
vi.mock("@/lib/desktop-telemetry", () => ({
  desktopTelemetry: { record: vi.fn().mockResolvedValue(undefined) },
}))

const mockedRuntime = vi.mocked(useRuntimeEnvironment)
const mockedSession = vi.mocked(useSession)
const mockedDatabase = vi.mocked(getLocalProjectsDatabase)
const mockedApply = vi.mocked(applyLocalRemediation)
const mockedRestore = vi.mocked(restoreLocalRemediation)
const mockedTelemetry = vi.mocked(desktopTelemetry.record)
const executablePatch = {
  diff: "diff --git a/file b/file",
  sha256: "a".repeat(64),
  source_snapshot: { source_kind: "local", source_identifier: "source", revision: "b".repeat(64) },
  files: [],
  warnings: [],
}

beforeEach(() => {
  vi.spyOn(remediationsApi, "getPatch").mockResolvedValue(executablePatch)
})

function remediation(id: string): Remediation {
  return {
    id,
    project_id: "project-a",
    finding_id: "finding-a",
    proposed_diff: "diff --git a/file b/file",
    generation_status: "ready",
    generation_failure: null,
    patch_available: true,
    preview_is_redacted: true,
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
    mockedTelemetry.mockClear()
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

describe("useApplyLocalRemediation", () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it("applies locally, then records every returned file with the API", async () => {
    mockedRuntime.mockReturnValue({ kind: "tauri", isTauri: true, isWeb: false })
    mockedSession.mockReturnValue({
      data: { user_id: "account-a" },
    } as ReturnType<typeof useSession>)
    mockedDatabase.mockResolvedValue({
      getByApiProjectId: vi.fn().mockResolvedValue({
        source: {
          kind: "local",
          availability: "available",
          canonicalPath: "/private/project",
        },
      }),
    } as never)
    const files = [
      {
        filePath: "src/example.ts",
        backupReference: "local-remediation-backups/remediation-a/src/example.ts",
        sourceHash: "a".repeat(64),
        appliedHash: "b".repeat(64),
      },
    ]
    mockedApply.mockResolvedValue({ files })
    const complete = vi
      .spyOn(remediationsApi, "completeLocalApply")
      .mockResolvedValue({ ...remediation("remediation-a"), status: "applied" })

    const { result } = renderHook(() => useApplyLocalRemediation("finding-a"), {
      wrapper,
    })
    await result.current.mutateAsync(remediation("remediation-a"))

    expect(mockedApply).toHaveBeenCalledWith(
      "/private/project",
      "remediation-a",
      executablePatch,
    )
    expect(complete).toHaveBeenCalledWith("remediation-a", {
      files: [
        {
          file_path: "src/example.ts",
          backup_reference: "local-remediation-backups/remediation-a/src/example.ts",
          source_hash: "a".repeat(64),
          applied_hash: "b".repeat(64),
        },
      ],
    })
    expect(mockedRestore).not.toHaveBeenCalled()
    expect(mockedTelemetry).toHaveBeenCalledWith({
      event: "local_remediation.apply.started",
      userId: "account-a",
    })
    expect(mockedTelemetry).toHaveBeenCalledWith({
      event: "local_remediation.record.succeeded",
      userId: "account-a",
    })
  })

  it("restores local files when completion cannot be recorded", async () => {
    mockedRuntime.mockReturnValue({ kind: "tauri", isTauri: true, isWeb: false })
    mockedSession.mockReturnValue({
      data: { user_id: "account-a" },
    } as ReturnType<typeof useSession>)
    mockedDatabase.mockResolvedValue({
      getByApiProjectId: vi.fn().mockResolvedValue({
        source: {
          kind: "local",
          availability: "available",
          canonicalPath: "/private/project",
        },
      }),
    } as never)
    const files = [
      {
        filePath: "src/example.ts",
        backupReference: "local-remediation-backups/remediation-a/src/example.ts",
        sourceHash: "a".repeat(64),
        appliedHash: "b".repeat(64),
      },
    ]
    mockedApply.mockResolvedValue({ files })
    mockedRestore.mockResolvedValue()
    vi.spyOn(remediationsApi, "completeLocalApply").mockRejectedValue(
      new Error("offline"),
    )

    const { result } = renderHook(() => useApplyLocalRemediation("finding-a"), {
      wrapper,
    })
    await expect(result.current.mutateAsync(remediation("remediation-a"))).rejects.toThrow(
      "offline",
    )
    expect(mockedRestore).toHaveBeenCalledWith(
      "/private/project",
      "remediation-a",
      files,
    )
    expect(mockedTelemetry).toHaveBeenCalledWith({
      event: "local_remediation.restore.succeeded",
      userId: "account-a",
    })
  })
})
