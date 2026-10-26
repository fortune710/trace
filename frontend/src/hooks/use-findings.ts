import { keepPreviousData, useQuery } from "@tanstack/react-query"

import {
  findingsApi,
  type FindingSeverity,
  type FindingStatus,
  type ReviewCategory,
} from "@/lib/api"

export type FindingFilters = {
  category?: ReviewCategory
  severity?: FindingSeverity
  status?: FindingStatus
  agentId?: string
}

export const findingsQueryKey = ["findings"] as const
const FINDINGS_PAGE_SIZE = 25

export function useReviewFindings(
  reviewId: string | undefined,
  page: number,
  filters: FindingFilters,
) {
  return useQuery({
    queryKey: [...findingsQueryKey, "review", reviewId, page, filters],
    queryFn: () =>
      findingsApi.list({
        reviewId: reviewId!,
        page,
        pageSize: FINDINGS_PAGE_SIZE,
        ...filters,
      }),
    enabled: Boolean(reviewId),
    placeholderData: keepPreviousData,
    retry: false,
  })
}

export function useFinding(findingId: string | undefined) {
  return useQuery({
    queryKey: [...findingsQueryKey, "detail", findingId],
    queryFn: () => findingsApi.get(findingId!),
    enabled: Boolean(findingId),
    retry: false,
  })
}
