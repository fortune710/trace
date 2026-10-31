import { useFindingRemediations } from "@/hooks/use-findings"
import {
  parseUnifiedDiff,
  type DiffLineKind,
  type FileDiff,
} from "@/components/findings/unified-diff"

function lineClassName(kind: DiffLineKind) {
  switch (kind) {
    case "addition":
      return "bg-emerald-500/10 text-foreground"
    case "deletion":
      return "bg-red-500/10 text-foreground"
    case "context":
      return "text-foreground"
  }
}

function lineMarker(kind: DiffLineKind) {
  if (kind === "addition") return "+"
  if (kind === "deletion") return "−"
  return " "
}

function displayLineNumber(line: FileDiff["lines"][number]) {
  return line.newLineNumber ?? line.oldLineNumber ?? ""
}

function FileDiffAccordion({ file }: { file: FileDiff }) {
  return (
    <details className="group border-b border-border last:border-b-0">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-4 px-3 py-2.5 text-sm hover:bg-muted/50 [&::-webkit-details-marker]:hidden">
        <span className="min-w-0 truncate font-mono text-xs font-medium">
          {file.path}
        </span>
        <span className="flex shrink-0 gap-2 font-mono text-xs tabular-nums">
          {file.additions > 0 ? (
            <span className="text-emerald-700 dark:text-emerald-300">
              +{file.additions}
            </span>
          ) : null}
          {file.deletions > 0 ? (
            <span className="text-red-700 dark:text-red-300">
              −{file.deletions}
            </span>
          ) : null}
        </span>
      </summary>
      {file.lines.length > 0 ? (
        <div className="overflow-hidden border-t border-border font-mono text-xs leading-5">
          {file.lines.map((line, index) => (
            <div
              key={`${line.oldLineNumber}-${line.newLineNumber}-${index}`}
              className={`grid min-w-0 grid-cols-[3.5rem_1.5rem_minmax(0,1fr)] ${lineClassName(line.kind)}`}
            >
              <span className="border-r border-current/10 px-2 text-right text-muted-foreground/80 select-none">
                {displayLineNumber(line)}
              </span>
              <span className="border-r border-current/10 text-center select-none">
                {lineMarker(line.kind)}
              </span>
              <code className="min-w-0 break-all px-3 whitespace-pre-wrap">
                {line.content || " "}
              </code>
            </div>
          ))}
        </div>
      ) : (
        <p className="border-t border-border px-3 py-3 text-sm text-muted-foreground">
          No textual changes to display.
        </p>
      )}
    </details>
  )
}

export function UnifiedDiffRenderer({ diff }: { diff: string }) {
  const files = parseUnifiedDiff(diff)

  if (files.length === 0) {
    return (
      <p className="px-3 py-3 text-sm text-muted-foreground">
        The proposed diff could not be parsed.
      </p>
    )
  }

  return (
    <div className="overflow-hidden rounded-md border border-border bg-muted/20">
      {files.map((file, index) => (
        <FileDiffAccordion key={`${file.path}-${index}`} file={file} />
      ))}
    </div>
  )
}

export function ProposedDiff({ findingId }: { findingId: string }) {
  const remediations = useFindingRemediations(findingId)
  const remediation = remediations.data?.[0]
  const diff = remediation?.proposed_diff

  if (remediation?.generation_status === "pending" || remediation?.generation_status === "running") {
    return (
      <p className="mt-6 text-sm text-muted-foreground">Preparing changes…</p>
    )
  }

  if (remediation?.status === "proposed" && (remediation.generation_failure || remediation.generation_status === "failed" || remediation.generation_status === "legacy_unverified")) {
    return (
      <p
        className="mt-6 text-sm text-muted-foreground"
        role="status"
      >
        The finding is saved. Automated changes are unavailable: {remediation.generation_failure?.message ?? "this patch has not been verified"}.
      </p>
    )
  }

  if (!diff) return null

  return (
    <section className="mt-6" aria-labelledby="proposed-changes-heading">
      <h2 id="proposed-changes-heading" className="text-sm font-medium">
        Proposed changes
      </h2>
      <div className="mt-3">
        {remediation?.preview_is_redacted ? (
          <p className="mb-2 text-xs text-muted-foreground">Redacted preview — applying changes uses the verified original patch.</p>
        ) : null}
        <UnifiedDiffRenderer diff={diff} />
      </div>
    </section>
  )
}
