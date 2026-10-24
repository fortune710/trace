const absoluteLocalPathPatterns = [
  /(?:^|[\s"'([{])\/(?:Users|private|home|tmp|var|Volumes)\//,
  /[A-Za-z]:\\/,
  /\\\\[A-Za-z0-9._-]+\\/,
]

export function assertPathFree(value: unknown, forbiddenPaths: string[] = []) {
  const serialized = typeof value === "string" ? value : JSON.stringify(value)

  if (!serialized) return

  const containsForbiddenPath = forbiddenPaths.some((path) => serialized.includes(path))
  const containsAbsolutePath = absoluteLocalPathPatterns.some((pattern) => pattern.test(serialized))

  if (containsForbiddenPath || containsAbsolutePath) {
    throw new Error("Value contains an absolute local path")
  }
}
