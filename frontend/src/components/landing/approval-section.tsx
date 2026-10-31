import { useState } from "react"

import { cn } from "cn"

import { approvalPoints } from "@/components/landing/landing-content"
import { SectionHeading } from "@/components/landing/section-heading"

type ApplyMode = "pull-request" | "local"

const modes: Array<{
  id: ApplyMode
  label: string
}> = [
  {
    id: "pull-request",
    label: "Pull request",
  },
  {
    id: "local",
    label: "Local apply",
  },
]

const diffLines = [
  {
    kind: "context",
    text: "@@ .env.example",
  },
  {
    kind: "remove",
    text: "- PAYMENTS_SECRET_KEY=sk_live_••••••••••••",
  },
  {
    kind: "add",
    text: "+ PAYMENTS_SECRET_KEY=",
  },
] as const

const footers: Record<ApplyMode, string> = {
  "pull-request": "Pull request opened and linked to the finding",
  local: "Backup saved, then applied to the selected folder",
}

const diffLineStyles = {
  context: "text-muted-foreground",
  remove: "bg-[#ff2047]/10 text-[#ff5c78]",
  add: "bg-[#11ff99]/10 text-[#11ff99]",
} as const

export function ApprovalSection() {
  const [mode, setMode] = useState<ApplyMode>("pull-request")

  return (
    <section
      aria-labelledby="approval-title"
      className="relative overflow-hidden py-24"
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 top-0 h-[560px] bg-[radial-gradient(ellipse_at_top,rgba(34,255,153,0.14),transparent_65%)]"
      />
      <div className="relative mx-auto grid w-full max-w-6xl items-center gap-12 px-6 md:px-10 lg:grid-cols-2 lg:gap-16">
        <div className="flex flex-col gap-10">
          <SectionHeading
            id="approval-title"
            align="left"
            eyebrow="Approval first"
            title="Nothing changes until you say so"
            description="Trace explains the risk, shows the diff and waits. You stay the only person who can ship a change."
          />
          <ol className="flex flex-col gap-6">
            {approvalPoints.map((point, index) => (
              <li
                key={point.title}
                className="flex gap-4"
              >
                <span className="flex size-7 shrink-0 items-center justify-center rounded-full border border-border bg-popover font-code text-xs">
                  {index + 1}
                </span>
                <div className="flex flex-col gap-1">
                  <h3 className="text-lg font-medium tracking-tight">
                    {point.title}
                  </h3>
                  <p className="text-base text-foreground/70">
                    {point.description}
                  </p>
                </div>
              </li>
            ))}
          </ol>
        </div>
        <div className="overflow-hidden rounded-xl border border-border bg-[#06060a]">
          <div className="flex items-center gap-4 border-b border-white/6 px-4 py-3">
            <div
              aria-hidden="true"
              className="flex items-center gap-1.5"
            >
              <span className="size-2.5 rounded-full bg-[#ff2047]" />
              <span className="size-2.5 rounded-full bg-[#ffc53d]" />
              <span className="size-2.5 rounded-full bg-[#11ff99]" />
            </div>
            <div
              role="tablist"
              aria-label="How an approved change is applied"
              className="flex gap-1"
            >
              {modes.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  role="tab"
                  id={`apply-tab-${item.id}`}
                  aria-selected={mode === item.id}
                  aria-controls="apply-panel"
                  onClick={() => setMode(item.id)}
                  className={cn(
                    "rounded-md px-3 py-1.5 font-code text-xs transition-colors focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none",
                    mode === item.id
                      ? "bg-card text-foreground"
                      : "text-foreground/60 hover:text-foreground",
                  )}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>
          <div
            role="tabpanel"
            id="apply-panel"
            aria-labelledby={`apply-tab-${mode}`}
            className="flex flex-col gap-4 p-6"
          >
            <p className="font-code text-xs text-muted-foreground">
              Finding accepted · Critical · Security
            </p>
            <pre className="overflow-x-auto rounded-md border border-white/8 bg-background py-2 font-code text-[13px] leading-relaxed">
              {diffLines.map((line) => (
                <code
                  key={line.text}
                  className={cn(
                    "block px-3",
                    diffLineStyles[line.kind],
                  )}
                >
                  {line.text}
                </code>
              ))}
            </pre>
            <p className="flex items-center gap-2 text-sm text-foreground/80">
              <span
                aria-hidden="true"
                className="size-2 rounded-full bg-[#11ff99]"
              />
              {footers[mode]}
            </p>
          </div>
        </div>
      </div>
    </section>
  )
}
