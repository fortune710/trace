import { useEffect, useRef, useState } from "react"
import { Link, useParams } from "react-router-dom"

import { ProviderLogo } from "@/components/agents/provider-logo"
import { AppShell } from "@/components/layout/app-shell"
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { toast } from "@/components/ui/toast"
import {
  useAgent,
  useAgentModelCatalog,
  useDisableAgent,
  useProviderCredentials,
  useUpdateAgent,
} from "@/hooks/use-agents"
import type { Agent, AgentSkill, AgentUpdate, ModelProvider } from "@/lib/api"

type AgentTab = "personality" | "skills" | "model"

const tabs: Array<{ id: AgentTab; label: string }> = [
  { id: "personality", label: "Personality" },
  { id: "skills", label: "Skills" },
  { id: "model", label: "Model" },
]

const tabDescriptions: Record<
  AgentTab,
  { title: string; description: string }
> = {
  personality: {
    title: "Personality",
    description: "Describe how this agent should approach its reviews.",
  },
  skills: {
    title: "Skills",
    description: "Configure the expertise this agent can apply during reviews.",
  },
  model: {
    title: "Model provider",
    description: "Choose the model and access this agent uses for reviews.",
  },
}

const providerLabels = {
  openai: "OpenAI",
  anthropic: "Anthropic",
  google: "Google",
  xai: "xAI",
} satisfies Record<ModelProvider, string>

function categoryLabel(category: Agent["review_category"]) {
  return category
    .replaceAll("_", " ")
    .replace(/\b\w/g, (character) => character.toUpperCase())
}

function skillLabel(skill: AgentSkill, index: number) {
  return typeof skill === "string" ? skill : `Configured skill ${index + 1}`
}

function useDebouncedAgentSave(agentId: string) {
  const updateAgent = useUpdateAgent()
  const timeout = useRef<number | undefined>(undefined)

  useEffect(() => {
    return () => {
      if (timeout.current !== undefined) {
        window.clearTimeout(timeout.current)
      }
    }
  }, [])

  function save(values: AgentUpdate) {
    if (timeout.current !== undefined) {
      window.clearTimeout(timeout.current)
    }

    timeout.current = window.setTimeout(() => {
      updateAgent.mutate({ agentId, agent: values })
    }, 650)
  }

  return { save }
}

function PersonalitySetting({
  agent,
  disabled,
}: {
  agent: Agent
  disabled: boolean
}) {
  const [value, setValue] = useState(agent.personality ?? "")
  const { save } = useDebouncedAgentSave(agent.id)

  function handleChange(nextValue: string) {
    setValue(nextValue)
    save({ personality: nextValue.trim() || null })
  }

  return (
    <section
      role="tabpanel"
      id="agent-personality-panel"
      aria-labelledby="agent-personality-tab"
    >
      <textarea
        aria-label="Personality"
        value={value}
        onChange={(event) => handleChange(event.target.value)}
        disabled={disabled}
        maxLength={4000}
        placeholder="Add a personality…"
        className="min-h-36 w-full resize-y rounded-md border border-white/20 bg-input p-4 text-sm leading-6 outline-none transition-colors hover:border-white/40 focus-visible:border-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-60"
      />
    </section>
  )
}

function SkillsSetting({ agent, disabled }: { agent: Agent; disabled: boolean }) {
  const [isSkillsDialogOpen, setIsSkillsDialogOpen] = useState(false)

  if (agent.skills.length === 0) {
    return (
      <section
        role="tabpanel"
        id="agent-skills-panel"
        aria-labelledby="agent-skills-tab"
      >
        <button
          type="button"
          onClick={() => setIsSkillsDialogOpen(true)}
          disabled={disabled}
          className="w-full text-left disabled:cursor-default"
        >
          <Empty className="min-h-56 border-white/14 bg-[#0a0a0c] transition-colors enabled:hover:border-white/25 enabled:hover:bg-[#101012]">
            <EmptyHeader>
              <EmptyTitle className="text-base">No skills configured</EmptyTitle>
              <EmptyDescription>
                Skills will be available to configure here soon.
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        </button>
        <Dialog open={isSkillsDialogOpen} onOpenChange={setIsSkillsDialogOpen}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Skills are coming soon</DialogTitle>
              <DialogDescription>
                Skill configuration has not been integrated yet.
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button type="button" onClick={() => setIsSkillsDialogOpen(false)}>
                Close
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </section>
    )
  }

  return (
    <section
      role="tabpanel"
      id="agent-skills-panel"
      aria-labelledby="agent-skills-tab"
      className="overflow-hidden rounded-lg border border-white/14 bg-[#0a0a0c]"
    >
      {agent.skills.map((skill, index) => (
        <div
          key={`${skillLabel(skill, index)}-${index}`}
          className={`flex min-h-20 items-center px-5 ${
            index > 0 ? "border-t border-white/8" : ""
          }`}
        >
          <div>
            <h3 className="text-sm font-medium">{skillLabel(skill, index)}</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              Configured skill
            </p>
          </div>
        </div>
      ))}
    </section>
  )
}

