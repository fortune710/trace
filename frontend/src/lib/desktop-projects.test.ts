import { describe, expect, it } from "vitest"

import type { Project } from "@/lib/api"
import { mergeApiProjectCache, toDesktopApiProject, toProjectResponse, type DesktopProjectRecord } from "@/lib/desktop-projects"
import { assertPathFree } from "@/test/path-redaction"

const apiProject: Project = {
  id: "remote-project",
  name: "Remote project",
  source: "github",
  external_repository_id: "123",
  external_repository_connection_id: "connection",
  repository_owner: "trace-labs",
  repository_name: "trace-dashboard",
  branch_name: "main",
  repository_visibility: "private",
  imported_at: "2026-10-16T00:00:00Z",
  source_hash: null,
  current_revision: "abc123",
  category: "business",
  auto_create_pull_requests: false,
  created_at: "2026-10-16T00:00:00Z",
  updated_at: "2026-10-16T00:00:00Z",
  archived_at: null,
}

const legacyApiLocalProject: Project = {
  ...apiProject,
  id: "legacy-local",
  name: "Legacy local project",
  source: "local",
}

const localProject: DesktopProjectRecord = {
  id: "local:project",
  accountId: "account-a",
  persistence: "local",
  name: "Device project",
  category: "productivity",
  source: {
    kind: "local",
    sourceId: "source-a",
    displayName: "Device project",
    canonicalPath: "/Users/example/Device project",
    availability: "available",
    lastValidatedAt: "2026-10-16T00:00:00Z",
  },
  createdAt: "2026-10-16T00:00:00Z",
  updatedAt: "2026-10-16T00:00:00Z",
  apiLastFetchedAt: null,
  apiCacheStatus: "not_applicable",
}

describe("desktop project contract", () => {
  it("converts GitHub API projects to local cache records", () => {
    expect(toDesktopApiProject(apiProject, "account-a", "2026-10-16T01:00:00Z")).toMatchObject({
      id: "api:account-a:remote-project",
      accountId: "account-a",
      persistence: "api_cache",
      source: { kind: "github", apiProjectId: "remote-project" },
      apiCacheStatus: "fresh",
    })
  })

  it("excludes legacy API-local projects", () => {
    expect(toDesktopApiProject(legacyApiLocalProject, "account-a", "2026-10-16T01:00:00Z")).toBeNull()
  })

  it("preserves local projects while replacing the API cache", () => {
    const merged = mergeApiProjectCache(
      [localProject],
      [apiProject, legacyApiLocalProject],
      "account-a",
      "2026-10-16T01:00:00Z",
    )

    expect(merged).toHaveLength(2)
    expect(merged.some((project) => project.persistence === "local")).toBe(true)
    expect(merged.some((project) => project.source.kind === "github")).toBe(true)
    expect(merged.some((project) => project.id === "api:account-a:legacy-local")).toBe(false)
  })

  it("does not expose a local canonical path in the safe project projection", () => {
    const response = toProjectResponse(localProject)

    expect(response.source).toBe("local")
    expect(response.repository_name).toBe("Device project")
    expect(response.imported_at).toBe(localProject.createdAt)
    expect(response).not.toHaveProperty("canonicalPath")
    assertPathFree(response, [
      localProject.source.kind === "local" ? localProject.source.canonicalPath : "",
    ])
  })

  it("maps the desktop cached project creation date to imported_at", () => {
    const cachedProject = toDesktopApiProject(apiProject, "account-a", "2026-10-16T01:00:00Z")

    expect(cachedProject).not.toBeNull()
    expect(toProjectResponse(cachedProject!).imported_at).toBe(apiProject.created_at)
  })

  it("does not merge another account's local records", () => {
    const otherAccountProject = { ...localProject, id: "local:other", accountId: "account-b" }

    expect(mergeApiProjectCache([localProject, otherAccountProject], [], "account-a", "2026-10-16T01:00:00Z")).toEqual([localProject])
  })
})
