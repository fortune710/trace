import { cn } from "cn"

type Severity = "info" | "low" | "medium" | "high" | "critical"

type MockFinding = {
  title: string
  severity: Severity
  category: string
  status: "Open" | "Accepted"
  selected?: boolean
}

type MockReviewer = {
  name: string
  initials: string
  category: string
  status: "Completed" | "Running"
  custom?: boolean
}

const severityStyles: Record<Severity, string> = {
  info: "bg-[#3b9eff]/12 text-[#3b9eff]",
  low: "bg-[#11ff99]/10 text-[#11ff99]",
  medium: "bg-[#ffc53d]/12 text-[#ffc53d]",
  high: "bg-[#ff2047]/14 text-[#ff5c78]",
  critical: "bg-[#ff2047]/14 text-[#ff5c78]",
}

const reviewers: MockReviewer[] = [
  {
    name: "Sentinel",
    initials: "SE",
    category: "Security",
    status: "Completed",
    custom: true,
  },
  {
    name: "Mark Zuckerberg",
    initials: "MZ",
    category: "Engineering",
    status: "Completed",
  },
  {
    name: "Harvey Specter",
    initials: "HS",
    category: "Legal",
    status: "Completed",
  },
  {
    name: "Super PM",
    initials: "PM",
    category: "Product",
    status: "Running",
  },
]

const findings: MockFinding[] = [
  {
    title: "Live payment key committed in .env.example",
    severity: "critical",
    category: "Security",
    status: "Open",
    selected: true,
  },
  {
    title: "Webhook handler has no error handling or retry path",
    severity: "high",
    category: "Engineering",
    status: "Open",
  },
  {
    title: "Analytics script loads before consent is collected",
    severity: "medium",
    category: "Legal",
    status: "Accepted",
  },
  {
    title: "No empty state after a first project import",
    severity: "low",
    category: "Product",
    status: "Open",
  },
]

const sidebarItems = ["Projects", "Agents", "Integrations"]

function TrafficLights() {
  return (
    <div className="flex items-center gap-1.5">
      <span className="size-2.5 rounded-full bg-[#ff2047]" />
      <span className="size-2.5 rounded-full bg-[#ffc53d]" />
      <span className="size-2.5 rounded-full bg-[#11ff99]" />
    </div>
  )
}

function SeverityLabel({
  severity,
  category,
}: Pick<MockFinding, "severity" | "category">) {
  return (
    <span className="flex items-center gap-1.5 text-[10px] font-medium tracking-wide uppercase">
      <span
        className={cn(
          "rounded px-1.5 py-0.5",
          severityStyles[severity],
        )}
      >
        {severity}
      </span>
      <span className="text-muted-foreground">{category}</span>
    </span>
  )
}

