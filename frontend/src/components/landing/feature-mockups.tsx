import type { ReactNode } from "react"

import { cn } from "cn"

import { ProviderLogo } from "@/components/agents/provider-logo"
import { reviewCategories } from "@/components/landing/landing-content"
import { Github } from "@/components/logos/github"
import { Linear } from "@/components/logos/linear"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"

const reviewerRows = [
  {
    name: "Mark Zuckerberg",
    details: "engineering · openai/gpt-6.1-sol",
  },
  {
    name: "Harvey Specter",
    details: "legal · openai/gpt-6.1-sol",
  },
  {
    name: "Super PM",
    details: "product · openai/gpt-6.1-sol",
  },
  {
    name: "Sentinel",
    details: "security · anthropic/claude-sonnet-5-5",
  },
]

function MockupSurface({
  className,
  children,
}: {
  className?: string
  children: ReactNode
}) {
  return (
    <div
      aria-hidden="true"
      inert
      className={cn(
        "min-w-0 max-w-full overflow-hidden rounded-lg border border-white/8 bg-background p-4 text-left",
        className,
      )}
    >
      {children}
    </div>
  )
}

export function ReviewAnglesMockup() {
  return (
    <MockupSurface className="flex flex-col gap-4">
      <ul className="flex flex-wrap gap-1.5">
        {reviewCategories.map((category) => (
          <li
            key={category}
            className="rounded-full border border-white/10 bg-popover px-2.5 py-0.5 text-xs text-foreground/85"
          >
            {category}
          </li>
        ))}
      </ul>
      <fieldset className="grid gap-2">
        <legend className="mb-2 text-sm font-medium">Reviewers</legend>
        {reviewerRows.map((reviewer) => (
          <label
            key={reviewer.name}
            className="flex items-start gap-3 rounded-md border border-border p-3 text-sm"
          >
            <input
              type="checkbox"
              checked
              readOnly
              tabIndex={-1}
              className="mt-1 size-4"
            />
            <span className="grid min-w-0 gap-0.5">
              <span>{reviewer.name}</span>
              <span className="truncate text-xs font-normal text-muted-foreground">
                {reviewer.details}
              </span>
            </span>
          </label>
        ))}
      </fieldset>
    </MockupSurface>
  )
}

export function EvidenceMockup() {
  return (
    <MockupSurface className="grid grid-cols-1 gap-5 p-5">
      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-2">
          <Badge className="rounded-md border-0 bg-red-500/15 uppercase text-red-300">
            critical
          </Badge>
          <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
            security
          </p>
        </div>
        <p className="text-lg font-medium tracking-tight">
          Live payment key committed in .env.example
        </p>
        <p className="text-sm text-muted-foreground">
          A live payment key sits in a file that ships with the repository, so
          anyone who can read the code can use it.
        </p>
      </div>
      <dl className="grid grid-cols-1 gap-4 text-sm">
        <div>
          <dt className="text-muted-foreground">Evidence</dt>
          <dd className="mt-1">
            <pre className="overflow-hidden rounded-md bg-muted/50 p-3 font-mono text-xs break-all whitespace-pre-wrap">
              PAYMENTS_SECRET_KEY=sk_live_••••••••••••
            </pre>
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Source location</dt>
          <dd className="mt-1 flex flex-wrap gap-1">
            <Badge
              variant="outline"
              className="rounded-sm font-mono text-xs"
            >
              .env.example
            </Badge>
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Recommendation</dt>
          <dd className="mt-1">
            Remove the key from the repository, rotate it, and load it from your
            host&apos;s secret store.
          </dd>
        </div>
      </dl>
    </MockupSurface>
  )
}

