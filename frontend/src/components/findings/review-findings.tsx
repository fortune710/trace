import { useState } from "react"
import { Link, useSearchParams } from "react-router-dom"

import {
  findingFilterParameterNames,
  findingPageParameterName,
} from "@/components/findings/finding-search-params"
import { ReviewFindingsSkeleton } from "@/components/findings/review-findings-skeleton"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
} from "@/components/ui/empty"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  useReviewFindings,
  useUpdateFindingStatus,
  type FindingFilters,
} from "@/hooks/use-findings"
import { ApiError } from "@/lib/api"
import type {
  Finding,
  FindingSeverity,
  FindingStatus,
  Review,
  ReviewCategory,
} from "@/lib/api"

const categories: ReviewCategory[] = [
  "security",
  "engineering",
  "product",
  "legal",
  "accessibility",
  "marketing",
]

const severities: FindingSeverity[] = [
  "info",
  "low",
  "medium",
  "high",
  "critical",
]

const filterableStatuses: FindingStatus[] = ["open", "accepted", "resolved"]

const allFilterValue = "all"
const visibleSourceLocationLimit = 3

function label(value: string) {
  return value.replaceAll("_", " ")
}

function validFilterValue<T extends string>(
  value: string | null,
  allowedValues: readonly T[],
): T | undefined {
  return allowedValues.find((allowedValue) => allowedValue === value)
}

function findingFiltersFromSearchParams(
  searchParams: URLSearchParams,
  review: Review,
): FindingFilters {
  const agentId = searchParams.get(findingFilterParameterNames.agentId)

  return {
    category: validFilterValue(
      searchParams.get(findingFilterParameterNames.category),
      categories,
    ),
    severity: validFilterValue(
      searchParams.get(findingFilterParameterNames.severity),
      severities,
    ),
    status: validFilterValue(
      searchParams.get(findingFilterParameterNames.status),
      filterableStatuses,
    ),
    agentId: review.agents.some((agent) => agent.agent_id === agentId)
      ? (agentId ?? undefined)
      : undefined,
  }
}

function pageFromSearchParams(searchParams: URLSearchParams) {
  const requestedPage = Number(
    searchParams.get(findingPageParameterName) ?? "1",
  )
  return Number.isInteger(requestedPage) && requestedPage > 0
    ? requestedPage
    : 1
}

