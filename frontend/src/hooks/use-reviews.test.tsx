// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, renderHook, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { useCreateReview, useProjectReviews } from "@/hooks/use-reviews"
import { useRuntimeEnvironment } from "@/hooks/use-runtime-environment"
import { useSession } from "@/hooks/use-session"
import { projectsApi, reviewsApi, type Project, type Review } from "@/lib/api"
import type { DesktopProjectRecord } from "@/lib/desktop-projects"
import { getLocalProjectsDatabase } from "@/lib/local-projects-database"
import {
  createLocalReviewSnapshot,
  localSourceIdentityHash,
} from "@/lib/local-source-snapshot"

vi.mock("@/hooks/use-runtime-environment", () => ({ useRuntimeEnvironment: vi.fn() }))
vi.mock("@/hooks/use-session", () => ({ useSession: vi.fn() }))
vi.mock("@/lib/local-projects-database", () => ({ getLocalProjectsDatabase: vi.fn() }))
vi.mock("@/lib/local-source-snapshot", () => ({
  createLocalReviewSnapshot: vi.fn(),
  localSourceIdentityHash: vi.fn(),
}))

const mockedRuntime = vi.mocked(useRuntimeEnvironment)
const mockedSession = vi.mocked(useSession)
const mockedDatabase = vi.mocked(getLocalProjectsDatabase)
const mockedCapture = vi.mocked(createLocalReviewSnapshot)
const mockedIdentityHash = vi.mocked(localSourceIdentityHash)

const githubProject: Project = {
  id: "project-github",
  name: "GitHub project",
  source: "github",
  external_repository_id: "repo-a",
  external_repository_connection_id: "connection-a",
  repository_owner: "fortune710",
  repository_name: "trace",
  branch_name: "main",
  repository_visibility: "private",
  imported_at: null,
  source_hash: null,
  current_revision: "a".repeat(40),
  category: "productivity",
  auto_create_pull_requests: false,
  created_at: "2026-10-21T00:00:00Z",
  updated_at: "2026-10-21T00:00:00Z",
  archived_at: null,
}

const localProject: Project = {
  ...githubProject,
  id: "local:project",
  name: "Local project",
  source: "local",
  external_repository_id: null,
  external_repository_connection_id: null,
  repository_owner: null,
  repository_name: "Local project",
  branch_name: null,
  repository_visibility: null,
  current_revision: null,
  local_source_id: "source-a",
}

const localRecord: DesktopProjectRecord = {
  id: "local:project",
  accountId: "account-a",
  persistence: "local",
  name: "Local project",
  category: "productivity",
  source: {
    kind: "local",
    sourceId: "source-a",
    displayName: "Local project",
    canonicalPath: "/private/Trace project",
    availability: "available",
    lastValidatedAt: null,
  },
  createdAt: "2026-10-21T00:00:00Z",
  updatedAt: "2026-10-21T00:00:00Z",
  apiLastFetchedAt: null,
  apiCacheStatus: "not_applicable",
}

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>
}

describe("useProjectReviews", () => {
  it("loads reviews filtered to the selected project", async () => {
    const listReviews = vi.spyOn(reviewsApi, "list").mockResolvedValue({
      items: [],
      next_offset: null,
    })

    const { result } = renderHook(() => useProjectReviews("project-a", 1), {
      wrapper,
    })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(listReviews).toHaveBeenCalledWith({
      projectId: "project-a",
      page: 1,
      pageSize: 10,
    })
    listReviews.mockRestore()
  })
})

describe("useCreateReview", () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    mockedSession.mockReturnValue({ data: { user_id: "account-a" } } as ReturnType<typeof useSession>)
    vi.spyOn(reviewsApi, "create").mockResolvedValue({ id: "review-a" } as Review)
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it("submits a GitHub review without a client-controlled source snapshot", async () => {
    mockedRuntime.mockReturnValue({ kind: "web", isTauri: false, isWeb: true })
    const { result } = renderHook(() => useCreateReview(), { wrapper })

    await act(async () => {
      await result.current.mutateAsync({ project: githubProject, agentIds: ["agent-a", "agent-b"] })
    })

    expect(reviewsApi.create).toHaveBeenCalledWith(
      { project_id: "project-github", agent_ids: ["agent-a", "agent-b"] },
      expect.any(String),
    )
  })

  it("lazily provisions a local project and submits only opaque snapshot metadata", async () => {
    mockedRuntime.mockReturnValue({ kind: "tauri", isTauri: true, isWeb: false })
    const database = {
      get: vi.fn().mockResolvedValue(localRecord),
      updateLocal: vi.fn().mockResolvedValue(undefined),
    }
    mockedDatabase.mockResolvedValue(database as never)
    mockedIdentityHash.mockResolvedValue("b".repeat(64))
    mockedCapture.mockResolvedValue({
      snapshotId: "snapshot-a",
      integrityAlgorithm: "sha256-directory-manifest-v1",
      digest: "a".repeat(64),
    })
    vi.spyOn(projectsApi, "create").mockResolvedValue({ id: "backend-project" } as Project)

    const { result } = renderHook(() => useCreateReview(), { wrapper })

    await act(async () => {
      await result.current.mutateAsync({ project: localProject, agentIds: ["agent-a"] })
    })

    expect(projectsApi.create).toHaveBeenCalledWith({
      name: "Local project",
      source: "local",
      local_path_hash: "b".repeat(64),
      category: "productivity",
      auto_create_pull_requests: false,
    })
    expect(database.updateLocal).toHaveBeenCalledWith(expect.objectContaining({
      source: expect.objectContaining({ apiProjectId: "backend-project" }),
    }))
    expect(reviewsApi.create).toHaveBeenCalledWith(
      {
        project_id: "backend-project",
        agent_ids: ["agent-a"],
        local_source_snapshot: {
          source_id: "source-a",
          integrity_algorithm: "sha256-directory-manifest-v1",
          digest: "a".repeat(64),
        },
      },
      expect.any(String),
    )
    expect(JSON.stringify(vi.mocked(reviewsApi.create).mock.calls[0][0])).not.toContain("/private/Trace project")
  })
})
