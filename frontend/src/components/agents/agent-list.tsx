import { BotIcon } from "@hugeicons/core-free-icons"
import { HugeiconsIcon } from "@hugeicons/react"
import { Link } from "react-router-dom"

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar"
import { Button } from "@/components/ui/button"
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty"
import type { Agent } from "@/hooks/use-agents"

function initials(name: string) {
  return name.split(" ").map((part) => part[0]).filter(Boolean).slice(0, 2).join("").toUpperCase()
}

function label(value: string) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (character) => character.toUpperCase())
}

function skillSummary(skills: Agent["skills"]) {
  if (skills.length === 0) return "No skills configured"
  const names = skills.filter((skill): skill is string => typeof skill === "string")
  const structured = skills.length - names.length
  return [...names, ...(structured ? [`${structured} configured skill${structured === 1 ? "" : "s"}`] : [])].join(" · ")
}

function AgentCard({ agent }: { agent: Agent }) {
  const disabled = agent.disabled_at !== null
  return (
    <Link
      to={`/agents/${agent.id}`}
      className={`block rounded-lg border border-white/14 bg-[#0a0a0c] p-5 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${disabled ? "opacity-60" : "hover:border-white/25"}`}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 items-center gap-3">
          <Avatar size="lg">
            <AvatarImage src={agent.avatar ?? undefined} alt="" />
            <AvatarFallback>
              {initials(agent.name) || <HugeiconsIcon icon={BotIcon} size={18} />}
            </AvatarFallback>
          </Avatar>
          <div className="min-w-0">
            <h2 className="truncate text-sm font-medium">{agent.name}</h2>
            <span className="mt-1 inline-flex rounded-sm border border-white/12 px-1.5 py-0.5 text-[11px] text-muted-foreground">
              {label(agent.review_category)}
            </span>
          </div>
        </div>
        <span
          className={`rounded-full border px-2 py-1 text-[11px] ${disabled ? "border-white/10 text-muted-foreground" : "border-[#11ff99]/30 text-[#11ff99]"}`}
        >
          {disabled ? "Disabled" : "Active"}
        </span>
      </div>
      <dl className="mt-5 grid grid-cols-2 gap-4 border-t border-white/6 pt-4 text-xs">
        <div>
          <dt className="text-muted-foreground">Model</dt>
          <dd className="mt-1 truncate font-mono text-foreground">
            {agent.model_provider}/{agent.model_name}
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Skills</dt>
          <dd className="mt-1 truncate text-foreground" title={skillSummary(agent.skills)}>
            {skillSummary(agent.skills)}
          </dd>
        </div>
      </dl>
    </Link>
  )
}

export function AgentList({ agents, onCreate }: { agents: Agent[]; onCreate: () => void }) {
  if (agents.length === 0) {
    return (
      <Empty className="min-h-80 border-white/14 bg-[#0a0a0c]">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <HugeiconsIcon icon={BotIcon} strokeWidth={2} />
          </EmptyMedia>
          <EmptyTitle>No agents yet</EmptyTitle>
          <EmptyDescription>
            Create a reviewer to choose its category and model.
          </EmptyDescription>
        </EmptyHeader>
        <EmptyContent>
          <Button type="button" onClick={onCreate}>
            Create agent
          </Button>
        </EmptyContent>
      </Empty>
    )
  }
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      {agents.map((agent) => (
        <AgentCard key={agent.id} agent={agent} />
      ))}
    </div>
  )
}
