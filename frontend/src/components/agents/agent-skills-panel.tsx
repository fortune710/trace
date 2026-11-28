import { useDeferredValue, useState } from "react"
import { Cancel01Icon, PlusSignIcon } from "@hugeicons/core-free-icons"
import { HugeiconsIcon } from "@hugeicons/react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
} from "@/components/ui/empty"
import { Input } from "@/components/ui/input"
import { toast } from "@/components/ui/toast"
import {
  useAttachAgentSkill,
  useCuratedSkills,
  useDetachAgentSkill,
  useSkillsSearch,
} from "@/hooks/use-agents"
import { trackEvent } from "@/lib/analytics"
import { ApiError, type Agent, type AgentSkill, type SkillsCatalogSkill } from "@/lib/api"

function skillName(skill: AgentSkill, index: number) {
  if (typeof skill === "string") {
    return skill
  }
  if (typeof skill.name === "string" && skill.name.trim()) {
    return skill.name
  }
  if (typeof skill.id === "string" && skill.id.trim()) {
    return skill.id
  }
  return `Configured skill ${index + 1}`
}

function skillSource(skill: AgentSkill) {
  if (typeof skill === "string") {
    return "Custom label"
  }
  if (typeof skill.source === "string" && skill.source.trim()) {
    return skill.source
  }
  if (skill.provider === "skills.sh") {
    return "skills.sh"
  }
  return "Configured skill"
}

function skillId(skill: AgentSkill) {
  if (
    typeof skill === "object" &&
    skill.provider === "skills.sh" &&
    typeof skill.id === "string"
  ) {
    return skill.id
  }
  return null
}

function attachedIds(skills: AgentSkill[]) {
  return new Set(
    skills
      .map((skill) => skillId(skill))
      .filter((value): value is string => Boolean(value)),
  )
}

