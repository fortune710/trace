import { Github } from "@/components/logos/github"
import { Linear } from "@/components/logos/linear"
import type { IssueProviderName } from "@/lib/api"

export function IssueProviderLogo({
  provider,
  className = "size-4",
  iconClassName = "size-3/5",
}: {
  provider: IssueProviderName
  className?: string
  iconClassName?: string
}) {
  return (
    <span
      aria-hidden="true"
      className={`flex shrink-0 items-center justify-center overflow-hidden rounded-sm ${
        provider === "github" ? "bg-foreground" : "bg-white"
      } ${className}`}
    >
      {provider === "github" ? (
        <Github className={`${iconClassName} text-background`} />
      ) : (
        <Linear className={iconClassName} />
      )}
    </span>
  )
}
