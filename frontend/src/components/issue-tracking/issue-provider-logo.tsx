import githubLogo from "@/assets/github-invertocat-white.svg"
import linearLogo from "@/assets/linear-logo.svg"
import type { IssueProviderName } from "@/lib/api"

const providerLogos = {
  github: githubLogo,
  linear: linearLogo,
} satisfies Record<IssueProviderName, string>

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
      <img
        alt=""
        className="size-3/5 object-contain"
        src={providerLogos[provider]}
      />
    </span>
  )
}
