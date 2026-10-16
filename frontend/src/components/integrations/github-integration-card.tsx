import { useMutation } from "@tanstack/react-query"

import githubLogo from "@/assets/github-invertocat-white.svg"
import { Button } from "@/components/ui/button"
import { toast } from "@/components/ui/toast"
import { useGitHubConnection } from "@/hooks/use-github-connection"
import { ApiError, authApi, type GitHubConnectionStatus } from "@/lib/api"

const statusCopy: Record<
  GitHubConnectionStatus,
  { badgeClassName: string; label: string; description: string }
> = {
  connected: {
    badgeClassName: "border-emerald-400/25 bg-emerald-500/15 text-emerald-300",
    label: "Connected",
    description: "GitHub repositories are available to import.",
  },
  never_connected: {
    badgeClassName: "border-red-400/25 bg-red-500/15 text-red-300",
    label: "Not connected",
    description: "Connect GitHub to import a repository into Trace.",
  },
  needs_reconnection: {
    badgeClassName: "border-amber-400/25 bg-amber-500/15 text-amber-300",
    label: "Reconnect required",
    description: "Your GitHub authorization needs to be refreshed before you can import repositories.",
  },
}

function errorMessage(error: unknown) {
  return error instanceof ApiError
    ? error.message
    : "Unable to start the GitHub connection. Please try again."
}

export function GitHubIntegrationCard() {
  const connection = useGitHubConnection()
  const connect = useMutation({
    mutationFn: authApi.beginGitHubConnection,
    onSuccess: ({ authorization_url }) => {
      window.location.assign(authorization_url)
    },
    onError: (error) => {
      toast.add({
        type: "error",
        title: "GitHub connection could not start",
        description: errorMessage(error),
      })
    },
  })

  const status = connection.data?.status
  const copy = status ? statusCopy[status] : null
  const actionLabel = status === "never_connected" ? "Connect GitHub" : "Reconnect"
  const isConnectionStarting = connect.isPending || connect.isSuccess

  return (
    <article className="rounded-lg border border-border bg-card p-5">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <span className="flex size-10 items-center justify-center rounded-md bg-secondary text-foreground">
            <img alt="" aria-hidden="true" className="h-5 w-[21px] object-contain" src={githubLogo} />
          </span>
          <div>
            <h2 className="text-sm font-medium">GitHub</h2>
            <p className="mt-1 text-sm text-muted-foreground">Import repositories and branches from GitHub.</p>
          </div>
        </div>
        {copy ? (
          <span className={`shrink-0 rounded-full border px-2 py-1 text-[11px] ${copy.badgeClassName}`}>
            {copy.label}
          </span>
        ) : null}
      </div>

      <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4">
        <p className="text-sm text-muted-foreground">
          {connection.isPending ? "Checking GitHub connection…" : copy?.description}
        </p>
        {connection.isError ? (
          <Button size="sm" type="button" variant="outline" onClick={() => void connection.refetch()}>
            Try again
          </Button>
        ) : (
          <Button size="sm" type="button" disabled={connection.isPending || isConnectionStarting} onClick={() => connect.mutate()}>
            {isConnectionStarting ? "Connecting…" : actionLabel}
          </Button>
        )}
      </div>
      {connection.isError ? (
        <p className="mt-3 text-sm text-destructive" role="status">
          We could not check your GitHub connection. Try again shortly.
        </p>
      ) : null}
    </article>
  )
}
