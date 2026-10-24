import { useState } from "react"

import { AgentDialog } from "@/components/agents/agent-dialog"
import { AgentList } from "@/components/agents/agent-list"
import { AppShell } from "@/components/layout/app-shell"
import { Button } from "@/components/ui/button"
import { useAgentModelCatalog, useAgents, useProviderCredentials } from "@/hooks/use-agents"

export function AgentsPage() {
  const [page, setPage] = useState(1)
  const [isCreateOpen, setIsCreateOpen] = useState(false)
  const agents = useAgents(page)
  const catalog = useAgentModelCatalog()
  const credentials = useProviderCredentials()

  return (
    <AppShell>
      <section className="mx-auto w-full max-w-6xl px-6 pt-8 pb-28 md:px-10 md:pt-10">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h1 className="text-xl font-medium tracking-tight">Agents</h1>
            <p className="mt-1 text-sm text-muted-foreground">Configure the reviewers available for your projects.</p>
          </div>
          <Button type="button" onClick={() => setIsCreateOpen(true)}>Create agent</Button>
        </div>
        <div className="mt-8">
          {agents.isLoading ? <p className="text-sm text-muted-foreground">Loading agents…</p> : null}
          {agents.isError ? <Button type="button" variant="outline" onClick={() => void agents.refetch()}>Try again</Button> : null}
          {agents.data ? <>
            <AgentList agents={agents.agents} onCreate={() => setIsCreateOpen(true)} />
            <nav className="fixed right-6 bottom-6 z-20 flex items-center gap-2 md:right-10" aria-label="Agent pagination">
              <Button type="button" variant="outline" size="sm" disabled={page === 1 || agents.isFetching} onClick={() => setPage((current) => current - 1)}>Previous</Button>
              <span className="min-w-16 self-center text-center text-xs text-muted-foreground" aria-live="polite">Page {page}</span>
              <Button type="button" variant="outline" size="sm" disabled={!agents.hasNextPage || agents.isFetching} onClick={() => setPage((current) => current + 1)}>Next</Button>
            </nav>
          </> : null}
        </div>
      </section>
      <AgentDialog
        key={`${isCreateOpen ? "create" : "closed"}-${catalog.data ? "catalog" : "loading"}`}
        open={isCreateOpen}
        agent={null}
        catalog={catalog.data}
        credentials={credentials.credentials}
        onOpenChange={setIsCreateOpen}
      />
    </AppShell>
  )
}
