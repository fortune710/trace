import { beforeEach, describe, expect, it, vi } from "vitest"
import { invoke } from "@tauri-apps/api/core"

import { LocalProjectCreationError, LocalSourceValidationError, type DesktopProjectRecord } from "@/lib/desktop-projects"
import { LocalProjectsDatabase } from "@/lib/local-projects-database"

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }))

const mockedInvoke = vi.mocked(invoke)

beforeEach(() => {
  mockedInvoke.mockReset()
})

describe("LocalProjectsDatabase", () => {
  const localProject: DesktopProjectRecord = {
    id: "local:project-a",
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
      lastValidatedAt: "2026-10-16T00:00:00.000Z",
    },
    createdAt: "2026-10-16T00:00:00.000Z",
    updatedAt: "2026-10-16T00:00:00.000Z",
    apiLastFetchedAt: null,
    apiCacheStatus: "not_applicable",
  }

  it("always scopes reads by account", async () => {
    const select = vi.fn().mockResolvedValue([])
    const database = new LocalProjectsDatabase(Promise.resolve({
      execute: vi.fn(),
      select,
    }))

    await database.list("account-a")
    await database.get("account-b", "project-b")
    expect(select.mock.calls[0][1]).toEqual(["account-a"])
    expect(select.mock.calls[1][1]).toEqual(["account-b", "project-b"])
  })

  it("does not resolve or revalidate another account's source mapping", async () => {
    const select = vi.fn().mockResolvedValue([])
    const execute = vi.fn().mockResolvedValue({ rowsAffected: 1 })
    const database = new LocalProjectsDatabase(Promise.resolve({ execute, select }))

    await expect(database.resolve("account-b", "source-a")).resolves.toBeNull()
    await expect(database.revalidate("account-b", "source-a")).rejects.toEqual(
      expect.objectContaining({ code: "missing", message: "missing" }) as LocalSourceValidationError,
    )

    expect(mockedInvoke).not.toHaveBeenCalled()
    expect(select).toHaveBeenCalledWith(expect.stringContaining("local_sources"), ["account-b", "source-a"])
  })

  it("revalidates a source within its account and updates its safe status", async () => {
    mockedInvoke.mockResolvedValue({ displayName: "Device project" })
    const select = vi.fn().mockResolvedValue([{
      source_id: "source-a",
      display_name: "Device project",
      canonical_path: "/Users/example/Device project",
      availability: "available",
      last_validated_at: null,
    }])
    const execute = vi.fn().mockResolvedValue({ rowsAffected: 1 })
    const database = new LocalProjectsDatabase(Promise.resolve({ execute, select }))

    const result = await database.revalidate("account-a", "source-a")

    expect(result).toMatchObject({ sourceId: "source-a", availability: "available" })
    expect(mockedInvoke).toHaveBeenCalledWith("validate_local_folder", { canonicalPath: "/Users/example/Device project" })
    expect(execute).toHaveBeenCalledWith(expect.stringContaining("UPDATE local_sources"), expect.arrayContaining(["account-a", "source-a"]))
  })

  it("records a missing source and returns a path-free validation error", async () => {
    mockedInvoke.mockRejectedValue({ code: "missing" })
    const select = vi.fn().mockResolvedValue([{
      source_id: "source-a",
      display_name: "Device project",
      canonical_path: "/Users/example/Device project",
      availability: "available",
      last_validated_at: null,
    }])
    const execute = vi.fn().mockResolvedValue({ rowsAffected: 1 })
    const database = new LocalProjectsDatabase(Promise.resolve({ execute, select }))

    await expect(database.revalidate("account-a", "source-a")).rejects.toEqual(
      expect.objectContaining({ code: "missing", message: "missing" }) as LocalSourceValidationError,
    )
    expect(execute).toHaveBeenCalledWith(expect.stringContaining("UPDATE local_sources"), expect.arrayContaining(["missing", "account-a", "source-a"]))
  })

  it.each(["not_directory", "permission_denied", "unreadable", "validation_failed"] as const)(
    "records a %s source validation failure without exposing its path",
    async (code) => {
      mockedInvoke.mockRejectedValue({ code, path: "/Users/private/secret" })
      const select = vi.fn().mockResolvedValue([{
        source_id: "source-a",
        display_name: "Device project",
        canonical_path: "/Users/example/Device project",
        availability: "available",
        last_validated_at: null,
      }])
      const execute = vi.fn().mockResolvedValue({ rowsAffected: 1 })
      const database = new LocalProjectsDatabase(Promise.resolve({ execute, select }))

      await expect(database.revalidate("account-a", "source-a")).rejects.toEqual(
        expect.objectContaining({ code, message: code }) as LocalSourceValidationError,
      )
      expect(execute.mock.calls.some(([, values]) =>
        Array.isArray(values) && values.includes("/Users/private/secret"),
      )).toBe(false)
    },
  )

  it("uses an immediate transaction and rejects an existing local project by account and path", async () => {
    const execute = vi.fn().mockResolvedValue({ rowsAffected: 1 })
    const select = vi.fn().mockResolvedValue([{ id: "local:existing" }])
    const database = new LocalProjectsDatabase(Promise.resolve({ execute, select }))

    await expect(database.insertLocal(localProject)).rejects.toEqual(
      expect.objectContaining({ code: "already_exists", message: "already_exists" }) as LocalProjectCreationError,
    )

    expect(execute).toHaveBeenNthCalledWith(1, "BEGIN IMMEDIATE")
    expect(execute).toHaveBeenCalledWith("ROLLBACK")
    expect(execute.mock.calls.some(([query]) => query.includes("INSERT INTO desktop_projects"))).toBe(false)
  })

  it("stores the canonical path as part of a new local project insert", async () => {
    const execute = vi.fn().mockResolvedValue({ rowsAffected: 1 })
    const select = vi.fn().mockResolvedValue([])
    const database = new LocalProjectsDatabase(Promise.resolve({ execute, select }))

    await database.insertLocal(localProject)

    expect(execute).toHaveBeenNthCalledWith(1, "BEGIN IMMEDIATE")
    expect(execute.mock.calls.some(([query, values]) =>
      query.includes("local_canonical_path") && Array.isArray(values) && values.includes("/Users/example/Device project"),
    )).toBe(true)
    expect(execute).toHaveBeenCalledWith("COMMIT")
  })

  it("maps the database uniqueness constraint to a stable duplicate error", async () => {
    const execute = vi.fn().mockImplementation(async (query: string) => {
      if (query.includes("INSERT INTO desktop_projects")) {
        throw new Error("UNIQUE constraint failed: desktop_projects.account_id, desktop_projects.local_canonical_path")
      }
      return { rowsAffected: 1 }
    })
    const select = vi.fn().mockResolvedValue([])
    const database = new LocalProjectsDatabase(Promise.resolve({ execute, select }))

    await expect(database.insertLocal(localProject)).rejects.toEqual(
      expect.objectContaining({ code: "already_exists", message: "already_exists" }) as LocalProjectCreationError,
    )
    expect(execute).toHaveBeenCalledWith("ROLLBACK")
  })
})