function sourceFiles(value: string) {
  const normalized = value.trim().replace(/^\[|\]$/g, "")

  return [
    ...new Set(
      normalized
        .split(/[\n,;|]+/)
        .map((file) =>
          file
            .trim()
            .replace(/^[-*•]\s+/, "")
            .replace(/^["']|["']$/g, ""),
        )
        .filter(Boolean),
    ),
  ]
}

function findingActions(status: FindingStatus) {
  switch (status) {
    case "open":
      return [
        { label: "Accept", status: "accepted" as const },
        { label: "Dismiss", status: "dismissed" as const },
      ]
    case "accepted":
      return [{ label: "Resolve", status: "resolved" as const }]
    case "dismissed":
      return [{ label: "Reopen", status: "open" as const }]
    case "resolved":
      return [{ label: "Unresolve", status: "accepted" as const }]
  }
}

function FindingCard({
  finding,
  onStatusChange,
  pending,
  error,
}: {
  finding: Finding
  onStatusChange: (status: FindingStatus) => void
  pending: boolean
  error: string | null
}) {
  const sourceFilesForFinding = finding.source_location
    ? sourceFiles(finding.source_location)
    : []
  const visibleSourceFiles = sourceFilesForFinding.slice(
    0,
    visibleSourceLocationLimit,
  )
  const hiddenSourceFileCount =
    sourceFilesForFinding.length - visibleSourceFiles.length

  return (
    <article className="rounded-lg border border-border bg-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            {finding.severity} · {label(finding.category)}
          </p>
          <h3 className="mt-1 text-base font-medium">{finding.title}</h3>
        </div>
        <Badge variant="outline" className="capitalize text-muted-foreground">
          {finding.status}
        </Badge>
      </div>
      <p className="mt-3 text-sm text-muted-foreground">
        {finding.explanation}
      </p>
      <dl className="mt-4 grid gap-2 text-sm">
        <div>
          <dt className="text-xs text-muted-foreground">Reviewer</dt>
          <dd>{finding.reviewing_agent.display_name}</dd>
        </div>
        {sourceFilesForFinding.length > 0 ? (
          <div className="min-w-0">
            <dt className="text-xs text-muted-foreground">Location</dt>
            <dd className="mt-1 flex min-w-0 flex-wrap gap-1">
              {visibleSourceFiles.map((file) => (
                <Badge
                  key={file}
                  variant="outline"
                  className="max-w-full shrink-0 truncate font-mono text-xs"
                  title={file}
                >
                  {file}
                </Badge>
              ))}
              {hiddenSourceFileCount > 0 ? (
                <Badge
                  variant="outline"
                  title={`${hiddenSourceFileCount} additional source ${hiddenSourceFileCount === 1 ? "file" : "files"}`}
                >
                  +{hiddenSourceFileCount}
                </Badge>
              ) : null}
            </dd>
          </div>
        ) : null}
      </dl>
      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <Link
          to={`/reviews/${encodeURIComponent(finding.review_id)}/findings/${encodeURIComponent(finding.id)}`}
          className="text-sm text-primary hover:underline"
        >
          View finding
        </Link>
        <div className="flex flex-wrap justify-end gap-2">
          {findingActions(finding.status).map((action) => (
            <Button
              key={action.status}
              type="button"
              size="sm"
              variant={action.status === "dismissed" ? "outline" : "default"}
              disabled={pending}
              onClick={() => onStatusChange(action.status)}
            >
              {action.label}
            </Button>
          ))}
        </div>
      </div>
      {error ? (
        <p className="mt-3 text-sm text-destructive" role="alert">
          {error}
        </p>
      ) : null}
    </article>
  )
}

export function ReviewFindings({ review }: { review: Review }) {
  const [searchParams, setSearchParams] = useSearchParams()
  const [dismissedOpen, setDismissedOpen] = useState(false)
  const [dismissedPage, setDismissedPage] = useState(1)
  const filters = findingFiltersFromSearchParams(searchParams, review)
  const page = pageFromSearchParams(searchParams)
  const primaryFilters = filters.status
    ? filters
    : { ...filters, excludeStatus: "dismissed" as const }
  const findings = useReviewFindings(review.id, page, primaryFilters)
  const dismissedFindings = useReviewFindings(
    review.id,
    dismissedPage,
    { status: "dismissed" },
    dismissedOpen,
  )
  const updateStatus = useUpdateFindingStatus()
  const hasFilters = Object.values(filters).some(Boolean)
  const hasNextPage = findings.data?.next_offset != null
  const isEmpty =
    !findings.isLoading &&
    !findings.isError &&
    findings.data?.items.length === 0

  function updateFilters(nextFilters: FindingFilters) {
    setSearchParams((currentSearchParams) => {
      const nextSearchParams = new URLSearchParams(currentSearchParams)
      nextSearchParams.delete(findingPageParameterName)

      for (const [filterName, parameterName] of Object.entries(
        findingFilterParameterNames,
      ) as Array<[keyof FindingFilters, string]>) {
        const value = nextFilters[filterName]
        if (value) {
          nextSearchParams.set(parameterName, value)
        } else {
          nextSearchParams.delete(parameterName)
        }
      }

      return nextSearchParams
    })
  }

  function updatePage(nextPage: number) {
    setSearchParams((currentSearchParams) => {
      const nextSearchParams = new URLSearchParams(currentSearchParams)
      if (nextPage === 1) {
        nextSearchParams.delete(findingPageParameterName)
      } else {
        nextSearchParams.set(findingPageParameterName, String(nextPage))
      }
      return nextSearchParams
    })
  }

  function changeStatus(findingId: string, status: FindingStatus) {
    updateStatus.mutate({ findingId, status })
  }

  function findingError(findingId: string) {
    if (
      updateStatus.variables?.findingId !== findingId ||
      !updateStatus.isError
    ) {
      return null
    }
    if (
      updateStatus.error instanceof ApiError &&
      updateStatus.error.status === 409
    ) {
      return "This finding changed elsewhere. The latest status has been reloaded."
    }
    return "We could not save this change. Try again."
  }

  function isFindingPending(findingId: string) {
    return (
      updateStatus.isPending && updateStatus.variables?.findingId === findingId
    )
  }

  return (
    <section aria-label="Findings">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-base font-medium">Findings</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Risks reported by the reviewers selected for this snapshot.
          </p>
        </div>
        {hasFilters ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => updateFilters({})}
          >
            Clear filters
          </Button>
        ) : null}
      </div>

      <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div className="grid gap-1">
          <Label htmlFor="finding-category">Category</Label>
          <Select
            value={filters.category ?? allFilterValue}
            onValueChange={(value) =>
              updateFilters({
                ...filters,
                category: (value && value !== allFilterValue
                  ? value
                  : undefined) as ReviewCategory | undefined,
              })
            }
          >
            <SelectTrigger id="finding-category" className="w-full">
              <SelectValue>
                {filters.category ? label(filters.category) : "All categories"}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={allFilterValue}>All categories</SelectItem>
              {categories.map((category) => (
                <SelectItem key={category} value={category}>
                  {label(category)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="grid gap-1">
          <Label htmlFor="finding-severity">Severity</Label>
          <Select
            value={filters.severity ?? allFilterValue}
            onValueChange={(value) =>
              updateFilters({
                ...filters,
                severity: (value && value !== allFilterValue
                  ? value
                  : undefined) as FindingSeverity | undefined,
              })
            }
          >
            <SelectTrigger id="finding-severity" className="w-full">
              <SelectValue>{filters.severity ?? "All severities"}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={allFilterValue}>All severities</SelectItem>
              {severities.map((severity) => (
                <SelectItem key={severity} value={severity}>
                  {severity}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="grid gap-1">
          <Label htmlFor="finding-status">Status</Label>
          <Select
            value={filters.status ?? allFilterValue}
            onValueChange={(value) =>
              updateFilters({
                ...filters,
                status: (value && value !== allFilterValue
                  ? value
                  : undefined) as FindingStatus | undefined,
              })
            }
          >
            <SelectTrigger id="finding-status" className="w-full">
              <SelectValue>{filters.status ?? "All statuses"}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={allFilterValue}>All statuses</SelectItem>
              {filterableStatuses.map((status) => (
                <SelectItem key={status} value={status}>
                  {status}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="grid gap-1">
          <Label htmlFor="finding-reviewer">Reviewer</Label>
          <Select
            value={filters.agentId ?? allFilterValue}
            onValueChange={(value) =>
              updateFilters({
                ...filters,
                agentId: value && value !== allFilterValue ? value : undefined,
              })
            }
          >
            <SelectTrigger id="finding-reviewer" className="w-full">
              <SelectValue>
                {review.agents.find(
                  (agent) => agent.agent_id === filters.agentId,
                )?.name ?? "All reviewers"}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={allFilterValue}>All reviewers</SelectItem>
              {review.agents.map((agent) => (
                <SelectItem key={agent.agent_id} value={agent.agent_id}>
                  {agent.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {findings.isLoading ? <ReviewFindingsSkeleton /> : null}
      {findings.isError ? (
        <div className="mt-6 grid justify-items-start gap-3">
          <p className="text-sm text-muted-foreground">
            We could not load these findings.
          </p>
          <Button
            type="button"
            variant="outline"
            onClick={() => void findings.refetch()}
          >
            Try again
          </Button>
        </div>
      ) : null}
      {isEmpty ? (
        <Empty className="mt-6 min-h-56 border-white/14 bg-[#0a0a0c]">
          <EmptyHeader>
            <EmptyTitle className="text-base">
              {hasFilters
                ? "No findings match these filters"
                : "No findings for this review"}
            </EmptyTitle>
            <EmptyDescription>
              {hasFilters
                ? "Adjust or clear the filters to see other reported findings."
                : "The reviewers did not report any findings for this review."}
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : null}
      {findings.data?.items.length ? (
        <div className="mt-6 grid gap-3">
          {findings.data.items.map((finding) => (
            <FindingCard
              key={finding.id}
              finding={finding}
              onStatusChange={(status) => changeStatus(finding.id, status)}
              pending={isFindingPending(finding.id)}
              error={findingError(finding.id)}
            />
          ))}
        </div>
      ) : null}
      {page > 1 || hasNextPage ? (
        <nav
          className="mt-5 flex justify-end gap-3"
          aria-label="Findings pagination"
        >
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={page === 1 || findings.isFetching}
            onClick={() => updatePage(page - 1)}
          >
            Previous
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={!hasNextPage || findings.isFetching}
            onClick={() => updatePage(page + 1)}
          >
            Next
          </Button>
        </nav>
      ) : null}
      <section
        className="mt-8 border-t border-border pt-6"
        aria-label="Dismissed findings"
      >
        <Button
          type="button"
          variant="ghost"
          size="sm"
          aria-expanded={dismissedOpen}
          onClick={() => {
            setDismissedOpen((open) => !open)
            setDismissedPage(1)
          }}
        >
          {dismissedOpen
            ? "Hide dismissed findings"
            : "Show dismissed findings"}
        </Button>
        {dismissedOpen && dismissedFindings.isLoading ? (
          <div
            className="mt-4 grid gap-3"
            aria-label="Loading dismissed findings"
          >
            <Skeleton className="h-36 w-full" />
            <Skeleton className="h-36 w-full" />
          </div>
        ) : null}
        {dismissedOpen && dismissedFindings.isError ? (
          <div className="mt-4 grid justify-items-start gap-3">
            <p className="text-sm text-muted-foreground">
              We could not load dismissed findings.
            </p>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => void dismissedFindings.refetch()}
            >
              Try again
            </Button>
          </div>
        ) : null}
        {dismissedOpen &&
        !dismissedFindings.isLoading &&
        !dismissedFindings.isError &&
        dismissedFindings.data?.items.length === 0 ? (
          <p className="mt-4 text-sm text-muted-foreground">
            No dismissed findings.
          </p>
        ) : null}
        {dismissedOpen && dismissedFindings.data?.items.length ? (
          <div className="mt-4 grid gap-3">
            {dismissedFindings.data.items.map((finding) => (
              <FindingCard
                key={finding.id}
                finding={finding}
                onStatusChange={(status) => changeStatus(finding.id, status)}
                pending={isFindingPending(finding.id)}
                error={findingError(finding.id)}
              />
            ))}
          </div>
        ) : null}
        {dismissedOpen &&
        (dismissedPage > 1 || dismissedFindings.data?.next_offset != null) ? (
          <nav
            className="mt-5 flex justify-end gap-3"
            aria-label="Dismissed findings pagination"
          >
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={dismissedPage === 1 || dismissedFindings.isFetching}
              onClick={() => setDismissedPage((current) => current - 1)}
            >
              Previous
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={
                dismissedFindings.data?.next_offset == null ||
                dismissedFindings.isFetching
              }
              onClick={() => setDismissedPage((current) => current + 1)}
            >
              Next
            </Button>
          </nav>
        ) : null}
      </section>
    </section>
  )
}
