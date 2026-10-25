// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from "vitest"

import { agentsApi, authApi, credentialsApi, projectsApi, repositoriesApi } from "@/lib/api"
import { runtimeConfig } from "@/lib/runtime-config"
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
    document.cookie = "trace_csrf=project-test-token"
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
    document.cookie = "trace_csrf=; Max-Age=0"
  })
})

describe("agent and credential APIs", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    document.cookie = "trace_csrf=; Max-Age=0"
  })

  it("lists agents, retrieves an agent detail, and fetches the managed model catalog", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ items: [], next_offset: null }), { status: 200 }))
    vi.stubGlobal("fetch", fetchMock)

    await agentsApi.list({ page: 2, pageSize: 9, includeDisabled: true })
    await agentsApi.catalog()
    await agentsApi.get("agent/1")

    expect(fetchMock).toHaveBeenNthCalledWith(1, "http://localhost:8000/api/v1/agents?page=2&page_size=9&include_disabled=true", expect.objectContaining({ credentials: "include" }))
    expect(fetchMock).toHaveBeenNthCalledWith(2, "http://localhost:8000/api/v1/agents/catalog", expect.objectContaining({ credentials: "include" }))
    expect(fetchMock).toHaveBeenNthCalledWith(3, "http://localhost:8000/api/v1/agents/agent%2F1", expect.objectContaining({ credentials: "include" }))
  })

  it("sends CSRF-protected agent and provider-key mutations without leaking extra fields", async () => {
    document.cookie = "trace_csrf=test-token"
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: "item" }), { status: 201 }))
    vi.stubGlobal("fetch", fetchMock)

    await agentsApi.create({ name: "Security", review_category: "security", model_provider: "openai", model_name: "gpt-5.1", skills: [] })
    await credentialsApi.createOrReplace({ provider: "openai", kind: "api_key", payload: { api_key: "secret-value" } })

    const agentInit = fetchMock.mock.calls[0]?.[1] as RequestInit
    const credentialInit = fetchMock.mock.calls[1]?.[1] as RequestInit
    expect(new Headers(agentInit.headers).get("X-CSRF-Token")).toBe("test-token")
    expect(JSON.parse(String(agentInit.body))).toEqual({ name: "Security", review_category: "security", model_provider: "openai", model_name: "gpt-5.1", skills: [] })
    expect(JSON.parse(String(credentialInit.body))).toEqual({ provider: "openai", kind: "api_key", payload: { api_key: "secret-value" } })
  })

  it("obtains a CSRF token from the API when its host-only cookie is not visible", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ csrf_token: "api-host-token" }), { status: 200 })
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ id: "agent-1" }), { status: 201 })
      )
    vi.stubGlobal("fetch", fetchMock)

    await agentsApi.create({
      name: "Security",
      review_category: "security",
      model_provider: "openai",
      model_name: "gpt-5.1",
      skills: [],
    })

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "http://localhost:8000/auth/csrf",
      expect.objectContaining({ credentials: "include" }),
    )
    const mutation = fetchMock.mock.calls[1]?.[1] as RequestInit
    expect(new Headers(mutation.headers).get("X-CSRF-Token")).toBe("api-host-token")
  })

  it("ignores a stale frontend-host cookie after moving the API to a subdomain", async () => {
    const previousApiBaseUrl = runtimeConfig.apiBaseUrl
    Object.assign(runtimeConfig, {
      apiBaseUrl: "https://traceapi.fortunealebiosu.dev",
    })
    document.cookie = "trace_csrf=stale-frontend-token"
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ csrf_token: "api-host-token" }), { status: 200 })
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ id: "agent-1" }), { status: 201 })
      )
    vi.stubGlobal("fetch", fetchMock)

    try {
      await agentsApi.create({
        name: "Security",
        review_category: "security",
        model_provider: "openai",
        model_name: "gpt-5.1",
        skills: [],
      })

      expect(fetchMock.mock.calls[0]?.[0]).toBe(
        "https://traceapi.fortunealebiosu.dev/auth/csrf"
      )
      const mutation = fetchMock.mock.calls[1]?.[1] as RequestInit
      expect(new Headers(mutation.headers).get("X-CSRF-Token")).toBe("api-host-token")
    } finally {
      Object.assign(runtimeConfig, { apiBaseUrl: previousApiBaseUrl })
    }
  })

  it("does not require a session CSRF token for login", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ message: "Authenticated.", csrf_token: "new-token" }), {
        status: 200,
      })
    )
    vi.stubGlobal("fetch", fetchMock)

    await authApi.login("user@example.com", "password")

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0]?.[0]).toBe("http://localhost:8000/auth/login")
  })
})
