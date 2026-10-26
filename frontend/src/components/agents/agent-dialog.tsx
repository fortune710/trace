import { useState, type FormEvent } from "react"

import { Button } from "@/components/ui/button"
import { ProviderLogo } from "@/components/agents/provider-logo"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { toast } from "@/components/ui/toast"
import {
  type Agent,
  type AgentModelCatalog,
  type ModelProvider,
  type ReviewCategory,
} from "@/lib/api"
import { useCreateAgent, useUpdateAgent, type Credential } from "@/hooks/use-agents"

const categories: Array<{ value: ReviewCategory; label: string }> = [
  { value: "security", label: "Security" },
  { value: "engineering", label: "Engineering" },
  { value: "product", label: "Product" },
  { value: "legal", label: "Legal" },
  { value: "accessibility", label: "Accessibility" },
  { value: "marketing", label: "Marketing" },
]

type AgentDialogProps = {
  agent: Agent | null
  catalog: AgentModelCatalog | undefined
  credentials: Credential[]
  open: boolean
  onOpenChange: (open: boolean) => void
}

function optionLabel<T extends { value: string; label: string }>(options: T[], value: string) {
  return options.find((option) => option.value === value)?.label ?? value
}

export function AgentDialog({ agent, catalog, credentials, open, onOpenChange }: AgentDialogProps) {
  const createAgent = useCreateAgent()
  const updateAgent = useUpdateAgent()
  const providers = catalog?.providers ?? []
  const initialProvider = agent?.model_provider ?? providers[0]?.id ?? "openai"
  const initialModels = providers.find((provider) => provider.id === initialProvider)?.models ?? []
  const initialModel = agent?.model_name ?? initialModels[0]?.id ?? ""
  const [name, setName] = useState(agent?.name ?? "")
  const [personality, setPersonality] = useState(agent?.personality ?? "")
  const [category, setCategory] = useState<ReviewCategory>(agent?.review_category ?? "security")
  const [provider, setProvider] = useState<ModelProvider>(initialProvider)
  const [model, setModel] = useState(initialModel)
  const [avatar, setAvatar] = useState(agent?.avatar ?? "")
  const [credentialId, setCredentialId] = useState(agent?.credential_id ?? "")

  const models = providers.find((item) => item.id === provider)?.models ?? []
  const compatibleCredentials = credentials.filter((credential) => credential.provider === provider)
  const isPending = createAgent.isPending || updateAgent.isPending
  const isEditing = agent !== null

  function handleProviderChange(value: string | null) {
    if (!value) return
    const nextProvider = value as ModelProvider
    const nextModels = providers.find((item) => item.id === nextProvider)?.models ?? []
    setProvider(nextProvider)
    setModel(nextModels[0]?.id ?? "")
    setCredentialId("")
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!name.trim() || !model) return

    const values = {
      name: name.trim(),
      personality: personality.trim() || null,
      review_category: category,
      model_provider: provider,
      model_name: model,
      avatar: avatar.trim() || null,
      credential_id: credentialId || null,
    }
    const callbacks = {
      onSuccess: () => {
        toast.add({ type: "success", title: isEditing ? "Agent updated" : "Agent created", description: "Your review configuration is ready." })
        onOpenChange(false)
      },
      onError: () => toast.add({ type: "error", title: "Agent could not be saved", description: "Check the configuration and try again." }),
    }
    if (agent) {
      updateAgent.mutate({ agentId: agent.id, agent: values }, callbacks)
    } else {
      createAgent.mutate({ ...values, skills: [] }, callbacks)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[calc(100svh-2rem)] max-w-xl overflow-y-auto border-white/14 bg-[#101012]">
        <DialogHeader>
          <DialogTitle>{isEditing ? "Edit agent" : "Create agent"}</DialogTitle>
          <DialogDescription>Choose the reviewer’s specialty and model access. Skills are managed separately.</DialogDescription>
        </DialogHeader>
        <form id="agent-form" className="grid gap-4" onSubmit={handleSubmit}>
          <div className="grid gap-2"><Label htmlFor="agent-name">Name</Label><Input id="agent-name" value={name} onChange={(event) => setName(event.target.value)} maxLength={120} required /></div>
          <div className="grid gap-2"><Label htmlFor="agent-personality">Personality <span className="text-muted-foreground">optional</span></Label><textarea id="agent-personality" value={personality} onChange={(event) => setPersonality(event.target.value)} maxLength={4000} className="min-h-24 w-full rounded-md border border-white/25 bg-input px-3 py-2 text-sm outline-none transition-colors hover:border-white/40 focus-visible:border-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50" /></div>
          <div className="grid gap-2"><Label htmlFor="agent-category">Review category</Label><Select value={category} onValueChange={(value) => value && setCategory(value as ReviewCategory)}><SelectTrigger id="agent-category" className="w-full"><SelectValue>{optionLabel(categories, category)}</SelectValue></SelectTrigger><SelectContent>{categories.map((item) => <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>)}</SelectContent></Select></div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="grid gap-2"><Label htmlFor="agent-provider">Provider</Label><Select value={provider} onValueChange={handleProviderChange}><SelectTrigger id="agent-provider" className="w-full"><SelectValue><span className="flex items-center gap-2"><ProviderLogo provider={provider} />{providers.find((item) => item.id === provider)?.label ?? provider}</span></SelectValue></SelectTrigger><SelectContent>{providers.map((item) => <SelectItem key={item.id} value={item.id}><span className="flex items-center gap-2"><ProviderLogo provider={item.id} />{item.label}</span></SelectItem>)}</SelectContent></Select></div>
            <div className="grid gap-2"><Label htmlFor="agent-model">Model</Label><Select value={model} onValueChange={(value) => value && setModel(value)} disabled={models.length === 0}><SelectTrigger id="agent-model" className="w-full"><SelectValue>{models.find((item) => item.id === model)?.label ?? "Choose model"}</SelectValue></SelectTrigger><SelectContent>{models.map((item) => <SelectItem key={item.id} value={item.id}>{item.label}</SelectItem>)}</SelectContent></Select></div>
          </div>
          <div className="grid gap-2"><Label htmlFor="agent-credential">Model access</Label><Select value={credentialId || "trace-managed"} onValueChange={(value) => setCredentialId(value === "trace-managed" ? "" : value ?? "")}><SelectTrigger id="agent-credential" className="w-full"><SelectValue>{credentialId ? (compatibleCredentials.find((credential) => credential.id === credentialId)?.name ?? "Your API key") : "Trace-managed access"}</SelectValue></SelectTrigger><SelectContent><SelectItem value="trace-managed">Trace-managed access</SelectItem>{compatibleCredentials.map((credential) => <SelectItem key={credential.id} value={credential.id}>{credential.name ?? `Your ${provider} API key`}</SelectItem>)}</SelectContent></Select><p className="text-xs text-muted-foreground">Compatible keys are managed in Settings → API keys.</p></div>
          <div className="grid gap-2"><Label htmlFor="agent-avatar">Avatar image URL <span className="text-muted-foreground">optional</span></Label><Input id="agent-avatar" type="url" value={avatar} onChange={(event) => setAvatar(event.target.value)} placeholder="https://…" /></div>
        </form>
        <DialogFooter><Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button><Button type="submit" form="agent-form" disabled={isPending || !catalog || !name.trim() || !model}>{isPending ? "Saving…" : isEditing ? "Save changes" : "Create agent"}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
