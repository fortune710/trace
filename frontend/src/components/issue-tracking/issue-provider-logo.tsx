import { Github } from "@/components/logos/github"
import { Linear } from "@/components/logos/linear"
import type { IssueProviderName } from "@/lib/api"

export function IssueProviderLogo({
  provider,
  className = "size-4",
}: {
  provider: IssueProviderName
  className?: string
}) {
  return (
    <span
      aria-hidden="true"
      className={`flex shrink-0 items-center justify-center overflow-hidden rounded-sm ${
        provider === "github" ? "bg-foreground" : "bg-white"
      } ${className}`}
    >
      {provider === "github" ? (
        <Github className="size-3/5 text-background" />
      ) : (
        <Linear className="size-3/5" />
      )}
    </span>
  )
}
