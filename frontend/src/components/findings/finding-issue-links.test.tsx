// @vitest-environment jsdom

import { render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import { FindingIssueLinks } from "@/components/findings/finding-issue-links"
import { useFindingIssueLinks } from "@/hooks/use-issue-tracking"

vi.mock("@/hooks/use-issue-tracking", () => ({
  useFindingIssueLinks: vi.fn(),
}))

const mockedUseFindingIssueLinks = vi.mocked(useFindingIssueLinks)

describe("FindingIssueLinks", () => {
  it("shows created, pending, and failed links without exposing unsafe URLs", () => {
    mockedUseFindingIssueLinks.mockReturnValue({
      data: [
        {
          id: "github-link",
          finding_id: "finding-a",
          provider: "github",
          destination_id: "acme/trace",
          external_identifier: "#21",
          external_url: "https://github.com/acme/trace/issues/21",
          state: "created",
          failure_code: null,
          created_at: "2026-10-27T00:00:00Z",
          updated_at: "2026-10-27T00:00:00Z",
        },
        {
          id: "linear-link",
          finding_id: "finding-a",
          provider: "linear",
          destination_id: "team/project",
          external_identifier: null,
          external_url: null,
          state: "pending",
          failure_code: null,
          created_at: "2026-10-27T00:00:00Z",
          updated_at: "2026-10-27T00:00:00Z",
        },
        {
          id: "failed-link",
          finding_id: "finding-a",
          provider: "github",
          destination_id: "acme/trace",
          external_identifier: null,
          external_url: null,
          state: "failed",
          failure_code: "authorization",
          created_at: "2026-10-27T00:00:00Z",
          updated_at: "2026-10-27T00:00:00Z",
        },
      ],
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useFindingIssueLinks>)

    render(<FindingIssueLinks findingId="finding-a" />)

    expect(screen.getByRole("heading", { name: "Linked issues" })).toBeTruthy()
    expect(screen.getByRole("link", { name: "#21" }).getAttribute("href")).toBe(
      "https://github.com/acme/trace/issues/21",
    )
    expect(screen.getByText("Pending")).toBeTruthy()
    expect(screen.getByText("Needs attention")).toBeTruthy()
    expect(screen.getByText(/authorization/)).toBeTruthy()
  })
})