export function ReviewMockup() {
  return (
    <figure className="mx-auto w-full max-w-6xl px-6 md:px-10">
      <p className="sr-only">
        Product preview: a completed Trace review of a project called Trace
        dashboard. Four reviewers report findings sorted by severity, including
        a critical security finding with evidence, a recommendation and a
        proposed change that is waiting for approval.
      </p>
      <div
        aria-hidden="true"
        className="overflow-hidden rounded-xl border border-border bg-[#06060a] text-left"
      >
        <div className="flex items-center justify-between border-b border-white/6 px-4 py-3">
          <TrafficLights />
          <span className="font-code text-xs text-muted-foreground">
            trace · Trace dashboard
          </span>
          <span className="w-12" />
        </div>
        <div className="grid md:grid-cols-[200px_1fr]">
          <aside className="hidden flex-col gap-1 border-r border-white/6 bg-card p-3 md:flex">
            <span className="px-2 py-2 font-mono text-sm">trace</span>
            {sidebarItems.map((item, index) => (
              <span
                key={item}
                className={cn(
                  "rounded-md px-2 py-1.5 text-sm text-muted-foreground",
                  index === 0 && "bg-popover text-foreground",
                )}
              >
                {item}
              </span>
            ))}
          </aside>
          <div className="flex min-w-0 flex-col gap-6 p-4 md:p-6">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="flex flex-col gap-1">
                <p className="text-xs text-muted-foreground">
                  Projects / Trace dashboard
                </p>
                <p className="text-lg font-medium">Review</p>
                <p className="font-code text-xs text-muted-foreground">
                  main · a1b2c3d4e5f6
                </p>
              </div>
              <span className="rounded-md bg-[#ffc53d]/12 px-2 py-0.5 text-xs font-medium text-[#ffc53d]">
                Running
              </span>
            </div>
            <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
              {reviewers.map((reviewer) => (
                <div
                  key={reviewer.name}
                  className="flex items-center gap-2.5 rounded-lg border border-white/8 bg-card p-2.5"
                >
                  <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-popover text-[10px] font-medium">
                    {reviewer.initials}
                  </span>
                  <span className="flex min-w-0 flex-col">
                    <span className="truncate text-xs font-medium">
                      {reviewer.name}
                    </span>
                    <span className="truncate text-[11px] text-muted-foreground">
                      {reviewer.category}
                      {reviewer.custom ? " · Custom" : ""}
                    </span>
                  </span>
                  <span
                    title={reviewer.status}
                    className={cn(
                      "ml-auto size-2 shrink-0 rounded-full",
                      reviewer.status === "Completed"
                        ? "bg-[#11ff99]"
                        : "bg-[#ffc53d]",
                    )}
                  />
                </div>
              ))}
            </div>
            <div className="grid gap-4 lg:grid-cols-[1fr_1.1fr]">
              <ul className="flex flex-col gap-2">
                {findings.map((finding) => (
                  <li
                    key={finding.title}
                    className={cn(
                      "flex flex-col gap-2 rounded-lg border border-white/8 bg-card p-3",
                      finding.selected && "border-white/25 bg-popover",
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <SeverityLabel
                        severity={finding.severity}
                        category={finding.category}
                      />
                      <span
                        className={cn(
                          "rounded-full px-2 py-0.5 text-[10px] font-medium",
                          finding.status === "Open"
                            ? "bg-primary text-primary-foreground"
                            : "bg-[#11ff99]/12 text-[#11ff99]",
                        )}
                      >
                        {finding.status}
                      </span>
                    </div>
                    <p className="text-sm leading-snug">{finding.title}</p>
                  </li>
                ))}
              </ul>
              <div className="hidden flex-col gap-4 rounded-lg border border-white/8 bg-card p-4 lg:flex">
                <div className="flex flex-col gap-1">
                  <SeverityLabel
                    severity="critical"
                    category="Security"
                  />
                  <p className="text-base font-medium">
                    Live payment key committed in .env.example
                  </p>
                  <p className="font-code text-xs text-muted-foreground">
                    .env.example:3
                  </p>
                </div>
                <div className="flex flex-col gap-1.5">
                  <p className="text-xs text-muted-foreground">Evidence</p>
                  <pre className="overflow-hidden rounded-md border border-white/8 bg-[#06060a] p-3 font-code text-xs text-foreground/85">
                    PAYMENTS_SECRET_KEY=sk_live_••••••••••••
                  </pre>
                </div>
                <div className="flex flex-col gap-1.5">
                  <p className="text-xs text-muted-foreground">
                    Recommendation
                  </p>
                  <p className="text-sm text-foreground/80">
                    Remove the key from the repository, rotate it, and load it
                    from your host&apos;s secret store.
                  </p>
                </div>
                <div className="flex gap-2">
                  <span className="rounded-md border border-[#11ff99]/30 bg-[#11ff99]/10 px-3 py-1.5 text-xs font-medium text-[#11ff99]">
                    Accept
                  </span>
                  <span className="rounded-md border border-border px-3 py-1.5 text-xs text-foreground/70">
                    Dismiss
                  </span>
                  <span className="rounded-md border border-border px-3 py-1.5 text-xs text-foreground/40">
                    Create pull request
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </figure>
  )
}
