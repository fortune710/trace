import {
  BotIcon,
  Folder01Icon,
  MessageNotification01Icon,
  Search01Icon,
  Settings01Icon,
} from "@hugeicons/core-free-icons"
import { HugeiconsIcon } from "@hugeicons/react"

import { FindingCard } from "@/components/findings/review-findings"
import { Badge } from "@/components/ui/badge"
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import type { Finding, ReviewCategory } from "@/lib/api"

type MockReviewer = {
  name: string
  category: ReviewCategory
}

const reviewers: Record<string, MockReviewer> = {
  sentinel: {
    name: "Sentinel",
    category: "security",
  },
  mark: {
    name: "Mark Zuckerberg",
    category: "engineering",
  },
  harvey: {
    name: "Harvey Specter",
    category: "legal",
  },
  pm: {
    name: "Super PM",
    category: "product",
  },
}

function mockFinding(
  id: string,
  reviewerKey: keyof typeof reviewers,
  overrides: Pick<
    Finding,
    "severity" | "title" | "explanation" | "source_location" | "status"
  >,
): Finding {
  const reviewer = reviewers[reviewerKey]

  return {
    id,
    review_id: "mock-review",
    agent_id: `agent-${reviewerKey}`,
    reviewing_agent: {
      assignment_id: `assignment-${reviewerKey}`,
      agent_id: `agent-${reviewerKey}`,
      display_name: reviewer.name,
      specialization: reviewer.category,
    },
    category: reviewer.category,
    evidence: null,
    recommendation: null,
    created_at: "2026-10-21T00:00:30Z",
    updated_at: "2026-10-21T00:00:30Z",
    ...overrides,
  }
}

const findings: Finding[] = [
  mockFinding("mock-1", "sentinel", {
    severity: "critical",
    title: "Live payment key committed in .env.example",
    explanation:
      "A live payment key sits in a file that ships with the repository, so anyone who can read the code can use it.",
    source_location: ".env.example",
    status: "open",
  }),
  mockFinding("mock-2", "mark", {
    severity: "high",
    title: "Webhook handler has no error handling or retry path",
    explanation:
      "The payment webhook updates the order without catching failures, so a transient database error silently drops the event.",
    source_location: "src/server/webhooks/payments.ts",
    status: "open",
  }),
  mockFinding("mock-3", "harvey", {
    severity: "medium",
    title: "Analytics script loads before consent is collected",
    explanation:
      "Tracking starts on first paint, before the visitor has accepted or declined cookies.",
    source_location: "src/app/layout.tsx",
    status: "accepted",
  }),
  mockFinding("mock-4", "pm", {
    severity: "low",
    title: "No empty state after a first project import",
    explanation:
      "A new account sees a blank table until the first review finishes.",
    source_location: "src/app/projects/page.tsx",
    status: "open",
  }),
]

const sidebarItems = [
  {
    label: "Projects",
    icon: Folder01Icon,
  },
  {
    label: "Agents",
    icon: BotIcon,
  },
  {
    label: "Notifications",
    icon: MessageNotification01Icon,
  },
  {
    label: "Settings",
    icon: Settings01Icon,
  },
]

const summaryFields = [
  {
    label: "Source",
    value: "GitHub",
  },
  {
    label: "Source identifier",
    value: "812094336",
    mono: true,
  },
  {
    label: "Captured",
    value: "10/20/2026, 8:00:00 PM",
  },
]

const filters = [
  {
    id: "mock-finding-category",
    label: "Category",
    value: "All categories",
  },
  {
    id: "mock-finding-severity",
    label: "Severity",
    value: "All severities",
  },
  {
    id: "mock-finding-status",
    label: "Status",
    value: "All statuses",
  },
  {
    id: "mock-finding-reviewer",
    label: "Reviewer",
    value: "All reviewers",
  },
]

function TrafficLights() {
  return (
    <div className="flex items-center gap-1.5">
      <span className="size-2.5 rounded-full bg-[#ff2047]" />
      <span className="size-2.5 rounded-full bg-[#ffc53d]" />
      <span className="size-2.5 rounded-full bg-[#11ff99]" />
    </div>
  )
}

