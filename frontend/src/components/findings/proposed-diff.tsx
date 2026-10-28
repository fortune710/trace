import { useFindingRemediations } from "@/hooks/use-findings"

function lineClassName(line: string) {
  if (line.startsWith("+") && !line.startsWith("+++")) {
    return "bg-emerald-500/10 text-emerald-800 dark:text-emerald-300"
  }
  if (line.startsWith("-") && !line.startsWith("---")) {
    return "bg-red-500/10 text-red-800 dark:text-red-300"
  }
  if (line.startsWith("@@") || line.startsWith("diff --git")) {
    return "bg-muted text-muted-foreground"
  }
  return "text-foreground"
}

export function ProposedDiff({ findingId }: { findingId: string }) {
  const remediations = useFindingRemediations(findingId)
  const diff = remediations.data?.[0]?.proposed_diff

  if (!diff) return null

  return (
    <section className="mt-6" aria-labelledby="proposed-diff-heading">
      <h2 id="proposed-diff-heading" className="text-sm font-medium">
        Proposed diff
      </h2>
      <pre className="mt-3 overflow-x-auto rounded-md border border-border bg-muted/30 py-2 font-mono text-xs leading-5">
        {diff.split("\n").map((line, index) => (
          <code
            key={`${index}-${line}`}
            className={`block min-w-full px-3 ${lineClassName(line)}`}
          >
            {line || " "}
          </code>
        ))}
      </pre>
    </section>
  )
}