function ModelSettings({ agent, disabled }: { agent: Agent; disabled: boolean }) {
  const catalog = useAgentModelCatalog()
  const credentials = useProviderCredentials()
  const updateAgent = useUpdateAgent()
  const [provider, setProvider] = useState(agent.model_provider)
  const [model, setModel] = useState(agent.model_name)
  const [credentialId, setCredentialId] = useState(
    agent.credential_id ?? "trace-managed"
  )
  const providers = catalog.data?.providers ?? []
  const models = providers.find((item) => item.id === provider)?.models ?? []
  const compatibleCredentials = credentials.credentials.filter(
    (credential) => credential.provider === provider
  )
  const controlsDisabled = disabled || updateAgent.isPending || catalog.isLoading

  function update(values: AgentUpdate, rollback: () => void) {
    updateAgent.mutate(
      { agentId: agent.id, agent: values },
      { onError: rollback }
    )
  }

  function handleProviderChange(value: string | null) {
    if (!value || value === provider) {
      return
    }

    const nextProvider = value as ModelProvider
    const nextModel = providers.find(
      (item) => item.id === nextProvider
    )?.models[0]?.id

    if (!nextModel) {
      return
    }

    const previous = { provider, model, credentialId }

    setProvider(nextProvider)
    setModel(nextModel)
    setCredentialId("trace-managed")
    update(
      {
        model_provider: nextProvider,
        model_name: nextModel,
        credential_id: null,
      },
      () => {
        setProvider(previous.provider)
        setModel(previous.model)
        setCredentialId(previous.credentialId)
      }
    )
  }

  function handleModelChange(value: string | null) {
    if (!value || value === model) {
      return
    }

    const previous = model

    setModel(value)
    update({ model_name: value }, () => setModel(previous))
  }

  function handleAccessChange(value: string | null) {
    if (!value || value === credentialId) {
      return
    }

    const previous = credentialId

    setCredentialId(value)
    update(
      { credential_id: value === "trace-managed" ? null : value },
      () => setCredentialId(previous)
    )
  }

  return (
    <section
      role="tabpanel"
      id="agent-model-panel"
      aria-labelledby="agent-model-tab"
      className="-m-5 overflow-hidden"
    >
      <div className="flex flex-col gap-4 px-5 py-5 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-sm font-medium">Provider</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            The company that supplies this agent’s language model.
          </p>
        </div>
        <Select
          value={provider}
          onValueChange={handleProviderChange}
          disabled={controlsDisabled}
        >
          <SelectTrigger
            aria-label="Model provider"
            className="w-full min-w-48 justify-between rounded-md sm:w-56"
          >
            <SelectValue>
              <span className="flex items-center gap-2">
                <ProviderLogo provider={provider} />
                {providers.find((item) => item.id === provider)?.label ??
                  providerLabels[provider]}
              </span>
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            {providers.map((item) => (
              <SelectItem key={item.id} value={item.id}>
                <span className="flex items-center gap-2">
                  <ProviderLogo provider={item.id} />
                  {item.label}
                </span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="flex flex-col gap-4 border-t border-white/8 px-5 py-5 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-sm font-medium">Model</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            The specific model this agent uses for reviews.
          </p>
        </div>
        <Select
          value={model}
          onValueChange={handleModelChange}
          disabled={controlsDisabled || models.length === 0}
        >
          <SelectTrigger
            aria-label="Model"
            className="w-full min-w-48 justify-between rounded-md sm:w-56"
          >
            <SelectValue>
              {models.find((item) => item.id === model)?.label ?? model}
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            {models.map((item) => (
              <SelectItem key={item.id} value={item.id}>
                {item.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="flex flex-col gap-4 border-t border-white/8 px-5 py-5 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-sm font-medium">Access</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            How this agent authenticates with its model provider.
          </p>
        </div>
        <Select
          value={credentialId}
          onValueChange={handleAccessChange}
          disabled={controlsDisabled}
        >
          <SelectTrigger
            aria-label="Model access"
            className="w-full min-w-48 justify-between rounded-md sm:w-56"
          >
            <SelectValue>
              {credentialId === "trace-managed"
                ? "Trace-managed access"
                : (compatibleCredentials.find(
                    (credential) => credential.id === credentialId,
                  )?.name ?? `Your ${providerLabels[provider]} API key`)}
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="trace-managed">Trace-managed access</SelectItem>
            {compatibleCredentials.map((credential) => (
              <SelectItem key={credential.id} value={credential.id}>
                {credential.name ?? `Your ${providerLabels[provider]} API key`}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </section>
  )
}

export function AgentDetailsPage() {
  const { agentId } = useParams()
  const [activeTab, setActiveTab] = useState<AgentTab>("personality")
  const [isDisableOpen, setIsDisableOpen] = useState(false)
  const agent = useAgent(agentId)
  const disableAgent = useDisableAgent()

  function disable() {
    if (!agent.data) {
      return
    }

    disableAgent.mutate(agent.data.id, {
      onSuccess: () => {
        toast.add({
          type: "success",
          title: "Agent disabled",
          description: "It will no longer be available for new reviews.",
        })
        setIsDisableOpen(false)
      },
      onError: () => {
        toast.add({
          type: "error",
          title: "Agent could not be disabled",
          description: "Please try again.",
        })
      },
    })
  }

  const disabled = agent.data?.disabled_at !== null

  return (
    <AppShell>
      <section className="mx-auto w-full max-w-6xl px-6 py-8 md:px-10 md:py-10">
        <Breadcrumb>
          <BreadcrumbList>
            <BreadcrumbItem>
              <BreadcrumbLink render={<Link to="/agents" />}>
                Agents
              </BreadcrumbLink>
            </BreadcrumbItem>
            <BreadcrumbSeparator />
            <BreadcrumbItem>
              <BreadcrumbPage>{agent.data?.name ?? "Agent"}</BreadcrumbPage>
            </BreadcrumbItem>
          </BreadcrumbList>
        </Breadcrumb>

        {agent.isLoading ? (
          <p className="mt-6 text-sm text-muted-foreground">Loading agent…</p>
        ) : null}

        {agent.isError ? (
          <div className="mt-6 grid justify-items-start gap-3">
            <p className="text-sm text-muted-foreground">
              We could not load this agent.
            </p>
            <Button type="button" variant="outline" onClick={() => void agent.refetch()}>
              Try again
            </Button>
          </div>
        ) : null}

        {agent.data ? (
          <>
            <div className="mt-6 flex flex-wrap items-start justify-between gap-4">
              <div>
                <h1 className="text-xl font-medium tracking-tight">
                  {agent.data.name}
                </h1>
                <span className="mt-2 inline-flex rounded-sm border border-white/12 px-1.5 py-0.5 text-[11px] text-muted-foreground">
                  {categoryLabel(agent.data.review_category)}
                </span>
              </div>
              {disabled ? (
                <span className="rounded-full border border-white/10 px-2 py-1 text-[11px] text-muted-foreground">
                  Disabled
                </span>
              ) : (
                <Button
                  type="button"
                  variant="destructive"
                  onClick={() => setIsDisableOpen(true)}
                >
                  Disable
                </Button>
              )}
            </div>

            {disabled ? (
              <p className="mt-5 text-sm text-muted-foreground">
                Disabled agents are read-only and cannot be selected for new reviews.
              </p>
            ) : null}

            <div
              className="mt-8 border-b border-white/10"
              role="tablist"
              aria-label="Agent details"
            >
              {tabs.map((tab) => (
                <button
                  key={tab.id}
                  type="button"
                  role="tab"
                  id={`agent-${tab.id}-tab`}
                  aria-selected={activeTab === tab.id}
                  aria-controls={`agent-${tab.id}-panel`}
                  onClick={() => setActiveTab(tab.id)}
                  className={`mr-5 border-b-2 px-1 pb-3 text-sm transition-colors ${
                    activeTab === tab.id
                      ? "border-foreground text-foreground"
                      : "border-transparent text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </div>

            <div className="mt-6 px-4">
              <h2 className="text-sm font-medium">
                {tabDescriptions[activeTab].title}
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                {tabDescriptions[activeTab].description}
              </p>
            </div>

            <div className="mt-4">
              <div hidden={activeTab !== "personality"}>
                <PersonalitySetting
                  key={`${agent.data.id}-personality`}
                  agent={agent.data}
                  disabled={disabled}
                />
              </div>
              <div hidden={activeTab !== "skills"}>
                <SkillsSetting
                  key={`${agent.data.id}-skills`}
                  agent={agent.data}
                  disabled={disabled}
                />
              </div>
              <div
                hidden={activeTab !== "model"}
                className="rounded-lg border border-white/14 bg-[#0a0a0c] p-5"
              >
                <ModelSettings key={agent.data.id} agent={agent.data} disabled={disabled} />
              </div>
            </div>
          </>
        ) : null}
      </section>

      <Dialog open={isDisableOpen} onOpenChange={setIsDisableOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Disable {agent.data?.name}?</DialogTitle>
            <DialogDescription>
              This agent stays visible for history but cannot be selected for new
              reviews. It cannot be re-enabled yet.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => setIsDisableOpen(false)}>
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              disabled={disableAgent.isPending}
              onClick={disable}
            >
              {disableAgent.isPending ? "Disabling…" : "Disable agent"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </AppShell>
  )
}
