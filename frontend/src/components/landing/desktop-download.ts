export const DEFAULT_DESKTOP_DOWNLOAD_URL =
  "https://github.com/fortune710/trace/releases/latest"

export function resolveDesktopDownloadUrl(
  override: string | undefined = import.meta.env.VITE_DESKTOP_DOWNLOAD_URL,
): string {
  const trimmed = override?.trim()

  if (!trimmed) {
    return DEFAULT_DESKTOP_DOWNLOAD_URL
  }

  try {
    const url = new URL(trimmed)

    if (url.protocol === "https:") {
      return url.toString()
    }
  } catch {
    return DEFAULT_DESKTOP_DOWNLOAD_URL
  }

  return DEFAULT_DESKTOP_DOWNLOAD_URL
}
