export type BuildMode = "web" | "desktop"

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "")
const appMode = import.meta.env.VITE_APP_MODE

export const runtimeConfig = {
  apiBaseUrl,
  appMode: appMode === "desktop" ? "desktop" : "web",
} as const satisfies {
  apiBaseUrl: string
  appMode: BuildMode
}