export function AgentConfigMockup() {
  return (
    <MockupSurface className="border-white/14 bg-[#101012] p-5">
      <p className="text-base font-medium">Create agent</p>
      <p className="mt-1 text-sm text-muted-foreground">
        Choose the reviewer’s specialty and model access.
      </p>
      <div className="mt-5 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="grid min-w-0 grid-cols-1 content-start gap-4">
          <div className="grid gap-2">
            <Label htmlFor="mock-agent-name">Name</Label>
            <Input
              id="mock-agent-name"
              value="Sentinel"
              readOnly
              tabIndex={-1}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="mock-agent-category">Review category</Label>
            <Select value="security">
              <SelectTrigger
                id="mock-agent-category"
                className="w-full"
                tabIndex={-1}
              >
                <SelectValue>Security</SelectValue>
              </SelectTrigger>
            </Select>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="mock-agent-personality">
              Personality{" "}
              <span className="text-muted-foreground">optional</span>
            </Label>
            <textarea
              id="mock-agent-personality"
              readOnly
              tabIndex={-1}
              value="Direct and practical. Explains each risk in plain language, then orders fixes by severity."
              className="min-h-24 w-full resize-none rounded-md border border-white/25 bg-input px-3 py-2 text-sm"
            />
          </div>
        </div>
        <div className="grid min-w-0 grid-cols-1 content-start gap-4">
          <div className="grid gap-2">
            <Label htmlFor="mock-agent-provider">Provider</Label>
            <Select value="openai">
              <SelectTrigger
                id="mock-agent-provider"
                className="w-full"
                tabIndex={-1}
              >
                <SelectValue>
                  <span className="flex items-center gap-2">
                    <ProviderLogo provider="openai" />
                    OpenAI
                  </span>
                </SelectValue>
              </SelectTrigger>
            </Select>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="mock-agent-model">Model</Label>
            <Select value="gpt-6.1-sol">
              <SelectTrigger
                id="mock-agent-model"
                className="w-full"
                tabIndex={-1}
              >
                <SelectValue>GPT-6.1 Sol</SelectValue>
              </SelectTrigger>
            </Select>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="mock-agent-access">Model access</Label>
            <Select value="trace-managed">
              <SelectTrigger
                id="mock-agent-access"
                className="w-full"
                tabIndex={-1}
              >
                <SelectValue>Trace-managed access</SelectValue>
              </SelectTrigger>
            </Select>
            <p className="text-xs text-muted-foreground">
              Compatible keys are managed in Settings → API keys.
            </p>
          </div>
        </div>
      </div>
    </MockupSurface>
  )
}

const issueTrackers = [
  {
    label: "GitHub issue",
    Logo: Github,
  },
  {
    label: "Linear issue",
    Logo: Linear,
  },
]

export function HandoffMockup() {
  return (
    <MockupSurface className="flex flex-col gap-5">
      <div className="flex flex-col gap-2">
        <Badge className="h-auto w-fit rounded-sm bg-green-500/15 px-1.5 py-0.5 text-sm font-semibold text-green-300">
          Accepted
        </Badge>
        <p className="text-sm font-medium">
          Live payment key committed in .env.example
        </p>
      </div>
      <div className="w-full max-w-[17rem]">
        <div className="flex items-stretch">
          <Button
            type="button"
            tabIndex={-1}
            className="rounded-r-none"
          >
            <Github
              aria-hidden="true"
              className="size-4 shrink-0"
            />
            Create pull request
          </Button>
          <Select value={null}>
            <SelectTrigger
              aria-label="Choose issue tracker"
              tabIndex={-1}
              className="h-9 rounded-l-none rounded-r-md border-l border-l-primary-foreground/30 bg-primary px-2 text-primary-foreground [&_svg]:text-primary-foreground"
            >
              <SelectValue className="sr-only">Create issue</SelectValue>
            </SelectTrigger>
          </Select>
        </div>
        <div className="mt-1 rounded-lg bg-popover p-1 ring-1 ring-foreground/5">
          <p className="px-3 py-2.5 text-xs text-muted-foreground">
            Issue trackers
          </p>
          {issueTrackers.map(({ label, Logo }, index) => (
            <div
              key={label}
              className={cn(
                "flex items-center gap-2.5 rounded-md py-2 pl-3 text-sm",
                index === 0 && "bg-white/10",
              )}
            >
              <Logo
                aria-hidden="true"
                className="size-4 shrink-0"
              />
              {label}
            </div>
          ))}
        </div>
      </div>
    </MockupSurface>
  )
}