export function AgentSkillsPanel({
  agent,
  disabled,
}: {
  agent: Agent
  disabled: boolean
}) {
  const [isDialogOpen, setIsDialogOpen] = useState(false)
  const [query, setQuery] = useState("")
  const deferredQuery = useDeferredValue(query.trim())
  const search = useSkillsSearch(deferredQuery)
  const curated = useCuratedSkills(isDialogOpen && deferredQuery.length < 2)
  const attachSkill = useAttachAgentSkill(agent.id)
  const detachSkill = useDetachAgentSkill(agent.id)
  const selected = attachedIds(agent.skills)

  const catalogSkills: SkillsCatalogSkill[] =
    deferredQuery.length >= 2
      ? (search.data?.data ?? [])
      : (curated.data?.data ?? [])

  function openPicker() {
    trackEvent("agent_skills_picker_opened", { agent_id: agent.id })
    setIsDialogOpen(true)
  }

  function handleAttach(skill: SkillsCatalogSkill) {
    attachSkill.mutate(skill.id, {
      onSuccess: () => {
        toast.add({
          type: "success",
          title: "Skill attached",
          description: `${skill.name} is available for this agent’s reviews.`,
        })
      },
      onError: (error) => {
        toast.add({
          type: "error",
          title: "Could not attach skill",
          description:
            error instanceof ApiError
              ? error.message
              : "Please try again in a moment.",
        })
      },
    })
  }

  function handleDetach(id: string, name: string) {
    detachSkill.mutate(id, {
      onSuccess: () => {
        toast.add({
          type: "success",
          title: "Skill removed",
          description: `${name} will no longer be used for new reviews.`,
        })
      },
      onError: () => {
        toast.add({
          type: "error",
          title: "Could not remove skill",
          description: "Please try again in a moment.",
        })
      },
    })
  }

  return (
    <section
      role="tabpanel"
      id="agent-skills-panel"
      aria-labelledby="agent-skills-tab"
    >
      {agent.skills.length === 0 ? (
        <button
          type="button"
          onClick={openPicker}
          disabled={disabled}
          className="w-full text-left disabled:cursor-default"
        >
          <Empty className="min-h-56 border-white/14 bg-[#0a0a0c] transition-colors enabled:hover:border-white/25 enabled:hover:bg-[#101012]">
            <EmptyHeader>
              <EmptyTitle className="text-base">No skills configured</EmptyTitle>
              <EmptyDescription>
                Browse skills.sh and attach expertise this agent can apply during
                reviews.
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        </button>
      ) : (
        <div className="overflow-hidden rounded-lg border border-white/14 bg-[#0a0a0c]">
          {agent.skills.map((skill, index) => {
            const id = skillId(skill)
            return (
              <div
                key={`${skillName(skill, index)}-${index}`}
                className={`flex min-h-20 items-center justify-between gap-4 px-5 ${
                  index > 0 ? "border-t border-white/8" : ""
                }`}
              >
                <div className="min-w-0">
                  <h3 className="truncate text-sm font-medium">
                    {skillName(skill, index)}
                  </h3>
                  <p className="mt-1 truncate text-sm text-muted-foreground">
                    {skillSource(skill)}
                  </p>
                </div>
                {id && !disabled ? (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    aria-label={`Remove ${skillName(skill, index)}`}
                    disabled={detachSkill.isPending}
                    onClick={() => handleDetach(id, skillName(skill, index))}
                  >
                    <HugeiconsIcon icon={Cancel01Icon} size={16} strokeWidth={2} />
                  </Button>
                ) : null}
              </div>
            )
          })}
          {disabled ? null : (
            <div className="border-t border-white/8 px-5 py-4">
              <Button
                type="button"
                variant="outline"
                onClick={openPicker}
              >
                <HugeiconsIcon icon={PlusSignIcon} size={16} strokeWidth={2} />
                Add skill
              </Button>
            </div>
          )}
        </div>
      )}

      <Dialog open={isDialogOpen} onOpenChange={setIsDialogOpen}>
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle>Add skills from skills.sh</DialogTitle>
            <DialogDescription>
              Search the catalog or pick from curated skills. Trace resolves and
              stores skill content server-side for reviews.
            </DialogDescription>
          </DialogHeader>

          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search skills…"
            aria-label="Search skills"
            autoFocus
          />

          <div className="max-h-80 overflow-y-auto rounded-md border border-white/12">
            {deferredQuery.length >= 2 && search.isLoading ? (
              <p className="px-4 py-6 text-sm text-muted-foreground">
                Searching skills…
              </p>
            ) : null}
            {deferredQuery.length < 2 && curated.isLoading ? (
              <p className="px-4 py-6 text-sm text-muted-foreground">
                Loading curated skills…
              </p>
            ) : null}
            {(deferredQuery.length >= 2 ? search.isError : curated.isError) &&
            catalogSkills.length === 0 ? (
              <p className="px-4 py-6 text-sm text-muted-foreground">
                The skills catalog is temporarily unavailable.
              </p>
            ) : null}
            {!(deferredQuery.length >= 2 ? search.isLoading : curated.isLoading) &&
            !(deferredQuery.length >= 2 ? search.isError : curated.isError) &&
            catalogSkills.length === 0 ? (
              <p className="px-4 py-6 text-sm text-muted-foreground">
                {deferredQuery.length >= 2
                  ? "No skills matched that search."
                  : "No curated skills were returned."}
              </p>
            ) : null}
            {catalogSkills.map((skill) => {
              const attached = selected.has(skill.id)
              return (
                <div
                  key={skill.id}
                  className="flex items-start justify-between gap-3 border-b border-white/8 px-4 py-3 last:border-b-0"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">{skill.name}</p>
                    <p className="mt-1 truncate text-xs text-muted-foreground">
                      {skill.source}
                      {typeof skill.installs === "number"
                        ? ` · ${skill.installs.toLocaleString()} installs`
                        : ""}
                    </p>
                  </div>
                  <Button
                    type="button"
                    size="sm"
                    variant={attached ? "ghost" : "outline"}
                    disabled={attached || attachSkill.isPending || disabled}
                    onClick={() => handleAttach(skill)}
                  >
                    {attached ? "Added" : "Add"}
                  </Button>
                </div>
              )
            })}
          </div>

          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => setIsDialogOpen(false)}>
              Done
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  )
}
