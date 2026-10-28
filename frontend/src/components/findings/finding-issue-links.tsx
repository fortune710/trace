import { IssueProviderLogo } from "@/components/issue-tracking/issue-provider-logo"
import { issueProviderLabel } from "@/components/issue-tracking/issue-provider"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { useFindingIssueLinks } from "@/hooks/use-issue-tracking"
import type { IssueLinkState } from "@/lib/api"

const stateLabel: Record<IssueLinkState, string> = {
  pending: "Pending",
  created: "Created",
  failed: "Needs attention",
}

export function FindingIssueLinks({ findingId }: { findingId: string }) {
  const links = useFindingIssueLinks(findingId)

  if (links.isLoading) {
    return <Skeleton className="mt-6 h-20 w-full" />
  }

  if (links.isError) {
    return (
      <section className="mt-6 grid justify-items-start gap-3">
        <p className="text-sm text-muted-foreground">
          We could not load linked issues.
        </p>
        <Button type="button" variant="outline" onClick={() => void links.refetch()}>
          Try again
        </Button>
      </section>
    )
  }

  if (!links.data?.length) {
    return null
  }

  return (
    <section className="mt-6" aria-labelledby="linked-issues-heading">
      <h2 id="linked-issues-heading" className="text-base font-medium tracking-tight">
        Linked issues
      </h2>
      <ul className="mt-3 grid gap-2">
        {links.data.map((link) => (
          <li
            key={link.id}
            className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-muted/20 px-4 py-3 text-sm"
          >
            <div className="flex min-w-0 items-center gap-2">
              <IssueProviderLogo provider={link.provider} />
              <span>{issueProviderLabel(link.provider)}</span>
              <span className="text-muted-foreground">·</span>
              <span className="text-muted-foreground">{stateLabel[link.state]}</span>
              {link.failure_code ? (
                <span className="text-muted-foreground">· {link.failure_code}</span>
              ) : null}
            </div>
            {link.state === "created" && link.external_url && link.external_identifier ? (
              <a
                className="font-medium text-primary underline-offset-4 hover:underline"
                href={link.external_url}
                rel="noreferrer"
                target="_blank"
              >
                {link.external_identifier}
              </a>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  )
}
