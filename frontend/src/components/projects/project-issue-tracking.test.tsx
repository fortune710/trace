// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { afterEach, describe, expect, it, vi } from "vitest"

import { ProjectIssueTracking } from "@/components/projects/project-issue-tracking"
import {
  useLinearProjects,
  useLinearTeams,
  useProjectIssueTracking,
  useUpdateProjectIssueTracking,
} from "@/hooks/use-issue-tracking"
import { useGitHubConnection } from "@/hooks/use-github-connection"
import type { Project } from "@/lib/api"

vi.mock("@/hooks/use-issue-tracking", () => ({
  useLinearProjects: vi.fn(),
  useLinearTeams: vi.fn(),
  useProjectIssueTracking: vi.fn(),
  useUpdateProjectIssueTracking: vi.fn(),
}))
vi.mock("@/hooks/use-github-connection", () => ({
  useGitHubConnection: vi.fn(),
}))
vi.mock("@/components/issue-tracking/issue-tracking-feedback", () => ({
  notifyIssueTrackingError: vi.fn(),
}))

const project: Project = {
  id: "project-a",
  name: "Trace",
  source: "github",
  external_repository_id: "repo-a",
  external_repository_connection_id: "connection-a",
  repository_owner: "acme",
  repository_name: "trace",
  branch_name: "main",
  repository_visibility: "private",
  imported_at: null,
  source_hash: null,
  current_revision: null,
  category: "productivity",
  auto_create_pull_requests: false,
  created_at: "2026-10-27T00:00:00Z",
  updated_at: "2026-10-27T00:00:00Z",
  archived_at: null,
}

describe("ProjectIssueTracking", () => {
  afterEach(cleanup)

  it("shows connected GitHub and Linear project details", () => {
    const mutate = vi.fn()
    vi.mocked(useProjectIssueTracking).mockReturnValue({
      data: {
        connected_projects: [
          { provider: "github", owner: "acme", project: "trace" },
          { provider: "linear", owner: "team-a", project: "project-a" },
        ],
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useProjectIssueTracking>)
    vi.mocked(useLinearTeams).mockReturnValue({
      data: [{ id: "team-a", name: "Engineering", key: "ENG" }],
      isLoading: false,
      isError: false,
      isSuccess: true,
    } as unknown as ReturnType<typeof useLinearTeams>)
    vi.mocked(useLinearProjects).mockReturnValue({
      data: [{ id: "project-a", name: "Trace" }],
      isLoading: false,
      isError: false,
    } as unknown as ReturnType<typeof useLinearProjects>)
    vi.mocked(useUpdateProjectIssueTracking).mockReturnValue({
      mutate,
      isPending: false,
    } as unknown as ReturnType<typeof useUpdateProjectIssueTracking>)
    vi.mocked(useGitHubConnection).mockReturnValue({
      data: { status: "connected" },
    } as ReturnType<typeof useGitHubConnection>)

    render(
      <MemoryRouter>
        <ProjectIssueTracking project={project} />
      </MemoryRouter>,
    )

    expect(screen.getByRole("heading", { name: "GitHub Issues" })).toBeTruthy()
    expect(screen.getByRole("heading", { name: "Linear Issues" })).toBeTruthy()
    expect(screen.getByText("Repository")).toBeTruthy()
    expect(screen.getByText("acme/trace", { selector: "dd" })).toBeTruthy()
    expect(screen.getByText("Project", { selector: "dt" })).toBeTruthy()
    expect(
      screen.getByText("Engineering/Trace", { selector: "dd" }),
    ).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "Remove Linear destination" }))
    expect(mutate).toHaveBeenCalledWith(
      { connected_projects: [] },
      expect.any(Object),
    )
  })

  it("offers provider-specific connection actions when integrations are unavailable", () => {
    vi.mocked(useProjectIssueTracking).mockReturnValue({
      data: { connected_projects: [] },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useProjectIssueTracking>)
    vi.mocked(useLinearTeams).mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      isSuccess: false,
    } as unknown as ReturnType<typeof useLinearTeams>)
    vi.mocked(useLinearProjects).mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: false,
    } as unknown as ReturnType<typeof useLinearProjects>)
    vi.mocked(useUpdateProjectIssueTracking).mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as unknown as ReturnType<typeof useUpdateProjectIssueTracking>)
    vi.mocked(useGitHubConnection).mockReturnValue({
      data: { status: "never_connected" },
    } as ReturnType<typeof useGitHubConnection>)

    render(
      <MemoryRouter>
        <ProjectIssueTracking project={project} />
      </MemoryRouter>,
    )

    expect(screen.getByText("Repository", { selector: "dt" })).toBeTruthy()
    expect(screen.getByText("Project", { selector: "dt" })).toBeTruthy()
    expect(screen.getByRole("button", { name: "Connect to GitHub" }).getAttribute("href")).toBe(
      "/settings/integrations",
    )
    expect(screen.getByRole("button", { name: "Connect to Linear" }).getAttribute("href")).toBe(
      "/settings/integrations",
    )
  })
})