function MockSidebar() {
  return (
    <aside className="hidden w-64 shrink-0 flex-col justify-between border-r border-sidebar-border bg-sidebar text-sidebar-foreground md:flex">
      <div className="flex flex-col gap-2 px-3 py-4">
        <div className="flex items-center justify-between">
          <span className="font-mono text-sm tracking-tight">trace</span>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            tabIndex={-1}
            className="text-muted-foreground"
          >
            <HugeiconsIcon
              icon={Search01Icon}
              size={17}
              strokeWidth={2}
            />
          </Button>
        </div>
        <ul className="flex flex-col gap-1 pt-2">
          {sidebarItems.map((item) => (
            <li
              key={item.label}
              className="flex h-9 items-center gap-2 rounded-sm px-3 py-2 text-sm"
            >
              <HugeiconsIcon
                icon={item.icon}
                size={17}
                strokeWidth={2}
              />
              <span>{item.label}</span>
            </li>
          ))}
        </ul>
      </div>
      <div className="px-3 pb-4">
        <div className="flex items-center gap-3 px-2 py-2">
          <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-sidebar-accent text-xs font-medium">
            AL
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-medium">
              Ada Lovelace
            </span>
            <span className="block truncate text-xs text-muted-foreground">
              ada@example.com
            </span>
          </span>
        </div>
      </div>
    </aside>
  )
}

function MockReviewPage() {
  return (
    <div className="min-w-0 flex-1 px-6 py-8 md:px-10 md:py-10">
      <Breadcrumb className="hidden md:block">
        <BreadcrumbList>
          <BreadcrumbItem>Projects</BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>Trace dashboard</BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbPage>Review 5f2c9d1e</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

      <div className="md:mt-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xl font-medium tracking-tight">
              Review 5f2c9d1e
            </p>
            <p className="mt-2 text-sm text-muted-foreground">
              The selected reviewers have finished this review.
            </p>
          </div>
          <Button
            type="button"
            tabIndex={-1}
          >
            Start another review
          </Button>
        </div>

        <dl className="mt-8 hidden grid-cols-2 gap-x-6 gap-y-5 text-sm md:grid lg:grid-cols-4">
          <div className="min-w-0">
            <dt className="text-muted-foreground">Status</dt>
            <dd className="mt-1">
              <Badge className="h-auto rounded-sm bg-green-500/15 px-1.5 py-0.5 text-sm font-semibold text-green-300">
                Completed
              </Badge>
            </dd>
          </div>
          {summaryFields.map((field) => (
            <div
              key={field.label}
              className="min-w-0"
            >
              <dt className="text-muted-foreground">{field.label}</dt>
              <dd
                className={
                  field.mono
                    ? "mt-1 font-mono break-all text-foreground"
                    : "mt-1 text-foreground"
                }
              >
                {field.value}
              </dd>
            </div>
          ))}
        </dl>

        <div className="mt-8 border-b border-border">
          <span className="mr-5 inline-block border-b-2 border-transparent px-1 pb-3 text-sm text-muted-foreground">
            Overview
          </span>
          <span className="inline-block border-b-2 border-foreground px-1 pb-3 text-sm text-foreground">
            Findings
          </span>
        </div>

        <div className="mt-8">
          <p className="text-base font-medium">Findings</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Risks reported by the reviewers selected for this snapshot.
          </p>
          <div className="mt-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
            {filters.map((filter) => (
              <div
                key={filter.id}
                className="grid gap-1"
              >
                <Label htmlFor={filter.id}>{filter.label}</Label>
                <Select value="all">
                  <SelectTrigger
                    id={filter.id}
                    className="w-full rounded-sm"
                    tabIndex={-1}
                  >
                    <SelectValue>{filter.value}</SelectValue>
                  </SelectTrigger>
                </Select>
              </div>
            ))}
          </div>
          <div className="mt-6 grid gap-3">
            {findings.map((finding) => (
              <FindingCard
                key={finding.id}
                finding={finding}
                onStatusChange={() => undefined}
                pending={false}
                error={null}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

export function ReviewMockup() {
  return (
    <figure className="mx-auto w-full max-w-6xl px-6 md:px-10">
      <p className="sr-only">
        Product preview: the Findings tab of a completed Trace review for a
        project called Trace dashboard. Findings from four reviewers are listed
        with their severity, category, reviewer and source file, each with
        Accept and Dismiss actions.
      </p>
      <div
        aria-hidden="true"
        inert
        className="overflow-hidden rounded-xl border border-border bg-background text-left"
      >
        <div className="flex items-center justify-between border-b border-white/6 px-4 py-3">
          <TrafficLights />
          <span className="font-mono text-xs text-muted-foreground">
            Trace
          </span>
          <span className="w-12" />
        </div>
        <div className="relative flex max-h-[620px] overflow-hidden md:max-h-[940px]">
          <MockSidebar />
          <MockReviewPage />
          <div className="pointer-events-none absolute inset-x-0 bottom-0 h-32 bg-linear-to-t from-background to-transparent" />
        </div>
      </div>
    </figure>
  )
}
