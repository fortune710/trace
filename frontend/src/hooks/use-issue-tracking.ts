import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import {
  ApiError,
  findingsApi,
  issueTrackingApi,
  projectsApi,
  remediationsApi,
  type IssueProviderName,
  type IssueTrackingDetails,
} from "@/lib/api"
import { trackEvent } from "@/lib/analytics"

export const issueTrackingQueryKey = ["issue-tracking"] as const

export function useFindingIssueLinks(findingId: string | undefined) {
  return useQuery({
    queryKey: [...issueTrackingQueryKey, "finding", findingId],
    queryFn: () => findingsApi.listIssueLinks(findingId!),
    enabled: Boolean(findingId),
    retry: false,
  })
}

export function useIssuePreview(
  findingId: string | undefined,
  provider: IssueProviderName | null,
) {
  return useQuery({
    queryKey: [...issueTrackingQueryKey, "preview", findingId, provider],
    queryFn: () => findingsApi.previewIssue(findingId!, provider!),
    enabled: Boolean(findingId && provider),
    retry: false,
  })
}

export function useCreateRemediationIssue(
  remediationId: string | undefined,
  findingId: string,
) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (provider: IssueProviderName) => {
      trackEvent("finding_issue_create_submitted", {
        finding_id: findingId,
        provider,
      })
      return remediationsApi.createIssue(remediationId!, provider)
    },
    onSuccess: (_result, provider) => {
      trackEvent("finding_issue_create_succeeded", {
        finding_id: findingId,
        provider,
      })
      queryClient.invalidateQueries({
        queryKey: [...issueTrackingQueryKey, "finding", findingId],
      })
    },
    onError: (error, provider) => {
      trackEvent("finding_issue_create_failed", {
        finding_id: findingId,
        provider,
        error_code: error instanceof ApiError ? error.code : undefined,
      })
    },
  })
}

export function useProjectIssueTracking(projectId: string | undefined) {
  return useQuery({
    queryKey: [...issueTrackingQueryKey, "project", projectId],
    queryFn: () => projectsApi.issueTracking(projectId!),
    enabled: Boolean(projectId),
    retry: false,
  })
}

export function useUpdateProjectIssueTracking(projectId: string) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (details: IssueTrackingDetails) =>
      projectsApi.updateIssueTracking(projectId, details),
    onSuccess: (_result, details) => {
      trackEvent("project_issue_tracking_updated", {
        project_id: projectId,
        provider_count: details.connected_projects.length,
      })
      queryClient.invalidateQueries({
        queryKey: [...issueTrackingQueryKey, "project", projectId],
      })
    },
  })
}

export function useLinearTeams(enabled: boolean) {
  return useQuery({
    queryKey: [...issueTrackingQueryKey, "linear", "teams"],
    queryFn: issueTrackingApi.listLinearTeams,
    enabled,
    retry: false,
  })
}

export function useLinearProjects(teamId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: [...issueTrackingQueryKey, "linear", "teams", teamId, "projects"],
    queryFn: () => issueTrackingApi.listLinearProjects(teamId!),
    enabled: enabled && Boolean(teamId),
    retry: false,
  })
}
