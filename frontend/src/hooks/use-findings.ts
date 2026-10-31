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
  type Remediation,
  type ReviewCategory,
} from "@/lib/api"
import {
  applyLocalRemediation,
  restoreLocalRemediation,
} from "@/lib/local-source-snapshot"
import { getLocalProjectsDatabase } from "@/lib/local-projects-database"
import { desktopTelemetry } from "@/lib/desktop-telemetry"
import { useRuntimeEnvironment } from "@/hooks/use-runtime-environment"
import { useSession } from "@/hooks/use-session"

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
  polling = false,
) {
  return useQuery({
    queryKey: [...findingsQueryKey, "review", reviewId, page, filters, polling],
    queryFn: () =>
      findingsApi.list({
        reviewId: reviewId!,
        page,
        pageSize: FINDINGS_PAGE_SIZE,
        ...filters,
      }),
    enabled: Boolean(reviewId) && enabled,
    refetchInterval: polling ? 2000 : false,
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

function getPageStatusFilter(queryKey: readonly unknown[]) {
  const filters = queryKey[4]
  if (
    typeof filters !== "object" ||
    filters === null ||
    !("status" in filters)
  ) {
    return undefined
  }
  return filters.status
}

function isFindingPageForReview(
  queryKey: readonly unknown[],
  reviewId: string,
) {
  return queryKey[1] === "review" && queryKey[2] === reviewId
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
        if (!isFindingPageForReview(queryKey, currentFinding.review_id)) return
        const page = value as FindingPage
        const containsFinding = page.items.some((item) => item.id === findingId)
        const dismissedPage = isDismissedFindingPage(queryKey)
        const pageStatus = getPageStatusFilter(queryKey)

        if (status === "dismissed") {
          if (!containsFinding) return
          queryClient.setQueryData(
            queryKey,
            dismissedPage
              ? {
                  ...page,
                  items: page.items.map((item) =>
                    item.id === findingId ? optimisticFinding : item,
                  ),
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
        if (containsFinding && pageStatus && pageStatus !== status) {
          queryClient.setQueryData(queryKey, {
            ...page,
            items: page.items.filter((item) => item.id !== findingId),
          })
        } else if (containsFinding) {
          queryClient.setQueryData(queryKey, {
            ...page,
            items: page.items.map((item) =>
              item.id === findingId ? optimisticFinding : item,
            ),
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
            if (!isFindingPageForReview(queryKey, finding.review_id)) return
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

export function useApplyLocalRemediation(findingId: string) {
  const queryClient = useQueryClient()
  const runtime = useRuntimeEnvironment()
  const session = useSession()

  return useMutation({
    mutationFn: async (remediation: Remediation) => {
      if (!remediation.patch_available) {
        throw new Error("A validated remediation patch is not available.")
      }
      if (!runtime.isTauri) {
        throw new Error("Local remediation is available in the desktop app only.")
      }
      const accountId = session.data?.user_id
      if (!accountId) {
        throw new Error("Sign in before applying a local remediation.")
      }
      const database = await getLocalProjectsDatabase()
      const project = await database.getByApiProjectId(
        accountId,
        remediation.project_id,
      )
      if (
        !project ||
        project.source.kind !== "local" ||
        project.source.availability !== "available"
      ) {
        throw new Error("Reconnect the reviewed local folder before applying this change.")
      }

      await desktopTelemetry.record({
        event: "local_remediation.apply.started",
        userId: accountId,
      })
      let operation
      try {
        const patch = await remediationsApi.getPatch(remediation.id)
        operation = await applyLocalRemediation(
          project.source.canonicalPath,
          remediation.id,
          patch,
        )
        await desktopTelemetry.record({
          event: "local_remediation.apply.succeeded",
          userId: accountId,
        })
      } catch (error) {
        await desktopTelemetry.record({
          event: "local_remediation.apply.failed",
          userId: accountId,
          errorCode: "local_apply_failed",
        })
        throw error
      }
      try {
        const recorded = await remediationsApi.completeLocalApply(remediation.id, {
          files: operation.files.map((file) => ({
            file_path: file.filePath,
            backup_reference: file.backupReference,
            source_hash: file.sourceHash,
            applied_hash: file.appliedHash,
          })),
        })
        await desktopTelemetry.record({
          event: "local_remediation.record.succeeded",
          userId: accountId,
        })
        return recorded
      } catch (error) {
        await desktopTelemetry.record({
          event: "local_remediation.record.failed",
          userId: accountId,
          errorCode: error instanceof ApiError ? error.code : "local_record_failed",
          httpStatus: error instanceof ApiError ? error.status : undefined,
          serverRequestId: error instanceof ApiError ? error.requestId : undefined,
        })
        try {
          await restoreLocalRemediation(
            project.source.canonicalPath,
            remediation.id,
            operation.files,
          )
          await desktopTelemetry.record({
            event: "local_remediation.restore.succeeded",
            userId: accountId,
          })
        } catch {
          await desktopTelemetry.record({
            event: "local_remediation.restore.failed",
            userId: accountId,
            errorCode: "local_restore_failed",
          })
          throw new Error(
            "Trace could not record or restore the local change. Check the affected files before continuing.",
          )
        }
        throw error
      }
    },
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
    refetchInterval: (query) =>
      query.state.data?.some((item) => item.generation_status === "pending" || item.generation_status === "running")
        ? 2000
        : false,
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
