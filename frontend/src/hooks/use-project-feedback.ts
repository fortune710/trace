import { useEffect, useRef } from "react"

import { toast } from "@/components/ui/toast"
import { ApiError } from "@/lib/api"
import { LocalProjectCreationError } from "@/lib/desktop-projects"

type Operation = "projects" | "repositories" | "branches" | "create"

export const projectCreatedToast = {
  type: "success" as const,
  title: "Project created",
  description: "Your repository is ready to review.",
}

const operationLabel: Record<Exclude<Operation, "create">, string> = {
  projects: "projects",
  repositories: "repositories",
  branches: "branches",
}

export function projectErrorCopy(error: unknown, operation: Operation) {
  if (error instanceof LocalProjectCreationError && error.code === "already_exists") {
    return {
      title: "Project already connected",
      description: "Choose a different folder or open the existing local project.",
      type: "error" as const,
    }
  }

  if (error instanceof ApiError) {
    if (error.code === "provider_rate_limited" || error.code === "rate_limited") {
      return {
        title: "Rate limit reached",
        description: error.retryAfterSeconds
          ? `Try again in ${error.retryAfterSeconds} seconds.`
          : "Please try again shortly.",
        type: "warning" as const,
      }
    }
    if (error.code === "github_authorization_required") {
      return {
        title: "Reconnect GitHub",
        description: "Connect GitHub again in Integrations before importing a project.",
        type: "error" as const,
      }
    }
    if (error.code === "repository_not_found" || error.code === "branch_not_found") {
      return {
        title: error.code === "branch_not_found" ? "Branch unavailable" : "Repository unavailable",
        description: "Refresh your selection and try again.",
        type: "error" as const,
      }
    }
    if (error.code === "resource_conflict") {
      return {
        title: "Project already imported",
        description: "Choose a different repository or branch.",
        type: "error" as const,
      }
    }
  }

  return {
    title: operation === "create" ? "Project could not be created" : `Could not load ${operationLabel[operation]}`,
    description: "Please try again.",
    type: "error" as const,
  }
}

export function useProjectErrorToast(error: unknown, operation: Operation) {
  const lastError = useRef<unknown>(null)

  useEffect(() => {
    if (!error || error === lastError.current) return
    lastError.current = error
    toast.add(projectErrorCopy(error, operation))
  }, [error, operation])
}
