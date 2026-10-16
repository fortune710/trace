// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from "vitest"

import { projectsApi, repositoriesApi } from "@/lib/api"
import { assertPathFree } from "@/test/path-redaction"

describe("repositoriesApi", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("includes the provider, page, and search query when listing repositories", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items: [], next_page: null }), { status: 200 }),
    )
    vi.stubGlobal("fetch", fetchMock)

    await repositoriesApi.list({ page: 2, query: "trace dashboard" })

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/repositories?source=github&page=2&page_size=5&query=trace+dashboard",
      expect.objectContaining({ credentials: "include" }),
    )
  })

  it("encodes the repository identifier and omits an absent branch query", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items: [], next_page: null }), { status: 200 }),
    )
    vi.stubGlobal("fetch", fetchMock)

    await repositoriesApi.listBranches({ repositoryId: "12345", page: 1 })

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/repositories/12345/branches?source=github&page=1&page_size=5",
      expect.objectContaining({ credentials: "include" }),
    )
  })
})

describe("projectsApi", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("includes the requested page and page size when listing projects", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items: [], next_offset: null }), { status: 200 }),
    )
    vi.stubGlobal("fetch", fetchMock)

    await projectsApi.list({ page: 2, pageSize: 9 })

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/projects?page=2&page_size=9",
      expect.objectContaining({ credentials: "include" }),
    )
  })

  it("keeps project API requests free of local source paths", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({
        id: "remote-project",
        name: "Remote project",
      }), { status: 200 }),
    )
    vi.stubGlobal("fetch", fetchMock)

    await projectsApi.create({
      name: "Remote project",
      source: "github",
      repository_id: "repository-1",
      branch_name: "main",
      category: "productivity",
      auto_create_pull_requests: false,
    })

    const requestInit = fetchMock.mock.calls[0]?.[1] as RequestInit
    assertPathFree(requestInit.body)
    expect(requestInit.body).not.toContain("canonicalPath")
  })
})
