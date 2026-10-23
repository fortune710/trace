import { describe, expect, it, vi } from "vitest"
import { invoke } from "@tauri-apps/api/core"

import {
  LocalSourceSnapshotError,
  captureLocalSourceSnapshot,
  localSourceIdentityHash,
} from "@/lib/local-source-snapshot"

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }))

const mockedInvoke = vi.mocked(invoke)

describe("local source snapshots", () => {
  it("uses a deterministic domain-separated opaque source identity hash", async () => {
    const first = await localSourceIdentityHash("source-a")
    const repeat = await localSourceIdentityHash("source-a")
    const other = await localSourceIdentityHash("source-b")

    expect(first).toMatch(/^[0-9a-f]{64}$/)
    expect(first).toBe(repeat)
    expect(first).not.toBe(other)
  })

  it("returns only digest metadata from the native command", async () => {
    mockedInvoke.mockResolvedValueOnce({
      integrityAlgorithm: "sha256-directory-manifest-v1",
      digest: "a".repeat(64),
    })

    const snapshot = await captureLocalSourceSnapshot("/private/local-project")

    expect(snapshot).toEqual({
      integrityAlgorithm: "sha256-directory-manifest-v1",
      digest: "a".repeat(64),
    })
    expect(mockedInvoke).toHaveBeenCalledWith("capture_local_source_snapshot", {
      canonicalPath: "/private/local-project",
    })
  })

  it("turns native failures into a path-free safe error", async () => {
    mockedInvoke.mockRejectedValueOnce({
      code: "snapshot_failed",
      path: "/private/local-project",
    })

    await expect(
      captureLocalSourceSnapshot("/private/local-project"),
    ).rejects.toEqual(expect.any(LocalSourceSnapshotError))
  })
})
