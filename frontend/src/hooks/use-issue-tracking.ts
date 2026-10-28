import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import {
  findingsApi,
  issueTrackingApi,
  projectsApi,
  remediationsApi,
  type IssueProviderName,
  type IssueTrackingDetails,
} from "@/lib/api"

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
    mutationFn: (provider: IssueProviderName) =>
      remediationsApi.createIssue(remediationId!, provider),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: [...issueTrackingQueryKey, "finding", findingId],
      }),
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
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: [...issueTrackingQueryKey, "project", projectId],
      }),
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
