import { describe, expect, it, vi } from "vitest"

import type { Project } from "@/lib/api"
import { DesktopApiProjectSynchronizer } from "@/lib/desktop-project-sync"
import type { DesktopProjectRecord, LocalProjectStore } from "@/lib/desktop-projects"

const apiProject = (id: string, source: Project["source"] = "github"): Project => ({
  id,
  name: id,
  source,
  external_repository_id: null,
  external_repository_connection_id: null,
  repository_owner: source === "github" ? "trace-labs" : null,
  repository_name: source === "github" ? id : "local-folder",
  branch_name: source === "github" ? "main" : null,
  repository_visibility: source === "github" ? "private" : null,
  imported_at: null,
  source_hash: null,
  current_revision: null,
  category: "productivity",
  auto_create_pull_requests: false,
  created_at: "2026-10-16T00:00:00Z",
  updated_at: "2026-10-16T00:00:00Z",
  archived_at: null,
})

const localProject: DesktopProjectRecord = {
  id: "local:one",
  accountId: "account-a",
  persistence: "local",
  name: "Local project",
  category: "productivity",
  source: {
    kind: "local",
    sourceId: "source-one",
    displayName: "Local project",
    canonicalPath: "/private/local-project",
    availability: "available",
    lastValidatedAt: null,
  },
  createdAt: "2026-10-16T00:00:00Z",
  updatedAt: "2026-10-16T00:00:00Z",
  apiLastFetchedAt: null,
  apiCacheStatus: "not_applicable",
}

function storeWith(records: DesktopProjectRecord[]): LocalProjectStore & {
  replaceApiCache: ReturnType<typeof vi.fn>
  markApiCache: ReturnType<typeof vi.fn>
} {
  return {
    list: vi.fn(async () => records),
    get: vi.fn(),
    insertLocal: vi.fn(),
    updateLocal: vi.fn(),
    removeLocal: vi.fn(),
    replaceApiCache: vi.fn(async (_accountId: string, projects: DesktopProjectRecord[]) => {
      records.splice(0, records.length, ...records.filter((project) => project.persistence === "local"), ...projects)
    }),
    markApiCache: vi.fn(),
  } as unknown as LocalProjectStore & {
    replaceApiCache: ReturnType<typeof vi.fn>
    markApiCache: ReturnType<typeof vi.fn>
  }
}

describe("DesktopApiProjectSynchronizer", () => {
  it("fetches every API page, excludes legacy local records, and preserves local records", async () => {
    const store = storeWith([localProject])
    const fetchPage = vi.fn()
      .mockResolvedValueOnce({ items: [apiProject("one"), apiProject("legacy", "local")], next_offset: 100 })
      .mockResolvedValueOnce({ items: [apiProject("two")], next_offset: null })

    const result = await new DesktopApiProjectSynchronizer(store, fetchPage).sync("account-a")

    expect(fetchPage).toHaveBeenNthCalledWith(1, { page: 1, pageSize: 100 })
    expect(fetchPage).toHaveBeenNthCalledWith(2, { page: 2, pageSize: 100 })
    expect(store.replaceApiCache).toHaveBeenCalledWith(
      "account-a",
      expect.arrayContaining([
        expect.objectContaining({ id: "api:account-a:one" }),
        expect.objectContaining({ id: "api:account-a:two" }),
      ]),
      expect.any(String),
    )
    expect(result.projects.map((project) => project.id)).toEqual(["local:one", "api:account-a:one", "api:account-a:two"])
    expect(result.projects.some((project) => project.source.kind === "local" && project.name === "legacy")).toBe(false)
  })

  it("preserves cached records and marks them unavailable when fetching fails", async () => {
    const store = storeWith([localProject])
    const failure = new Error("offline")
    const fetchPage = vi.fn().mockRejectedValue(failure)

    const result = await new DesktopApiProjectSynchronizer(store, fetchPage).sync("account-a")

    expect(store.markApiCache).toHaveBeenCalledWith("account-a", "unavailable", null)
    expect(result.status).toBe("unavailable")
    expect(result.error).toBe(failure)
    expect(result.projects).toEqual([localProject])
  })
})
