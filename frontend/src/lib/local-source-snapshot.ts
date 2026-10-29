import { invoke } from "@tauri-apps/api/core"

export type NativeSourceSnapshot = {
  integrityAlgorithm: "sha256-directory-manifest-v1"
  digest: string
}

export type NativeStoredSourceSnapshot = NativeSourceSnapshot & {
  snapshotId: string
}

export type NativeLocalRemediationFile = {
  filePath: string
  backupReference: string
  sourceHash: string
  appliedHash: string
}

export type NativeLocalRemediationResult = {
  files: NativeLocalRemediationFile[]
}

type NativeSnapshotError = {
  code?: string
}

export class LocalSourceSnapshotError extends Error {
  constructor() {
    super("The local source could not be captured safely.")
    this.name = "LocalSourceSnapshotError"
  }
}

export async function captureLocalSourceSnapshot(
  canonicalPath: string,
): Promise<NativeSourceSnapshot> {
  try {
    return await invoke<NativeSourceSnapshot>("capture_local_source_snapshot", {
      canonicalPath,
    })
  } catch (error) {
    const code = (error as NativeSnapshotError | null)?.code
    if (code === "snapshot_failed") {
      throw new LocalSourceSnapshotError()
    }

    throw new LocalSourceSnapshotError()
  }
}

export async function createLocalReviewSnapshot(
  canonicalPath: string,
): Promise<NativeStoredSourceSnapshot> {
  try {
    return await invoke<NativeStoredSourceSnapshot>("create_local_review_snapshot", {
      canonicalPath,
      snapshotId: crypto.randomUUID(),
    })
  } catch {
    throw new LocalSourceSnapshotError()
  }
}

export async function applyLocalRemediation(
  canonicalPath: string,
  remediationId: string,
  diff: string,
): Promise<NativeLocalRemediationResult> {
  try {
    return await invoke<NativeLocalRemediationResult>("apply_local_remediation", {
      canonicalPath,
      remediationId,
      diff,
    })
  } catch (error) {
    const code = (error as NativeSnapshotError | null)?.code
    if (code === "invalid_diff" || code === "source_changed") {
      throw new LocalSourceSnapshotError()
    }
    throw new LocalSourceSnapshotError()
  }
}

export async function restoreLocalRemediation(
  canonicalPath: string,
  remediationId: string,
  files: NativeLocalRemediationFile[],
): Promise<void> {
  try {
    await invoke("restore_local_remediation", {
      canonicalPath,
      remediationId,
      files: files.map((file) => ({
        filePath: file.filePath,
        backupReference: file.backupReference,
        appliedHash: file.appliedHash,
      })),
    })
  } catch {
    throw new LocalSourceSnapshotError()
  }
}

export async function localSourceIdentityHash(sourceId: string): Promise<string> {
  const encoder = new TextEncoder()
  const bytes = encoder.encode(`trace-local-source-id-v1\0${sourceId}`)
  const digest = await crypto.subtle.digest("SHA-256", bytes)

  return Array.from(new Uint8Array(digest), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("")
}
