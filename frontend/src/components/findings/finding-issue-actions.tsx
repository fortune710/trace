import { useLayoutEffect, useRef, useState } from "react"

import { issueProviderLabel } from "@/components/issue-tracking/issue-provider"
import { Github } from "@/components/logos/github"
import { Linear } from "@/components/logos/linear"
import {
  notifyIssueCreation,
  notifyIssueTrackingError,
} from "@/components/issue-tracking/issue-tracking-feedback"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import {
  useCreateRemediationPullRequest,
  useApplyLocalRemediation,
  useFindingRemediations,
} from "@/hooks/use-findings"
import { useRuntimeEnvironment } from "@/hooks/use-runtime-environment"
import { useSession, useUpdateAutomaticPullRequests } from "@/hooks/use-session"
import {
  useCreateRemediationIssue,
  useIssuePreview,
} from "@/hooks/use-issue-tracking"
import type { FindingStatus, IssueProviderName } from "@/lib/api"

const providers: IssueProviderName[] = ["github", "linear"]

function IssueProviderActionLogo({
  provider,
}: {
  provider: IssueProviderName
}) {
  if (provider === "github") {
    return <Github aria-hidden="true" className="size-4 shrink-0" />
  }

  return <Linear aria-hidden="true" className="size-4 shrink-0" />
}

