import { GitHubIntegrationCard } from "@/components/integrations/github-integration-card"
import { GitLabIntegrationCard } from "@/components/integrations/gitlab-integration-card"
import { AppShell } from "@/components/layout/app-shell"
import { useGitHubCallbackToast } from "@/hooks/use-github-callback-toast"

export function IntegrationsPage() {
  useGitHubCallbackToast()

  return (
    <AppShell>
      <section className="mx-auto w-full max-w-6xl px-6 py-8 md:px-10 md:py-10">
        <h1 className="text-xl font-medium tracking-tight">Integrations</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Connect the services Trace uses to import and review your code.
        </p>
        <div className="mt-8 grid gap-4 md:grid-cols-2">
          <GitHubIntegrationCard />
          <GitLabIntegrationCard />
        </div>
      </section>
    </AppShell>
  )
}
