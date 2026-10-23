import { useEffect, useRef } from "react"

export function useShortcut({
  enabled = true,
  key,
  onTrigger,
}: {
  enabled?: boolean
  key: string
  onTrigger: () => void
}) {
  const onTriggerRef = useRef(onTrigger)

  useEffect(() => {
    onTriggerRef.current = onTrigger
  }, [onTrigger])

  useEffect(() => {
    if (!enabled) return

    function handleKeyDown(event: KeyboardEvent) {
      if (event.repeat || event.altKey || event.key.toLowerCase() !== key.toLowerCase()) return
      if (!event.metaKey && !event.ctrlKey) return
      event.preventDefault()
      onTriggerRef.current()
    }

    window.addEventListener("keydown", handleKeyDown)
    return () => window.removeEventListener("keydown", handleKeyDown)
  }, [enabled, key])
}
