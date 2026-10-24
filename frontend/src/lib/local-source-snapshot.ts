import { invoke } from "@tauri-apps/api/core"

export type NativeSourceSnapshot = {
  integrityAlgorithm: "sha256-directory-manifest-v1"
  digest: string
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

export async function localSourceIdentityHash(sourceId: string): Promise<string> {
  const encoder = new TextEncoder()
  const bytes = encoder.encode(`trace-local-source-id-v1\0${sourceId}`)
  const digest = await crypto.subtle.digest("SHA-256", bytes)

  return Array.from(new Uint8Array(digest), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("")
}
