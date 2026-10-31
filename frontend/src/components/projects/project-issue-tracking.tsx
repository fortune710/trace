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
import { useGitHubConnection } from "@/hooks/use-github-connection"
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
  const githubConnection = useGitHubConnection()
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
  const githubIsConnected =
    githubConnection.data?.status === "connected" && Boolean(github)
  const selectedTeam = teams.data?.find((team) => team.id === selectedTeamId)
  const selectedProject = projects.data?.find(
    (item) => item.id === selectedProjectId,
  )

  return (
    <div className="grid max-w-4xl gap-12">
      <section aria-labelledby="github-issues-heading">
        <h2
          id="github-issues-heading"
          className="flex items-center gap-3 text-xl font-medium tracking-tight"
        >
          <IssueProviderLogo
            provider="github"
            className="size-6"
            iconClassName="size-4/5"
          />
          GitHub Issues
        </h2>
        <p className="mt-0 text-base text-muted-foreground">
          Create GitHub issues from this project’s findings.
        </p>
        <div className="mt-4 rounded-lg border border-white/6 bg-card p-4">
          <dl className="flex flex-wrap items-center justify-between gap-3">
            <dt className="text-sm text-muted-foreground">Repository</dt>
            <dd className="min-w-0 break-all text-right text-sm font-medium">
              {githubIsConnected && github ? (
                <>{github.owner}/{github.project}</>
              ) : (
                <Button
                  type="button"
                  nativeButton={false}
                  render={<Link to="/settings/integrations" />}
                >
                  Connect to GitHub
                </Button>
              )}
            </dd>
          </dl>
        </div>
      </section>

      <section aria-labelledby="linear-issues-heading">
        <h2
          id="linear-issues-heading"
          className="flex items-center gap-3 text-xl font-medium tracking-tight"
        >
          <IssueProviderLogo
            provider="linear"
            className="size-6 text-foreground"
            iconClassName="size-4/5"
          />
          Linear Issues
        </h2>
        <p className="mt-0 text-base text-muted-foreground">
          Choose a Linear team and project for issues created from this project’s findings.
        </p>
        <div className="mt-4 rounded-lg border border-white/6 bg-card p-4">
          {teams.isLoading ? <ProjectIssuesSkeleton /> : null}
          {teams.isError ? (
            <>
              <dl className="flex flex-wrap items-center justify-between gap-3">
                <dt className="text-sm text-muted-foreground">Project</dt>
                <dd className="min-w-0 break-all text-right text-sm font-medium">
                  {savedLinear ? (
                    <>{savedLinear.owner}/{savedLinear.project}</>
                  ) : (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="px-2"
                      nativeButton={false}
                      render={<Link to="/settings/integrations" />}
                    >
                      Connect to Linear
                    </Button>
                  )}
                </dd>
              </dl>
              {savedLinear ? (
                <div className="mt-4 flex justify-end">
                  <Button
                    type="button"
                    variant="outline"
                    disabled={update.isPending}
                    onClick={removeLinearDestination}
                  >
                    Remove Linear destination
                  </Button>
                </div>
              ) : null}
            </>
          ) : null}
          {teams.data ? (
            <>
              <dl className="flex flex-wrap items-center justify-between gap-3">
                <dt className="text-sm text-muted-foreground">Project</dt>
                <dd className="min-w-0 break-all text-right text-sm font-medium">
                  {savedLinear ? (
                    <>
                      {selectedTeam?.name ?? selectedTeamId}/
                      {selectedProject?.name ?? selectedProjectId}
                    </>
                  ) : (
                    "Not configured"
                  )}
                </dd>
              </dl>
              <div
                className="mt-5 grid gap-4 border-t border-border pt-4 sm:grid-cols-2"
              >
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
                    disabled={
                      !selectedTeamId || projects.isLoading || projects.isError
                    }
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
                        {projects.data?.find(
                          (item) => item.id === selectedProjectId,
                        )?.name ?? "Choose a project"}
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
              {projects.isError ? (
                <p className="mt-3 text-sm text-destructive">
                  We could not load Linear projects for that team.
                </p>
              ) : null}
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
            </>
          ) : null}
        </div>
      </section>
    </div>
  )
}
