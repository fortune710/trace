import { useDesktopProjectSync } from "@/hooks/use-desktop-project-sync"

export function DesktopProjectBootstrap() {
  useDesktopProjectSync()
  return null
}
