import { useEffect, useRef } from "react"

/**
 * Fire `onOpen` once per entity id while this component stays mounted.
 * Polling or status refreshes for the same id must not re-fire.
 */
export function useTrackEntityOpened(
  entityId: string | undefined | null,
  onOpen: (id: string) => void,
) {
  const capturedId = useRef<string | null>(null)

  useEffect(() => {
    if (!entityId) return
    if (capturedId.current === entityId) return
    capturedId.current = entityId
    onOpen(entityId)
  }, [entityId, onOpen])
}
