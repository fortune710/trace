// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { FindingDetailsPage } from "@/app/findings/finding-details-page"
import { useFinding } from "@/hooks/use-findings"
import { useProject } from "@/hooks/use-projects"
import { useReview } from "@/hooks/use-reviews"
import type { Finding, Project, Review } from "@/lib/api"

vi.mock("@/hooks/use-findings", () => ({ useFinding: vi.fn() }))
vi.mock("@/hooks/use-projects", () => ({ useProject: vi.fn() }))
vi.mock("@/hooks/use-reviews", () => ({ useReview: vi.fn() }))
vi.mock("@/components/layout/app-shell", () => ({
  AppShell: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

const finding: Finding = {
  id: "finding-a",
  review_id: "review-a",
  agent_id: "agent-a",
  reviewing_agent: {
    assignment_id: "assignment-a",
    agent_id: "agent-a",
    display_name: "Security Scout",
    specialization: "security",
  },
  category: "security",
  severity: "high",
  title: "Unsafe redirect destination allows attackers to take over user sessions",
  explanation: "The redirect destination is not validated.",
  evidence: "next=https://untrusted.example",
  source_location: "src/auth/redirect.ts:24",
  recommendation: "Allow only trusted relative destinations.",
  status: "open",
  created_at: "2026-10-26T00:00:00Z",
  updated_at: "2026-10-26T00:00:00Z",
}

const mockedUseFinding = vi.mocked(useFinding)
const mockedUseProject = vi.mocked(useProject)
const mockedUseReview = vi.mocked(useReview)

const project = {
  id: "project-a",
  name: "Trace",
} as Project

const review = {
  id: "review-a",
  project_id: "project-a",
} as Review

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/reviews/review-a/findings/finding-a"]}>
      <Routes>
        <Route
          path="/reviews/:reviewId/findings/:findingId"
          element={<FindingDetailsPage />}
        />
      </Routes>
    </MemoryRouter>,
  )
}

describe("FindingDetailsPage", () => {
  beforeEach(() => {
    mockedUseProject.mockReturnValue({
      data: project,
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useProject>)
    mockedUseReview.mockReturnValue({
      data: review,
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useReview>)
    mockedUseFinding.mockReturnValue({
      data: finding,
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useFinding>)
  })

  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it("renders a finding breadcrumb and finding details", () => {
    renderPage()

    expect(screen.getByRole("navigation", { name: "breadcrumb" })).toBeTruthy()
    expect(screen.getByRole("link", { name: "Projects" }).getAttribute("href")).toBe("/projects")
    expect(screen.getByRole("link", { name: "Trace" }).getAttribute("href")).toBe(
      "/projects/project-a",
    )
    expect(screen.getByRole("link", { name: "Review review-a" }).getAttribute("href")).toBe(
      "/reviews/review-a?tab=findings",
    )
    const breadcrumbPage = document.querySelector("[aria-current=page]")
    expect(breadcrumbPage?.textContent).toBe(`${finding.title.slice(0, 49)}…`)
    expect(breadcrumbPage?.textContent).toHaveLength(50)
    expect(breadcrumbPage?.getAttribute("title")).toBe(finding.title)
    expect(screen.getByRole("heading", { name: finding.title })).toBeTruthy()
    expect(screen.getByText(/Security Scout/)).toBeTruthy()
  })
})
