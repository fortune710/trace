export function sourceFiles(value: string) {
  const normalized = value.trim().replace(/^\[|\]$/g, "");

  return [
    ...new Set(
      normalized
        .split(/[\n,;|]+/)
        .map((file) =>
          file
            .trim()
            .replace(/^[-*•]\s+/, "")
            .replace(/^["']|["']$/g, ""),
        )
        .filter(Boolean),
    ),
  ];
}