export function FindingIssueActions({
  findingId,
  status,
  isLocalProject = false,
}: {
  findingId: string
  status: FindingStatus
  isLocalProject?: boolean
}) {
  const [provider, setProvider] = useState<IssueProviderName | null>(null)
  const [confirmingPullRequest, setConfirmingPullRequest] = useState(false)
  const [skipConfirmation, setSkipConfirmation] = useState(false)
  const actionGroup = useRef<HTMLDivElement>(null)
  const [actionMenuWidth, setActionMenuWidth] = useState<number>()
  const session = useSession()
  const runtime = useRuntimeEnvironment()
  const updateAutomaticPullRequests = useUpdateAutomaticPullRequests()
  const remediations = useFindingRemediations(findingId)
  const remediation = remediations.data?.[0]
  const remediationId = remediation?.id
  const preview = useIssuePreview(findingId, provider)
  const create = useCreateRemediationIssue(remediationId, findingId)
  const createPullRequest = useCreateRemediationPullRequest(
    remediationId,
    findingId,
  )
  const applyLocalRemediation = useApplyLocalRemediation(findingId)
  const appliesLocally = runtime.isTauri && isLocalProject

  useLayoutEffect(() => {
    const element = actionGroup.current
    if (!element) return

    const updateWidth = () => {
      setActionMenuWidth(element.getBoundingClientRect().width)
    }

    updateWidth()

    if (typeof ResizeObserver === "undefined") return

    const resizeObserver = new ResizeObserver(updateWidth)
    resizeObserver.observe(element)

    return () => resizeObserver.disconnect()
  }, [])

  function requestPullRequest() {
    if (!remediationId || status !== "accepted") return
    if (appliesLocally && remediation) {
      applyLocalRemediation.mutate(remediation)
      return
    }
    if (session.data?.automatic_pull_requests) {
      createPullRequest.mutate()
      return
    }
    setConfirmingPullRequest(true)
  }

  function confirmPullRequest() {
    if (skipConfirmation) {
      updateAutomaticPullRequests.mutate(true)
    }
    createPullRequest.mutate(undefined, {
      onSuccess: () => setConfirmingPullRequest(false),
    })
  }

  function handleProviderChange(value: string | null) {
    if (value === "github" || value === "linear") {
      setProvider(value)
    }
  }

  function handleDialogChange(open: boolean) {
    if (!open && !create.isPending) {
      setProvider(null)
    }
  }

  function handleCreate() {
    if (!provider) return
    if (!remediationId) return
    create.mutate(provider, {
      onSuccess: (link) => {
        notifyIssueCreation(link)
        setProvider(null)
      },
      onError: notifyIssueTrackingError,
    })
  }

  return (
    <>
      <div className="flex flex-col items-end gap-2">
        <div
          ref={actionGroup}
          className="flex items-stretch"
          aria-label="Finding actions"
        >
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger render={<span className="inline-flex" />}>
                <Button
                  type="button"
                  disabled={
                    remediations.isLoading ||
                    !remediationId ||
                    status !== "accepted" ||
                    (!appliesLocally && Boolean(remediation?.pull_request)) ||
                    createPullRequest.isPending ||
                    applyLocalRemediation.isPending
                  }
                  className="rounded-r-none"
                  onClick={requestPullRequest}
                >
                  {appliesLocally ? null : (
                    <IssueProviderActionLogo provider="github" />
                  )}
                  {applyLocalRemediation.isPending
                    ? "Applying change…"
                    : appliesLocally
                      ? "Apply change"
                      : "Create pull request"}
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                {appliesLocally
                  ? "Apply the stored remediation diff to the selected local project."
                  : remediation?.pull_request
                  ? "A pull request already exists for this remediation."
                  : status === "accepted"
                    ? "Create a pull request from the stored remediation diff."
                    : "Accept this finding before creating a pull request."}
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
          <Select
            value={provider}
            onValueChange={handleProviderChange}
            disabled={remediations.isLoading || !remediationId}
          >
            <SelectTrigger
              aria-label="Choose issue tracker"
              className="h-9 rounded-l-none rounded-r-md border-l border-l-primary-foreground/30 bg-primary px-2 text-primary-foreground hover:bg-primary/80 [&_svg]:text-primary-foreground"
            >
              <SelectValue className="sr-only">Create issue</SelectValue>
            </SelectTrigger>
            <SelectContent
              align="end"
              alignItemWithTrigger={false}
              className="min-w-0"
              style={actionMenuWidth ? { width: actionMenuWidth } : undefined}
            >
              <SelectGroup>
                <SelectLabel>Issue trackers</SelectLabel>
                {providers.map((item) => (
                  <SelectItem key={item} value={item}>
                    <IssueProviderActionLogo provider={item} />
                    {issueProviderLabel(item)} issue
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </div>

        {remediation?.pull_request ? (
          <a
            className="text-sm text-link underline"
            href={remediation.pull_request.url}
            target="_blank"
            rel="noreferrer"
          >
            View pull request #{remediation.pull_request.number}
          </a>
        ) : null}
        {applyLocalRemediation.isError ? (
          <p className="max-w-xs text-right text-xs text-destructive" role="alert">
            {applyLocalRemediation.error instanceof Error
              ? applyLocalRemediation.error.message
              : "Trace could not apply the local change."}
          </p>
        ) : null}
      </div>

      <Dialog
        open={confirmingPullRequest}
        onOpenChange={(open) => {
          if (!createPullRequest.isPending) setConfirmingPullRequest(open)
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create pull request?</DialogTitle>
            <DialogDescription>
              Trace will apply the stored remediation diff to a new branch and
              open a pull request in this project’s connected repository.
            </DialogDescription>
          </DialogHeader>
          <label className="flex items-center gap-2 text-sm">
            <Checkbox
              checked={skipConfirmation}
              onCheckedChange={(checked) =>
                setSkipConfirmation(checked === true)
              }
            />
            Automatically create future pull requests for this account
          </label>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={createPullRequest.isPending}
              onClick={() => setConfirmingPullRequest(false)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              disabled={createPullRequest.isPending}
              onClick={confirmPullRequest}
            >
              {createPullRequest.isPending
                ? "Creating pull request…"
                : "Create pull request"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={provider !== null} onOpenChange={handleDialogChange}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>
              Create {provider ? issueProviderLabel(provider) : ""} issue
            </DialogTitle>
            <DialogDescription>
              Trace generates this ticket from the finding and its remediation.
              The content cannot be edited here.
            </DialogDescription>
          </DialogHeader>
          {preview.isLoading ? (
            <p className="text-sm text-muted-foreground">
              Preparing issue preview…
            </p>
          ) : null}
          {preview.isError ? (
            <div className="grid justify-items-start gap-3">
              <p className="text-sm text-destructive">
                We could not prepare this issue preview.
              </p>
              <Button
                type="button"
                variant="outline"
                onClick={() => void preview.refetch()}
              >
                Try again
              </Button>
            </div>
          ) : null}
          {preview.data ? (
            <div className="grid gap-4">
              <div>
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Title
                </p>
                <p className="mt-1 text-sm font-medium">{preview.data.title}</p>
              </div>
              <div>
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Description
                </p>
                <pre className="mt-1 max-h-72 overflow-auto whitespace-pre-wrap rounded-md border border-border bg-muted/20 p-3 font-mono text-xs leading-5">
                  {preview.data.body_markdown}
                </pre>
              </div>
            </div>
          ) : null}
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={create.isPending}
              onClick={() => setProvider(null)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              disabled={!preview.data || create.isPending}
              onClick={handleCreate}
            >
              {create.isPending ? "Creating issue…" : "Create issue"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
