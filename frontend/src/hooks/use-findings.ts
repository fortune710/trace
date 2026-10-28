import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"

import {
  findingsApi,
  ApiError,
  remediationsApi,
  type Finding,
  type FindingPage,
  type FindingSeverity,
  type FindingStatus,
  type ReviewCategory,
} from "@/lib/api"

export type FindingFilters = {
  category?: ReviewCategory
  severity?: FindingSeverity
  status?: FindingStatus
  excludeStatus?: FindingStatus
  agentId?: string
}

export const findingsQueryKey = ["findings"] as const
const FINDINGS_PAGE_SIZE = 25

export function useReviewFindings(
  reviewId: string | undefined,
  page: number,
  filters: FindingFilters,
  enabled = true,
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
    enabled: Boolean(reviewId) && enabled,
    placeholderData: keepPreviousData,
    retry: false,
  })
}

type FindingCacheSnapshot = Array<[readonly unknown[], unknown]>

function isDismissedFindingPage(queryKey: readonly unknown[]) {
  const filters = queryKey[4]
  return (
    typeof filters === "object" &&
    filters !== null &&
    "status" in filters &&
    filters.status === "dismissed"
  )
}

function isPrimaryFindingPage(queryKey: readonly unknown[]) {
  const filters = queryKey[4]
  return (
    typeof filters === "object" &&
    filters !== null &&
    "excludeStatus" in filters &&
    filters.excludeStatus === "dismissed"
  )
}

function statusMatchesFindingPage(
  queryKey: readonly unknown[],
  status: FindingStatus,
) {
  const filters = queryKey[4]
  return (
    typeof filters === "object" &&
    filters !== null &&
    "status" in filters &&
    filters.status === status
  )
}

function insertByCreatedAt(items: Finding[], finding: Finding) {
  return [...items.filter((item) => item.id !== finding.id), finding].toSorted(
    (left, right) =>
      new Date(right.created_at).getTime() -
      new Date(left.created_at).getTime(),
  )
}

export function useUpdateFindingStatus() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({
      findingId,
      status,
    }: {
      findingId: string
      status: FindingStatus
    }) => findingsApi.updateStatus(findingId, status),
    onMutate: async ({ findingId, status }) => {
      await queryClient.cancelQueries({ queryKey: findingsQueryKey })
      const previous = queryClient.getQueriesData({
        queryKey: findingsQueryKey,
      }) as FindingCacheSnapshot
      const cachedFinding = previous
        .map(([, value]) => value)
        .find(
          (value): value is Finding =>
            value != null &&
            typeof value === "object" &&
            "id" in value &&
            value.id === findingId &&
            "review_id" in value,
        )
      const cachedPageFinding = previous
        .flatMap(([, value]) =>
          value && typeof value === "object" && "items" in value
            ? (value as FindingPage).items
            : [],
        )
        .find((finding) => finding.id === findingId)
      const currentFinding = cachedFinding ?? cachedPageFinding
      if (!currentFinding) return { previous }
      const optimisticFinding: Finding = {
        ...currentFinding,
        status,
      }

      previous.forEach(([queryKey, value]) => {
        if (!value || typeof value !== "object") return
        if ("id" in value && value.id === findingId && "review_id" in value) {
          queryClient.setQueryData(queryKey, optimisticFinding)
          return
        }
        if (!("items" in value)) return
        const page = value as FindingPage
        const containsFinding = page.items.some((item) => item.id === findingId)
        const dismissedPage = isDismissedFindingPage(queryKey)
        const primaryPage = isPrimaryFindingPage(queryKey)
        const targetStatusPage = statusMatchesFindingPage(queryKey, status)

        if (status === "dismissed") {
          queryClient.setQueryData(
            queryKey,
            dismissedPage
              ? {
                  ...page,
                  items: insertByCreatedAt(page.items, optimisticFinding),
                }
              : {
                  ...page,
                  items: page.items.filter((item) => item.id !== findingId),
                },
          )
          return
        }
        if (dismissedPage) {
          queryClient.setQueryData(queryKey, {
            ...page,
            items: page.items.filter((item) => item.id !== findingId),
          })
          return
        }
        if (containsFinding) {
          queryClient.setQueryData(queryKey, {
            ...page,
            items: page.items.map((item) =>
              item.id === findingId ? optimisticFinding : item,
            ),
          })
        } else if (primaryPage || targetStatusPage) {
          queryClient.setQueryData(queryKey, {
            ...page,
            items: insertByCreatedAt(page.items, optimisticFinding),
          })
        }
      })

      return { previous }
    },
    onSuccess: (finding) => {
      queryClient
        .getQueriesData({ queryKey: findingsQueryKey })
        .forEach(([queryKey, value]) => {
          if (!value || typeof value !== "object") return
          if (
            "id" in value &&
            value.id === finding.id &&
            "review_id" in value
          ) {
            queryClient.setQueryData(queryKey, finding)
            return
          }
          if ("items" in value) {
            const page = value as FindingPage
            queryClient.setQueryData(queryKey, {
              ...page,
              items: page.items.map((item) =>
                item.id === finding.id ? finding : item,
              ),
            })
          }
        })
    },
    onError: (_error, _variables, context) => {
      context?.previous.forEach(([queryKey, value]) => {
        queryClient.setQueryData(queryKey, value)
      })
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: findingsQueryKey })
    },
  })
}

export function useCreateRemediationPullRequest(
  remediationId: string | undefined,
  findingId: string,
) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: () => remediationsApi.createPullRequest(remediationId!),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: findingsQueryKey })
      void queryClient.invalidateQueries({
        queryKey: [...findingsQueryKey, "remediations", findingId],
      })
    },
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

export function useFindingRemediations(findingId: string | undefined) {
  return useQuery({
    queryKey: [...findingsQueryKey, "remediation", findingId],
    queryFn: () => remediationsApi.listForFinding(findingId!),
    enabled: Boolean(findingId),
    retry: false,
  })
}

export function useFindingRemediationPrompt(findingId: string | undefined) {
  const remediations = useFindingRemediations(findingId)
  const remediationId = remediations.data?.[0]?.id
  const prompt = useQuery({
    queryKey: [...findingsQueryKey, "remediation", remediationId, "prompt"],
    queryFn: () => remediationsApi.getPrompt(remediationId!),
    enabled: Boolean(remediationId),
    retry: false,
  })
  const promptMissing =
    prompt.isError &&
    prompt.error instanceof ApiError &&
    prompt.error.code === "resource_not_found"
  const noPrompt =
    remediations.isSuccess && (!remediationId || promptMissing)
  const isError = remediations.isError || (prompt.isError && !promptMissing)

  return {
    prompt: prompt.data?.prompt_text ?? null,
    isLoading:
      remediations.isLoading || (Boolean(remediationId) && prompt.isLoading),
    isError,
    isNoPrompt: noPrompt,
    refetch: async () => {
      await remediations.refetch()
      if (remediationId) {
        await prompt.refetch()
      }
    },
  }
}
