import { useState, type FormEvent } from "react"
import { useQuery } from "@tanstack/react-query"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { toast } from "@/components/ui/toast"
import { useCreateReview } from "@/hooks/use-reviews"
import { agentsApi, type Project } from "@/lib/api"

type ReviewSubmissionDialogProps = {
  open: boolean
  project: Project
  onOpenChange: (open: boolean) => void
  onCreated: (reviewId: string) => void
}

function snapshotDescription(project: Project) {
  if (project.source === "local") {
    return "Trace will capture a local integrity snapshot after you submit. Folder paths and file contents stay on this device."
  }

  return "Trace will resolve the selected GitHub branch to a fresh immutable commit before queueing the review."
}

export function ReviewSubmissionDialog({
  open,
  project,
  onOpenChange,
  onCreated,
}: ReviewSubmissionDialogProps) {
  const [selectedAgentIds, setSelectedAgentIds] = useState<string[]>([])
  const createReview = useCreateReview()
  const agents = useQuery({
    queryKey: ["agents", "review-enabled"],
    queryFn: () =>
      agentsApi.list({
        page: 1,
        pageSize: 100,
        includeDisabled: false,
      }),
    enabled: open,
    retry: false,
  })

  function toggleAgent(agentId: string) {
    setSelectedAgentIds((current) =>
      current.includes(agentId)
        ? current.filter((id) => id !== agentId)
        : [...current, agentId],
    )
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (selectedAgentIds.length === 0) {
      return
    }

    createReview.mutate(
      {
        project,
        agentIds: selectedAgentIds,
      },
      {
        onSuccess: (review) => {
          toast.add({
            type: "success",
            title: "Review queued",
            description: "Your immutable source and reviewer snapshots were saved.",
          })
          setSelectedAgentIds([])
          onOpenChange(false)
          onCreated(review.id)
        },
        onError: () => {
          toast.add({
            type: "error",
            title: "Review could not be started",
            description: "The source could not be captured or the review request was rejected. Try again.",
          })
        },
      },
    )
  }

  const enabledAgents = (agents.data?.items ?? []).filter(
    (agent) => agent.disabled_at === null,
  )

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
    >
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Start review</DialogTitle>
          <DialogDescription>
            {snapshotDescription(project)}
          </DialogDescription>
        </DialogHeader>

        <form
          id="review-submission-form"
          className="grid gap-4"
          onSubmit={handleSubmit}
        >
          <fieldset className="grid gap-2">
            <legend className="text-sm font-medium">Reviewers</legend>
            {agents.isLoading ? (
              <p className="text-sm text-muted-foreground">Loading reviewers…</p>
            ) : null}
            {agents.isError ? (
              <p className="text-sm text-destructive">
                Available reviewers could not be loaded.
              </p>
            ) : null}
            {!agents.isLoading && !agents.isError && enabledAgents.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Create and enable at least one agent before starting a review.
              </p>
            ) : null}
            {enabledAgents.map((agent) => {
              const inputId = `review-agent-${agent.id}`
              const selected = selectedAgentIds.includes(agent.id)

              return (
                <Label
                  key={agent.id}
                  htmlFor={inputId}
                  className="rounded-md border border-border p-3 hover:bg-muted/50"
                >
                  <input
                    id={inputId}
                    type="checkbox"
                    checked={selected}
                    onChange={() => toggleAgent(agent.id)}
                    className="size-4"
                  />
                  <span className="grid gap-0.5">
                    <span>{agent.name}</span>
                    <span className="text-xs font-normal text-muted-foreground">
                      {agent.review_category} · {agent.model_provider}/{agent.model_name}
                    </span>
                  </span>
                </Label>
              )
            })}
          </fieldset>
        </form>

        <DialogFooter>
          <Button
            type="button"
            variant="ghost"
            onClick={() => onOpenChange(false)}
          >
            Cancel
          </Button>
          <Button
            type="submit"
            form="review-submission-form"
            disabled={
              createReview.isPending ||
              selectedAgentIds.length === 0 ||
              agents.isLoading ||
              agents.isError
            }
          >
            {createReview.isPending ? "Capturing source…" : "Start review"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
