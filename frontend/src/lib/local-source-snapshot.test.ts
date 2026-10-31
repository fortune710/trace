import { describe, expect, it, vi } from "vitest"
import { invoke } from "@tauri-apps/api/core"

import {
  LocalSourceSnapshotError,
  applyLocalRemediation,
  captureLocalSourceSnapshot,
  createLocalReviewSnapshot,
  localSourceIdentityHash,
  restoreLocalRemediation,
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

  it("creates a private snapshot with a bounded relative source upload", async () => {
    mockedInvoke.mockResolvedValueOnce({
      snapshotId: "snapshot-a",
      upload: { digest: "b".repeat(64), entries: [] },
      integrityAlgorithm: "sha256-directory-manifest-v1",
      digest: "b".repeat(64),
    })

    const snapshot = await createLocalReviewSnapshot("/private/local-project")

    expect(snapshot).toEqual({
      snapshotId: "snapshot-a",
      upload: { digest: "b".repeat(64), entries: [] },
      integrityAlgorithm: "sha256-directory-manifest-v1",
      digest: "b".repeat(64),
    })
    expect(mockedInvoke).toHaveBeenCalledWith(
      "create_local_review_snapshot",
      expect.objectContaining({ canonicalPath: "/private/local-project" }),
    )
  })

  it("explains upload limits before a local review can be queued", async () => {
    mockedInvoke.mockRejectedValueOnce({ code: "snapshot_upload_too_large" })
    await expect(createLocalReviewSnapshot("/private/local-project")).rejects.toThrow("256 KB per file")
  })

  it("applies and restores a batch of local remediation files through native commands", async () => {
    const files = [
      {
        filePath: "src/example.ts",
        backupReference: "local-remediation-backups/remediation-a/src/example.ts",
        sourceHash: "a".repeat(64),
        appliedHash: "b".repeat(64),
      },
    ]
    mockedInvoke.mockResolvedValueOnce({ files })
    mockedInvoke.mockResolvedValueOnce(undefined)

    await expect(
      applyLocalRemediation("/private/local-project", "remediation-a", { diff: "diff", sha256: "a".repeat(64), source_snapshot: { source_kind: "local", source_identifier: "id", revision: "b".repeat(64) }, files: [], warnings: [] }),
    ).resolves.toEqual({ files })
    await restoreLocalRemediation(
      "/private/local-project",
      "remediation-a",
      files,
    )

    expect(mockedInvoke).toHaveBeenNthCalledWith(1, "apply_local_remediation", {
      canonicalPath: "/private/local-project",
      remediationId: "remediation-a",
      patch: { diff: "diff", sha256: "a".repeat(64), source_snapshot: { source_kind: "local", source_identifier: "id", revision: "b".repeat(64) }, files: [], warnings: [] },
    })
    expect(mockedInvoke).toHaveBeenNthCalledWith(2, "restore_local_remediation", {
      canonicalPath: "/private/local-project",
      remediationId: "remediation-a",
      files: [
        {
          filePath: "src/example.ts",
          backupReference: "local-remediation-backups/remediation-a/src/example.ts",
          appliedHash: "b".repeat(64),
        },
      ],
    })
  })
})
