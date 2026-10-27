// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, useLocation } from "react-router-dom"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { ReviewFindings } from "@/components/findings/review-findings"
import { useReviewFindings, useUpdateFindingStatus } from "@/hooks/use-findings"
import type { Finding, Review } from "@/lib/api"

vi.mock("@/hooks/use-findings", () => ({
  useReviewFindings: vi.fn(),
  useUpdateFindingStatus: vi.fn(),
}))

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
  status: "completed",
  started_at: "2026-10-21T00:00:00Z",
  completed_at: "2026-10-21T00:01:00Z",
  created_at: "2026-10-21T00:00:00Z",
  updated_at: "2026-10-21T00:01:00Z",
  agents: [
    {
      assignment_id: "assignment-a",
      agent_id: "agent-a",
      name: "Security Scout",
      review_category: "security",
      model_provider: "openai",
      model_name: "gpt-5.1",
      personality: null,
      skills: [],
      configuration_version: 1,
      status: "completed",
      assigned_at: "2026-10-21T00:00:00Z",
      started_at: "2026-10-21T00:00:00Z",
      completed_at: "2026-10-21T00:01:00Z",
    },
  ],
}

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
  title: "Missing authorization check",
  explanation: "A route does not verify the caller's organization.",
  evidence: null,
  source_location: [
    "backend/routes.py:42",
    "frontend/src/app.tsx:10",
    "frontend/src/lib/api.ts:82",
    "frontend/src/hooks/use-auth.ts:48",
  ].join("\n"),
  recommendation: null,
  status: "open",
  status_changed_at: null,
  triage_reason: null,
  created_at: "2026-10-21T00:00:00Z",
  updated_at: "2026-10-21T00:00:00Z",
}

const mockedUseReviewFindings = vi.mocked(useReviewFindings)
const mockedUseUpdateFindingStatus = vi.mocked(useUpdateFindingStatus)
const mutate = vi.fn()

function LocationProbe() {
  const location = useLocation()
  return <output data-testid="location">{location.search}</output>
}

function renderFindings(initialEntry = "/reviews/review-a?tab=findings") {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <LocationProbe />
      <ReviewFindings review={review} />
    </MemoryRouter>,
  )
}

