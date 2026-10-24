import { useCallback, useEffect, useRef, useState } from "react"
import { invoke } from "@tauri-apps/api/core"

import { useRuntimeEnvironment } from "@/hooks/use-runtime-environment"
import { useSession } from "@/hooks/use-session"
import { getLocalProjectsDatabase } from "@/lib/local-projects-database"
import type { LocalSourceAvailability } from "@/lib/desktop-projects"

export type FolderSelection = {
  sourceId: string
  displayName: string
  availability: "available"
  lastValidatedAt: string
}

export type FolderPickerErrorCode =
  | "desktop_only"
  | "not_authenticated"
  | "invalid_selection"
  | "missing"
  | "not_directory"
  | "permission_denied"
  | "unreadable"
  | "validation_failed"
  | "storage_failed"

export type FolderPickerError = {
  code: FolderPickerErrorCode
  message: string
}

type NativeFolderSelection = {
  canonicalPath: string
  displayName: string
}

type NativeFolderError = {
  code?: string
}

export type UseLocalFolderPickerResult = {
  selection: FolderSelection | null
  isSelecting: boolean
  error: FolderPickerError | null
  selectFolder: () => Promise<FolderSelection | null>
  clearSelection: () => Promise<void>
  commitSelection: () => void
}

const errorMessages: Record<FolderPickerErrorCode, string> = {
  desktop_only: "Folder selection is available in the Trace desktop app.",
  not_authenticated: "Sign in before selecting a local project folder.",
  invalid_selection: "That folder could not be selected. Try another folder.",
  missing: "That folder no longer exists. Choose another folder.",
  not_directory: "Choose a folder rather than a file.",
  permission_denied: "Trace does not have permission to read that folder.",
  unreadable: "That folder could not be read. Choose another folder.",
  validation_failed: "That folder could not be validated. Try again.",
  storage_failed: "The folder selection could not be saved. Try again.",
}

function createError(code: FolderPickerErrorCode): FolderPickerError {
  return { code, message: errorMessages[code] }
}

function nativeErrorCode(error: unknown): FolderPickerErrorCode {
  const code = (error as NativeFolderError | null)?.code
  switch (code) {
    case "invalid_selection":
    case "missing":
    case "not_directory":
    case "permission_denied":
    case "unreadable":
    case "validation_failed":
      return code
    default:
      return "validation_failed"
  }
}

function safeSelection(source: {
  sourceId: string
  displayName: string
  availability: LocalSourceAvailability
  lastValidatedAt: string | null
}): FolderSelection {
  return {
    sourceId: source.sourceId,
    displayName: source.displayName,
    availability: "available",
    lastValidatedAt: source.lastValidatedAt ?? new Date().toISOString(),
  }
}

export function useLocalFolderPicker(): UseLocalFolderPickerResult {
  const runtime = useRuntimeEnvironment()
  const session = useSession()
  const accountId = session.data?.user_id
  const [selection, setSelection] = useState<FolderSelection | null>(null)
  const [isSelecting, setIsSelecting] = useState(false)
  const [error, setError] = useState<FolderPickerError | null>(null)
  const sourceIdRef = useRef<string | null>(null)
  const sourceAccountIdRef = useRef<string | null>(null)
  const selectingRef = useRef(false)

  const clearSelection = useCallback(async () => {
    const sourceId = sourceIdRef.current
    const sourceAccountId = sourceAccountIdRef.current
    setError(null)

    if (!sourceId || !sourceAccountId) {
      setSelection(null)
      return
    }

    try {
      const database = await getLocalProjectsDatabase()
      await database.disconnect(sourceAccountId, sourceId)
      sourceIdRef.current = null
      sourceAccountIdRef.current = null
      setSelection(null)
    } catch {
      const storageError = createError("storage_failed")
      setError(storageError)
      throw storageError
    }
  }, [])

  const commitSelection = useCallback(() => {
    sourceIdRef.current = null
    sourceAccountIdRef.current = null
    setSelection(null)
    setError(null)
  }, [])

  const selectFolder = useCallback(async () => {
    if (selectingRef.current) return selection

    setError(null)
    if (!runtime.isTauri) {
      const desktopError = createError("desktop_only")
      setError(desktopError)
      return null
    }
    if (!accountId) {
      const sessionError = createError("not_authenticated")
      setError(sessionError)
      return null
    }

    selectingRef.current = true
    setIsSelecting(true)

    try {
      const nativeSelection = await invoke<NativeFolderSelection | null>("pick_local_folder")
      if (!nativeSelection) return null

      const database = await getLocalProjectsDatabase()
      const registered = await database.register(accountId, {
        kind: "local",
        displayName: nativeSelection.displayName,
        canonicalPath: nativeSelection.canonicalPath,
        availability: "available",
        lastValidatedAt: new Date().toISOString(),
        apiProjectId: null,
      })

      const previousSourceId = sourceIdRef.current
      const previousAccountId = sourceAccountIdRef.current
      if (previousSourceId && previousAccountId) {
        try {
          await database.disconnect(previousAccountId, previousSourceId)
        } catch {
          await database.disconnect(accountId, registered.sourceId).catch(() => undefined)
          throw new Error("Failed to replace the previous folder selection")
        }
      }

      const nextSelection = safeSelection(registered)
      sourceIdRef.current = registered.sourceId
      sourceAccountIdRef.current = accountId
      setSelection(nextSelection)
      return nextSelection
    } catch (caughtError) {
      const code = caughtError && typeof caughtError === "object" && "code" in caughtError
        ? nativeErrorCode(caughtError)
        : caughtError && typeof caughtError === "object" && "message" in caughtError
          ? "storage_failed"
          : "validation_failed"
      const pickerError = createError(code)
      setError(pickerError)
      return null
    } finally {
      selectingRef.current = false
      setIsSelecting(false)
    }
  }, [accountId, runtime.isTauri, selection])

  useEffect(() => {
    return () => {
      void clearSelection().catch(() => undefined)
    }
  }, [clearSelection])

  return { selection, isSelecting, error, selectFolder, clearSelection, commitSelection }
}
