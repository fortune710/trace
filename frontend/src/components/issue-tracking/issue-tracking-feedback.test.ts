import { describe, expect, it, vi } from "vitest"

import {
  notifyIssueCreation,
  notifyIssueTrackingError,
} from "@/components/issue-tracking/issue-tracking-feedback"
import { toast } from "@/components/ui/toast"
import { ApiError, type IssueLink } from "@/lib/api"

vi.mock("@/components/ui/toast", () => ({
  toast: { add: vi.fn() },
}))

const link = (state: IssueLink["state"]): IssueLink => ({
  id: "link-a",
  finding_id: "finding-a",
  provider: "github",
  destination_id: "acme/trace",
  external_identifier: null,
  external_url: null,
  state,
  failure_code: null,
  created_at: "2026-10-27T00:00:00Z",
  updated_at: "2026-10-27T00:00:00Z",
})

describe("issue-tracking feedback", () => {
  it("maps created, pending, and failed links to distinct feedback", () => {
    notifyIssueCreation(link("created"))
    notifyIssueCreation(link("pending"))
    notifyIssueCreation(link("failed"))

    expect(toast.add).toHaveBeenNthCalledWith(
      1,
      expect.objectContaining({ type: "success", title: "Issue created" }),
    )
    expect(toast.add).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({ type: "info", title: "Issue creation is pending" }),
    )
    expect(toast.add).toHaveBeenNthCalledWith(
      3,
      expect.objectContaining({ type: "warning", title: "Issue creation needs attention" }),
    )
  })

  it("maps provider failures without exposing provider responses", () => {
    notifyIssueTrackingError(
      new ApiError(429, { error: { code: "provider_rate_limited" } }, 12),
    )
    notifyIssueTrackingError(
      new ApiError(403, { error: { code: "issue_destination_access_denied" } }),
    )

    expect(toast.add).toHaveBeenNthCalledWith(
      1,
      expect.objectContaining({
        type: "warning",
        description: "Try again in 12 seconds.",
      }),
    )
    expect(toast.add).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({ title: "Destination access denied" }),
    )
  })
})