describe("ReviewFindings", () => {
  beforeEach(() => {
    mockedUseReviewFindings.mockReturnValue({
      data: { items: [finding], next_offset: null },
      isLoading: false,
      isError: false,
      isFetching: false,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useReviewFindings>)
    mockedUseUpdateFindingStatus.mockReturnValue({
      mutate,
      isPending: false,
      isError: false,
      variables: undefined,
      error: null,
    } as unknown as ReturnType<typeof useUpdateFindingStatus>)
  })

  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it("uses URL-backed filters and shows reviewer details", () => {
    renderFindings("/reviews/review-a?tab=findings&finding_severity=high")

    expect(mockedUseReviewFindings).toHaveBeenCalledWith("review-a", 1, {
      category: undefined,
      severity: "high",
      status: undefined,
      agentId: undefined,
      excludeStatus: "dismissed",
    })
    expect(screen.getByText("Missing authorization check")).toBeTruthy()
    expect(screen.getByText("Security Scout")).toBeTruthy()
    expect(
      screen.getByText("backend/routes.py:42").getAttribute("data-slot"),
    ).toBe("badge")
    expect(screen.getByText("frontend/src/lib/api.ts:82")).toBeTruthy()
    expect(screen.getByText("+1").getAttribute("title")).toBe(
      "1 additional source file",
    )
    expect(screen.queryByText("frontend/src/hooks/use-auth.ts:48")).toBeNull()
    expect(
      screen.getByRole("link", { name: "View finding" }).getAttribute("href"),
    ).toBe("/reviews/review-a/findings/finding-a")

    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }))

    expect(screen.getByTestId("location").textContent).toBe("?tab=findings")
  })

  it("ignores invalid enum filters from the URL", () => {
    renderFindings(
      "/reviews/review-a?tab=findings&finding_category=unknown&finding_severity=urgent&finding_status=pending&finding_agent=agent-a",
    )

    expect(mockedUseReviewFindings).toHaveBeenCalledWith("review-a", 1, {
      category: undefined,
      severity: undefined,
      status: undefined,
      agentId: "agent-a",
      excludeStatus: "dismissed",
    })
  })

  it("ignores a reviewer filter that is not assigned to the review", () => {
    renderFindings("/reviews/review-a?tab=findings&finding_agent=agent-other")

    expect(mockedUseReviewFindings).toHaveBeenCalledWith("review-a", 1, {
      category: undefined,
      severity: undefined,
      status: undefined,
      agentId: undefined,
      excludeStatus: "dismissed",
    })
    expect(
      screen.getByRole("combobox", { name: "Reviewer" }).textContent,
    ).toContain("All reviewers")
  })

  it("retries after a finding query failure", () => {
    const refetch = vi.fn()
    mockedUseReviewFindings.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      isFetching: false,
      refetch,
    } as unknown as ReturnType<typeof useReviewFindings>)

    renderFindings()

    expect(screen.getByText("We could not load these findings.")).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "Try again" }))
    expect(refetch).toHaveBeenCalledTimes(1)
  })

  it("shows an empty filtered state and moves through URL-backed pages", () => {
    mockedUseReviewFindings.mockReturnValue({
      data: { items: [], next_offset: 25 },
      isLoading: false,
      isError: false,
      isFetching: false,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useReviewFindings>)

    renderFindings(
      "/reviews/review-a?tab=findings&finding_category=engineering",
    )

    expect(screen.getByText("No findings match these filters")).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "Next" }))
    expect(screen.getByTestId("location").textContent).toBe(
      "?tab=findings&finding_category=engineering&finding_page=2",
    )
  })

  it("uses the shared empty state when a review has no findings", () => {
    mockedUseReviewFindings.mockReturnValue({
      data: { items: [], next_offset: null },
      isLoading: false,
      isError: false,
      isFetching: false,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useReviewFindings>)

    renderFindings()

    expect(screen.getByText("No findings for this review")).toBeTruthy()
    expect(
      screen.getByText(
        "The reviewers did not report any findings for this review.",
      ),
    ).toBeTruthy()
    expect(document.querySelector("[data-slot=empty]")).toBeTruthy()
  })

  it("writes filter selections to the URL before querying the next result set", async () => {
    renderFindings()

    const user = userEvent.setup()
    await user.click(screen.getByRole("combobox", { name: "Status" }))
    await user.click(await screen.findByRole("option", { name: "resolved" }))

    expect(screen.getByTestId("location").textContent).toBe(
      "?tab=findings&finding_status=resolved",
    )
    expect(mockedUseReviewFindings).toHaveBeenNthCalledWith(
      mockedUseReviewFindings.mock.calls.length - 1,
      "review-a",
      1,
      {
        category: undefined,
        severity: undefined,
        status: "resolved",
        agentId: undefined,
      },
    )
  })

  it("offers open-finding triage actions and lazily loads dismissed findings", () => {
    renderFindings()

    fireEvent.change(screen.getByLabelText("Decision reason optional"), {
      target: { value: "Risk accepted for the current release." },
    })
    fireEvent.click(screen.getByRole("button", { name: "Accept" }))
    expect(mutate).toHaveBeenCalledWith({
      findingId: "finding-a",
      status: "accepted",
      reason: "Risk accepted for the current release.",
    })

    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }))
    expect(mutate).toHaveBeenCalledWith({
      findingId: "finding-a",
      status: "dismissed",
      reason: "Risk accepted for the current release.",
    })

    fireEvent.click(
      screen.getByRole("button", { name: "Show dismissed findings" }),
    )
    expect(mockedUseReviewFindings).toHaveBeenLastCalledWith(
      "review-a",
      1,
      { status: "dismissed" },
      true,
    )
  })
})
