import { useRef, useState } from "react"
import { Copy01Icon } from "@hugeicons/core-free-icons"
import { HugeiconsIcon } from "@hugeicons/react"

import { Button } from "@/components/ui/button"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
} from "@/components/ui/empty"
import { Skeleton } from "@/components/ui/skeleton"
import { ScrollArea } from "@/components/ui/scroll-area"
import { toast } from "@/components/ui/toast"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { useFindingRemediationPrompt } from "@/hooks/use-findings"

function PromptSkeleton() {
  return (
    <section className="mt-6" aria-label="Loading coding-agent prompt">
      <Skeleton className="h-5 w-40" />
      <div className="mt-3 rounded-lg border border-border bg-muted/20 p-4">
        <Skeleton className="h-4 w-full" />
        <Skeleton className="mt-2 h-4 w-11/12" />
        <Skeleton className="mt-2 h-4 w-4/5" />
      </div>
    </section>
  )
}

export function CodingAgentPrompt({ findingId }: { findingId: string }) {
  const prompt = useFindingRemediationPrompt(findingId)
  const promptPanel = useRef<HTMLPreElement>(null)
  const [manualCopyRequired, setManualCopyRequired] = useState(false)

  function selectPrompt() {
    const panel = promptPanel.current
    const selection = window.getSelection()
    if (!panel || !selection) return

    panel.focus()
    const range = document.createRange()
    range.selectNodeContents(panel)
    selection.removeAllRanges()
    selection.addRange(range)
  }

  async function copyPrompt() {
    if (!prompt.prompt) return

    try {
      if (!window.navigator.clipboard?.writeText) {
        throw new Error("clipboard_unavailable")
      }
      await window.navigator.clipboard.writeText(prompt.prompt)
      setManualCopyRequired(false)
      toast.add({
        type: "success",
        title: "Prompt copied",
        description: "Paste it into your coding agent.",
      })
    } catch {
      selectPrompt()
      setManualCopyRequired(true)
    }
  }

  if (prompt.isLoading) {
    return <PromptSkeleton />
  }

  if (prompt.isNoPrompt) {
    return (
      <Empty className="mt-6 min-h-56 bg-muted/20">
        <EmptyHeader>
          <EmptyTitle className="text-base">
            No coding-agent prompt available
          </EmptyTitle>
          <EmptyDescription>
            This finding does not have a remediation prompt yet.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  }

  if (prompt.isError) {
    return (
      <section className="mt-6 grid justify-items-start gap-3">
        <p className="text-sm text-muted-foreground">
          We could not load the coding-agent prompt.
        </p>
        <Button
          type="button"
          variant="outline"
          onClick={() => void prompt.refetch()}
        >
          Try again
        </Button>
      </section>
    )
  }

  if (!prompt.prompt) {
    return null
  }

  return (
    <section className="mt-6" aria-labelledby="coding-agent-prompt-heading">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2
          id="coding-agent-prompt-heading"
          className="text-base font-medium tracking-tight"
        >
          Coding-agent prompt
        </h2>
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger render={<span className="inline-flex" />}>
              <Button
                type="button"
                variant="outline"
                size="icon"
                aria-label="Copy prompt"
                onClick={() => void copyPrompt()}
              >
                <HugeiconsIcon icon={Copy01Icon} strokeWidth={2} />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Copy prompt</TooltipContent>
          </Tooltip>
        </TooltipProvider>
      </div>
      <div className="mt-3 h-96 rounded-lg border border-border bg-muted/20 p-3">
        <ScrollArea className="h-full rounded-md bg-muted/50">
          <pre
            ref={promptPanel}
            tabIndex={-1}
            className="min-h-full whitespace-pre-wrap p-4 font-mono text-xs leading-6 outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
          >
            {prompt.prompt}
          </pre>
        </ScrollArea>
      </div>
      {manualCopyRequired ? (
        <p className="mt-3 text-sm text-muted-foreground" role="status">
          Clipboard access is unavailable. The prompt is selected so you can
          copy it manually.
        </p>
      ) : null}
    </section>
  )
}
