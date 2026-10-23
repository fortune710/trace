import gitlabLogo from "@/assets/gitlab-logo.svg"

export function GitLabIntegrationCard() {
  return (
    <article className="rounded-lg border border-border bg-card p-5 opacity-75">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <span className="flex size-10 items-center justify-center rounded-md bg-secondary text-foreground">
            <img alt="" aria-hidden="true" className="h-5 w-[21px] object-contain" src={gitlabLogo} />
          </span>
          <div>
            <h2 className="text-sm font-medium">GitLab</h2>
            <p className="mt-1 text-sm text-muted-foreground">Import repositories and branches from GitLab.</p>
          </div>
        </div>
        <span className="shrink-0 rounded-full border border-border px-2 py-1 text-[11px] text-muted-foreground">
          Coming soon
        </span>
      </div>
    </article>
  )
}
