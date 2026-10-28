import { toast } from "@/components/ui/toast"
import { ApiError, type IssueLink } from "@/lib/api"

export function notifyIssueCreation(result: IssueLink) {
  if (result.state === "created") {
    toast.add({
      type: "success",
      title: "Issue created",
      description: "Your finding is now tracked externally.",
    })
    return
  }

  if (result.state === "pending") {
    toast.add({
      type: "info",
      title: "Issue creation is pending",
      description: "Trace will not send a duplicate request while this ticket is pending.",
    })
    return
  }

  toast.add({
    type: "warning",
    title: "Issue creation needs attention",
    description: "Try creating the issue again after resolving the provider error.",
  })
}

export function notifyIssueTrackingError(error: unknown) {
  const code = error instanceof ApiError ? error.code : "unknown"
  const copy = {
    issue_destination_not_configured: {
      title: "Issue tracker not configured",
      description: "Add this provider in the project’s Issues tab before creating an issue.",
    },
    issue_provider_authorization_required: {
      title: "Reconnect your provider",
      description: "Reconnect the issue-tracker integration and try again.",
    },
    issue_destination_access_denied: {
      title: "Destination access denied",
      description: "Your connected account cannot create issues in this destination.",
    },
    issue_destination_not_found: {
      title: "Issue destination unavailable",
      description: "Update the project’s issue-tracker configuration and try again.",
    },
    issue_provider_validation_failed: {
      title: "Issue could not be validated",
      description: "Check the saved issue-tracker destination and try again.",
    },
    provider_rate_limited: {
      title: "Rate limit reached",
      description:
        error instanceof ApiError && error.retryAfterSeconds
          ? `Try again in ${error.retryAfterSeconds} seconds.`
          : "Please try again shortly.",
    },
    resource_unavailable: {
      title: "Issue provider is unavailable",
      description: "The request may still be pending. Wait before trying again.",
    },
  }[code]

  toast.add({
    type: code === "provider_rate_limited" ? "warning" : "error",
    ...(copy ?? {
      title: "Issue could not be created",
      description: "Please try again.",
    }),
  })
}
