import { useState } from "react"
import { Link } from "react-router-dom"

import { IssueProviderLogo } from "@/components/issue-tracking/issue-provider-logo"
import { notifyIssueTrackingError } from "@/components/issue-tracking/issue-tracking-feedback"
import { ProjectIssuesSkeleton } from "@/components/projects/project-details-page-skeleton"
import { Button } from "@/components/ui/button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  useLinearProjects,
  useLinearTeams,
  useProjectIssueTracking,
  useUpdateProjectIssueTracking,
} from "@/hooks/use-issue-tracking"
import type { Project } from "@/hooks/use-projects"

function linearConnection(details: { connected_projects: Array<{ provider: string; owner: string; project: string }> } | undefined) {
  return details?.connected_projects.find((item) => item.provider === "linear") ?? null
}

export function ProjectIssueTracking({ project }: { project: Project }) {
  const details = useProjectIssueTracking(project.id)
  const savedLinear = linearConnection(details.data)
  const [selection, setSelection] = useState<{
    teamId: string | null
    projectId: string | null
    hasSelection: boolean
  }>({ teamId: null, projectId: null, hasSelection: false })
  const teams = useLinearTeams(!details.isLoading)
  const selectedTeamId = selection.hasSelection
    ? selection.teamId
    : (savedLinear?.owner ?? null)
  const selectedProjectId = selection.hasSelection
    ? selection.projectId
    : (savedLinear?.project ?? null)
  const projects = useLinearProjects(selectedTeamId, teams.isSuccess)
  const update = useUpdateProjectIssueTracking(project.id)

  function saveLinearDestination() {
    if (!selectedTeamId || !selectedProjectId) return
    update.mutate(
      {
        connected_projects: [
          {
            provider: "linear",
            owner: selectedTeamId,
            project: selectedProjectId,
          },
        ],
      },
      {
        onError: notifyIssueTrackingError,
      },
    )
  }

  function removeLinearDestination() {
    update.mutate(
      { connected_projects: [] },
      {
        onSuccess: () => {
          setSelection({ teamId: null, projectId: null, hasSelection: true })
        },
        onError: notifyIssueTrackingError,
      },
    )
  }

  if (details.isLoading) {
    return <ProjectIssuesSkeleton />
  }

  if (details.isError) {
    return (
      <div className="grid justify-items-start gap-3">
        <p className="text-sm text-muted-foreground">
          We could not load issue-tracker settings.
        </p>
        <Button type="button" variant="outline" onClick={() => void details.refetch()}>
          Try again
        </Button>
      </div>
    )
  }

  const github = details.data?.connected_projects.find(
    (item) => item.provider === "github",
  )

  return (
    <div className="grid gap-6">
      <section className="rounded-lg border border-border bg-card p-5">
        <div className="flex items-center gap-3">
          <IssueProviderLogo provider="github" className="size-5" />
          <div>
            <h2 className="text-sm font-medium">GitHub Issues</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              {github
                ? `${github.owner}/${github.project} is the source repository for this project.`
                : "Local projects do not have a GitHub source repository."}
            </p>
          </div>
        </div>
        {github ? (
          <p className="mt-4 text-xs text-muted-foreground">
            The source repository is managed by Trace and cannot be changed here.
          </p>
        ) : null}
      </section>

      <section className="rounded-lg border border-border bg-card p-5">
        <div className="flex items-center gap-3">
          <IssueProviderLogo provider="linear" className="size-5 text-foreground" />
          <div>
            <h2 className="text-sm font-medium">Linear Issues</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Choose one team and project for issues created from this project’s findings.
            </p>
          </div>
        </div>

        {teams.isLoading ? <ProjectIssuesSkeleton /> : null}
        {teams.isError ? (
          <div className="mt-5 flex flex-wrap items-center gap-3">
            <p className="text-sm text-muted-foreground">
              Connect Linear before choosing a destination.
            </p>
            <Button type="button" variant="outline" render={<Link to="/settings/integrations" />}>
              Open integrations
            </Button>
            {savedLinear ? (
              <Button
                type="button"
                variant="outline"
                disabled={update.isPending}
                onClick={removeLinearDestination}
              >
                Remove Linear destination
              </Button>
            ) : null}
          </div>
        ) : null}
        {teams.data ? (
          <div className="mt-5 grid gap-4 sm:grid-cols-2">
            <label className="grid gap-2 text-sm font-medium">
              Team
              <Select
                value={selectedTeamId}
                onValueChange={(value) => {
                  setSelection({
                    teamId: value,
                    projectId: null,
                    hasSelection: true,
                  })
                }}
              >
                <SelectTrigger className="w-full">
                  <SelectValue>
                    {teams.data.find((team) => team.id === selectedTeamId)?.name ?? "Choose a team"}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {teams.data.map((team) => (
                    <SelectItem key={team.id} value={team.id}>
                      {team.name} ({team.key})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </label>
            <label className="grid gap-2 text-sm font-medium">
              Project
              <Select
                value={selectedProjectId}
                disabled={!selectedTeamId || projects.isLoading || projects.isError}
                onValueChange={(value) =>
                  setSelection({
                    teamId: selectedTeamId,
                    projectId: value,
                    hasSelection: true,
                  })
                }
              >
                <SelectTrigger className="w-full">
                  <SelectValue>
                    {projects.data?.find((item) => item.id === selectedProjectId)?.name ?? "Choose a project"}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {projects.data?.map((item) => (
                    <SelectItem key={item.id} value={item.id}>
                      {item.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </label>
          </div>
        ) : null}

        {projects.isError ? (
          <p className="mt-3 text-sm text-destructive">
            We could not load Linear projects for that team.
          </p>
        ) : null}
        {teams.data ? (
          <div className="mt-5 flex flex-wrap gap-2">
            <Button
              type="button"
              disabled={!selectedTeamId || !selectedProjectId || update.isPending}
              onClick={saveLinearDestination}
            >
              {update.isPending ? "Saving…" : "Save Linear destination"}
            </Button>
            {savedLinear ? (
              <Button
                type="button"
                variant="outline"
                disabled={update.isPending}
                onClick={removeLinearDestination}
              >
                Remove Linear destination
              </Button>
            ) : null}
          </div>
        ) : null}
      </section>
    </div>
  )
}
