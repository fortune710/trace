import { isTauri } from "@tauri-apps/api/core"

export type RuntimeEnvironment = {
  kind: "tauri" | "web"
  isTauri: boolean
  isWeb: boolean
}

export function useRuntimeEnvironment(): RuntimeEnvironment {
  const desktop = isTauri()

  return {
    kind: desktop ? "tauri" : "web",
    isTauri: desktop,
    isWeb: !desktop,
  }
}
