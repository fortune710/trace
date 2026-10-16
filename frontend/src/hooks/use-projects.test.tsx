// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, renderHook, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { projectsApi } from "@/lib/api"
import type { DesktopProjectRecord } from "@/lib/desktop-projects"
import { useCreateLocalProject, useProjects } from "@/hooks/use-projects"
import { useDesktopProjectSync } from "@/hooks/use-desktop-project-sync"
import { useRuntimeEnvironment } from "@/hooks/use-runtime-environment"
import { useSession } from "@/hooks/use-session"
import { getLocalProjectsDatabase } from "@/lib/local-projects-database"

vi.mock("@/hooks/use-runtime-environment", () => ({ useRuntimeEnvironment: vi.fn() }))
vi.mock("@/hooks/use-session", () => ({ useSession: vi.fn() }))
vi.mock("@/hooks/use-desktop-project-sync", () => ({ useDesktopProjectSync: vi.fn() }))
vi.mock("@/lib/local-projects-database", () => ({ getLocalProjectsDatabase: vi.fn() }))

const projectsList = vi.spyOn(projectsApi, "list")
const mockedRuntime = vi.mocked(useRuntimeEnvironment)
const mockedSession = vi.mocked(useSession)
const mockedSync = vi.mocked(useDesktopProjectSync)
const mockedDatabase = vi.mocked(getLocalProjectsDatabase)

const localRecord: DesktopProjectRecord = {
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
    lastValidatedAt: null,
  },
  createdAt: "2026-10-16T00:00:00Z",
  updatedAt: "2026-10-16T00:00:00Z",
  apiLastFetchedAt: null,
  apiCacheStatus: "not_applicable",
}

function wrapper({ children }: { children: React.ReactNode }) {
  return <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>
}

describe("useProjects repository selection", () => {
  beforeEach(() => {
    mockedSession.mockReturnValue({ data: { user_id: "account-a" } } as ReturnType<typeof useSession>)
    mockedSync.mockReturnValue({ isReady: true, syncNow: vi.fn() } as unknown as ReturnType<typeof useDesktopProjectSync>)
    mockedDatabase.mockResolvedValue({ list: vi.fn().mockResolvedValue([localRecord]) } as never)
    projectsList.mockReset()
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it("uses the local database in Tauri without requesting project API data", async () => {
    mockedRuntime.mockReturnValue({ kind: "tauri", isTauri: true, isWeb: false })
    const { result } = renderHook(() => useProjects(1), { wrapper })

    await waitFor(() => expect(result.current.projects).toHaveLength(1))
    expect(result.current.projects[0].name).toBe("Device project")
    expect(projectsList).not.toHaveBeenCalled()
  })

  it("uses the API repository in the browser", async () => {
    mockedRuntime.mockReturnValue({ kind: "web", isTauri: false, isWeb: true })
    projectsList.mockResolvedValue({ items: [], next_offset: null })

    const { result } = renderHook(() => useProjects(1), { wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(projectsList).toHaveBeenCalledWith({ page: 1, pageSize: 9 })
    expect(mockedDatabase).not.toHaveBeenCalled()
  })
})

describe("useCreateLocalProject", () => {
  it("revalidates and stores a local project without calling the project API", async () => {
    mockedRuntime.mockReturnValue({ kind: "tauri", isTauri: true, isWeb: false })
    mockedSession.mockReturnValue({ data: { user_id: "account-a" } } as ReturnType<typeof useSession>)
    const source = localRecord.source
    const revalidate = vi.fn().mockResolvedValue(source)
    const insertLocal = vi.fn().mockResolvedValue(undefined)
    mockedDatabase.mockResolvedValue({ revalidate, insertLocal } as never)
    const create = vi.spyOn(projectsApi, "create")

    const { result } = renderHook(() => useCreateLocalProject(), { wrapper })

    await act(async () => {
      await result.current.mutateAsync({ name: "Local project", category: "productivity", sourceId: "source-a" })
    })

    expect(revalidate).toHaveBeenCalledWith("account-a", "source-a")
    expect(insertLocal).toHaveBeenCalledOnce()
    expect(insertLocal.mock.calls[0][0]).toMatchObject({
      accountId: "account-a",
      persistence: "local",
      name: "Local project",
      category: "productivity",
      source,
    })
    expect(create).not.toHaveBeenCalled()
  })

  it.each(["missing", "permission_denied", "unreadable", "not_directory"] as const)(
    "does not create a local project when source validation returns %s",
    async (code) => {
      mockedRuntime.mockReturnValue({ kind: "tauri", isTauri: true, isWeb: false })
      mockedSession.mockReturnValue({ data: { user_id: "account-a" } } as ReturnType<typeof useSession>)
      const revalidate = vi.fn().mockRejectedValue({ code })
      const insertLocal = vi.fn()
      mockedDatabase.mockResolvedValue({ revalidate, insertLocal } as never)

      const { result } = renderHook(() => useCreateLocalProject(), { wrapper })

      await expect(act(async () => {
        await result.current.mutateAsync({ name: "Local project", category: "productivity", sourceId: "source-a" })
      })).rejects.toMatchObject({ code })

      expect(revalidate).toHaveBeenCalledWith("account-a", "source-a")
      expect(insertLocal).not.toHaveBeenCalled()
    },
  )
})
