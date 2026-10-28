import type { IssueProviderName } from "@/lib/api"

const providerLabels = {
  github: "GitHub",
  linear: "Linear",
} satisfies Record<IssueProviderName, string>

export function issueProviderLabel(provider: IssueProviderName) {
  return providerLabels[provider]
}
