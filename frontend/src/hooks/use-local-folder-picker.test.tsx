// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { invoke, isTauri } from "@tauri-apps/api/core"
import { useLocalFolderPicker } from "@/hooks/use-local-folder-picker"
import { useSession } from "@/hooks/use-session"
import { getLocalProjectsDatabase } from "@/lib/local-projects-database"
import { assertPathFree } from "@/test/path-redaction"

vi.mock("@tauri-apps/api/core", () => ({
  invoke: vi.fn(),
  isTauri: vi.fn(),
}))

vi.mock("@/hooks/use-session", () => ({
  useSession: vi.fn(),
}))

vi.mock("@/lib/local-projects-database", () => ({
  getLocalProjectsDatabase: vi.fn(),
}))

const mockedInvoke = vi.mocked(invoke)
const mockedIsTauri = vi.mocked(isTauri)
const mockedSession = vi.mocked(useSession)
const mockedGetDatabase = vi.mocked(getLocalProjectsDatabase)

describe("useLocalFolderPicker", () => {
  const register = vi.fn()
  const disconnect = vi.fn()

  beforeEach(() => {
    mockedInvoke.mockReset()
    mockedIsTauri.mockReset()
    mockedSession.mockReset()
    mockedGetDatabase.mockReset()
    register.mockReset()
    disconnect.mockReset()
    mockedIsTauri.mockReturnValue(true)
    mockedSession.mockReturnValue({ data: { user_id: "account-a" } } as ReturnType<typeof useSession>)
    mockedGetDatabase.mockResolvedValue({ register, disconnect } as unknown as Awaited<ReturnType<typeof getLocalProjectsDatabase>>)
    register.mockResolvedValue({
      kind: "local",
      sourceId: "source-a",
      displayName: "Trace project",
      canonicalPath: "/Users/example/Trace project",
      availability: "available",
      lastValidatedAt: "2026-10-16T00:00:00.000Z",
    })
    disconnect.mockResolvedValue(undefined)
  })

  it("does not invoke the native picker in web mode", async () => {
    mockedIsTauri.mockReturnValue(false)
    const { result } = renderHook(() => useLocalFolderPicker())

    await act(async () => {
      await result.current.selectFolder()
    })

    expect(mockedInvoke).not.toHaveBeenCalled()
    expect(result.current.error).toMatchObject({ code: "desktop_only" })
  })

  it("opens the desktop single-folder picker and returns safe metadata", async () => {
    mockedInvoke.mockResolvedValue({
      canonicalPath: "/Users/example/Trace project",
      displayName: "Trace project",
    })
    const { result } = renderHook(() => useLocalFolderPicker())

    await act(async () => {
      await result.current.selectFolder()
    })

    expect(mockedInvoke).toHaveBeenCalledWith("pick_local_folder")
    expect(register).toHaveBeenCalledWith("account-a", expect.objectContaining({
      kind: "local",
      canonicalPath: "/Users/example/Trace project",
      availability: "available",
    }))
    expect(result.current.selection).toMatchObject({
      sourceId: "source-a",
      displayName: "Trace project",
      availability: "available",
    })
    expect(result.current.selection).not.toHaveProperty("canonicalPath")
  })

  it("keeps the current selection when the user cancels", async () => {
    mockedInvoke.mockResolvedValue(null)
    const { result } = renderHook(() => useLocalFolderPicker())

    await act(async () => {
      await result.current.selectFolder()
    })

    expect(result.current.selection).toBeNull()
    expect(result.current.error).toBeNull()
    expect(register).not.toHaveBeenCalled()
  })

  it.each([
    ["missing", "missing"],
    ["not_directory", "not_directory"],
    ["permission_denied", "permission_denied"],
    ["unreadable", "unreadable"],
    ["validation_failed", "validation_failed"],
  ] as const)("maps a native %s failure without exposing its path", async (code, expectedCode) => {
    mockedInvoke.mockRejectedValue({ code, path: "/Users/private/secret" })
    const { result } = renderHook(() => useLocalFolderPicker())

    await act(async () => {
      await result.current.selectFolder()
    })

    expect(result.current.error).toMatchObject({ code: expectedCode })
    assertPathFree(result.current.error, ["/Users/private/secret"])
    expect(register).not.toHaveBeenCalled()
  })

  it("replaces a previous provisional mapping", async () => {
    mockedInvoke
      .mockResolvedValueOnce({ canonicalPath: "/Users/example/one", displayName: "one" })
      .mockResolvedValueOnce({ canonicalPath: "/Users/example/two", displayName: "two" })
    register
      .mockResolvedValueOnce({ sourceId: "source-one", displayName: "one", availability: "available", canonicalPath: "/Users/example/one", lastValidatedAt: null })
      .mockResolvedValueOnce({ sourceId: "source-two", displayName: "two", availability: "available", canonicalPath: "/Users/example/two", lastValidatedAt: null })
    const { result } = renderHook(() => useLocalFolderPicker())

    await act(async () => {
      await result.current.selectFolder()
      await result.current.selectFolder()
    })

    expect(disconnect).toHaveBeenCalledWith("account-a", "source-one")
    expect(result.current.selection).toMatchObject({ sourceId: "source-two", displayName: "two" })
  })

  it("clears the provisional mapping without deleting source files", async () => {
    mockedInvoke.mockResolvedValue({ canonicalPath: "/Users/example/Trace project", displayName: "Trace project" })
    const { result } = renderHook(() => useLocalFolderPicker())

    await act(async () => {
      await result.current.selectFolder()
      await result.current.clearSelection()
    })

    expect(disconnect).toHaveBeenCalledWith("account-a", "source-a")
    expect(result.current.selection).toBeNull()
  })

  it("uses the active account for registration and cleanup", async () => {
    mockedSession.mockReturnValue({ data: { user_id: "account-b" } } as ReturnType<typeof useSession>)
    mockedInvoke.mockResolvedValue({ canonicalPath: "/Users/example/account-b", displayName: "account-b" })

    const { result } = renderHook(() => useLocalFolderPicker())

    await act(async () => {
      await result.current.selectFolder()
      await result.current.clearSelection()
    })

    expect(register).toHaveBeenCalledWith("account-b", expect.anything())
    expect(disconnect).toHaveBeenCalledWith("account-b", "source-a")
  })

  it("prevents concurrent native picker requests", async () => {
    let resolvePicker: ((value: { canonicalPath: string; displayName: string }) => void) | undefined
    mockedInvoke.mockImplementation(() => new Promise((resolve) => {
      resolvePicker = resolve
    }))
    const { result } = renderHook(() => useLocalFolderPicker())
    let firstSelection: Promise<unknown> | undefined

    await act(async () => {
      firstSelection = result.current.selectFolder()
      await Promise.resolve()
    })

    expect(result.current.isSelecting).toBe(true)
    let secondSelection: unknown
    await act(async () => {
      secondSelection = await result.current.selectFolder()
    })
    expect(secondSelection).toBeNull()
    expect(mockedInvoke).toHaveBeenCalledOnce()

    await act(async () => {
      resolvePicker?.({ canonicalPath: "/Users/example/Trace project", displayName: "Trace project" })
      await firstSelection
    })
    expect(result.current.isSelecting).toBe(false)
  })

  it("reports storage failures without exposing the selected path", async () => {
    mockedInvoke.mockResolvedValue({ canonicalPath: "/Users/private/secret", displayName: "secret" })
    register.mockRejectedValue(new Error("database failed for /Users/private/secret"))
    const { result } = renderHook(() => useLocalFolderPicker())

    await act(async () => {
      await result.current.selectFolder()
    })

    expect(result.current.error).toMatchObject({ code: "storage_failed" })
    assertPathFree(result.current.error, ["/Users/private/secret"])
  })

  it("reports cleanup storage failures and retains the mapping for retry", async () => {
    mockedInvoke.mockResolvedValue({ canonicalPath: "/Users/example/Trace project", displayName: "Trace project" })
    const { result } = renderHook(() => useLocalFolderPicker())

    await act(async () => {
      await result.current.selectFolder()
    })
    disconnect.mockRejectedValueOnce(new Error("database cleanup failed"))

    await act(async () => {
      await expect(result.current.clearSelection()).rejects.toMatchObject({ code: "storage_failed" })
    })

    expect(result.current.error).toMatchObject({ code: "storage_failed" })
    expect(result.current.selection).toMatchObject({ sourceId: "source-a" })
  })
})
