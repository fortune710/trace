// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { ProjectDetailsPage } from "@/app/projects/project-details-page"
import { useProject } from "@/hooks/use-projects"
import { useProjectReviews } from "@/hooks/use-reviews"
import type { Project, Review } from "@/lib/api"

vi.mock("@/hooks/use-projects", () => ({ useProject: vi.fn() }))
vi.mock("@/hooks/use-reviews", () => ({ useProjectReviews: vi.fn() }))
vi.mock("@/components/findings/review-findings", () => ({
  ReviewFindings: ({ review }: { review: Review }) => (
    <p>Findings for {review.id}</p>
  ),
}))
vi.mock("@/components/layout/app-shell", () => ({
  AppShell: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))
vi.mock("@/components/reviews/review-submission-dialog", () => ({
  ReviewSubmissionDialog: ({ open }: { open: boolean }) =>
    open ? (
      <div role="dialog" aria-label="Start review dialog" />
    ) : null,
}))

const project: Project = {
  id: "project-a",
  name: "Trace",
  source: "github",
  external_repository_id: "123",
  external_repository_connection_id: "connection-a",
  repository_owner: "fortune710",
  repository_name: "trace",
  branch_name: "main",
  repository_visibility: "private",
  imported_at: "2026-10-21T00:00:00Z",
  source_hash: null,
  current_revision: "a".repeat(40),
  category: "productivity",
  auto_create_pull_requests: false,
  created_at: "2026-10-21T00:00:00Z",
  updated_at: "2026-10-21T00:00:00Z",
  archived_at: null,
}

const review: Review = {
  id: "review-a",
  project_id: "project-a",
  source_revision: "a".repeat(40),
  source_snapshot: {
    source_kind: "github",
    source_identifier: "123",
    integrity_algorithm: "git-commit-sha1-v1",
    revision: "a".repeat(40),
    captured_at: "2026-10-21T00:00:00Z",
  },
  status: "queued",
  started_at: null,
  completed_at: null,
  created_at: "2026-10-21T00:00:00Z",
  updated_at: "2026-10-21T00:00:00Z",
  agents: [],
}

const mockedUseProject = vi.mocked(useProject)
const mockedUseProjectReviews = vi.mocked(useProjectReviews)

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/projects/project-a"]}>
      <Routes>
        <Route
          path="/projects/:projectId"
          element={<ProjectDetailsPage />}
        />
      </Routes>
    </MemoryRouter>,
  )
}

describe("ProjectDetailsPage", () => {
  beforeEach(() => {
    mockedUseProject.mockReturnValue({
      data: project,
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useProject>)
    mockedUseProjectReviews.mockReturnValue({
      data: { items: [review], next_offset: null },
      isLoading: false,
      isError: false,
      isFetching: false,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useProjectReviews>)
  })

  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it("shows project details, review history, and the start review action", () => {
    renderPage()

    expect(screen.getByRole("navigation", { name: "breadcrumb" })).toBeTruthy()
    expect(screen.getByRole("link", { name: "Projects" }).getAttribute("href")).toBe("/projects")
    expect(screen.getByText("Trace", { selector: "[aria-current=page]" })).toBeTruthy()
    expect(screen.getByRole("heading", { name: "Trace" })).toBeTruthy()
    expect(screen.getByText("fortune710/trace")).toBeTruthy()
    expect(screen.getByText("main")).toBeTruthy()
    expect(screen.getByRole("link", { name: /review review-a/i }).getAttribute("href")).toBe(
      "/reviews/review-a",
    )
    expect(mockedUseProjectReviews).toHaveBeenCalledWith("project-a", 1)

    fireEvent.click(screen.getByRole("button", { name: "Start review" }))
    expect(screen.getByRole("dialog", { name: "Start review dialog" })).toBeTruthy()
  })

  it("switches to the selected review's findings tab", () => {
    renderPage()

    fireEvent.click(screen.getByRole("tab", { name: "Findings" }))

    expect(screen.getByRole("tabpanel", { name: "Findings" })).toBeTruthy()
    expect(screen.getByText("Findings for review-a")).toBeTruthy()
    expect(screen.queryByRole("link", { name: /review review-a/i })).toBeNull()
  })

  it("uses the API project ID for a desktop-cached project", () => {
    mockedUseProject.mockReturnValue({
      data: { ...project, id: "api:account-a:project-a", api_project_id: "project-a" },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useProject>)

    renderPage()

    expect(mockedUseProjectReviews).toHaveBeenCalledWith("project-a", 1)
  })

  it("moves through review history pages", () => {
    mockedUseProjectReviews.mockReturnValue({
      data: { items: [review], next_offset: 10 },
      isLoading: false,
      isError: false,
      isFetching: false,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useProjectReviews>)

    renderPage()
    fireEvent.click(screen.getByRole("button", { name: "Next" }))

    expect(mockedUseProjectReviews).toHaveBeenCalledWith("project-a", 2)
  })

  it("shows a review-load error instead of an empty state after a failed refetch", () => {
    mockedUseProjectReviews.mockReturnValue({
      data: { items: [], next_offset: null },
      isLoading: false,
      isError: true,
      isFetching: false,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useProjectReviews>)

    renderPage()

    expect(screen.getByText("We could not load this project’s reviews.")).toBeTruthy()
    expect(screen.queryByText("No reviews yet")).toBeNull()
  })
})
