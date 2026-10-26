import { useState, type FormEvent } from "react"
import { Navigate } from "react-router-dom"

import { AppShell } from "@/components/layout/app-shell"
import { Button } from "@/components/ui/button"
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
  useAgentModelCatalog,
  useCreateProviderCredential,
  useProviderCredentials,
  useRevokeProviderCredential,
} from "@/hooks/use-agents"
import type { ModelProvider } from "@/lib/api"

function CreateApiKeyDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const catalog = useAgentModelCatalog()
  const create = useCreateProviderCredential()
  const providers = catalog.data?.providers ?? []
  const [name, setName] = useState("")
  const [provider, setProvider] = useState<ModelProvider | "">("")
  const [apiKey, setApiKey] = useState("")

  function close(nextOpen: boolean) {
    onOpenChange(nextOpen)
    if (!nextOpen) {
      setName("")
      setProvider("")
      setApiKey("")
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const trimmedName = name.trim()
    const trimmedKey = apiKey.trim()
    if (!trimmedName || !provider || !trimmedKey) return
    create.mutate(
      {
        provider,
        kind: "api_key",
        name: trimmedName,
        payload: { api_key: trimmedKey },
      },
      {
        onSuccess: () => {
          toast.add({
            type: "success",
            title: "API key saved",
            description: "Your key is encrypted and ready for agent configuration.",
          })
          close(false)
        },
        onError: () =>
          toast.add({
            type: "error",
            title: "Key could not be saved",
            description: "A key with that name may already exist. Please try again.",
          }),
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Create API key</DialogTitle>
          <DialogDescription>
            Your key is encrypted before storage and is never shown again. Give
            each key a name so you can tell your keys apart when linking them
            to an agent.
          </DialogDescription>
        </DialogHeader>
        <form id="create-api-key-form" className="grid gap-4" onSubmit={submit}>
          <div className="grid gap-2">
            <Label htmlFor="api-key-name">Name</Label>
            <Input
              id="api-key-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              maxLength={100}
              placeholder="Primary OpenAI key"
              required
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="api-key-provider">Provider</Label>
            <Select
              value={provider}
              onValueChange={(value) => value && setProvider(value as ModelProvider)}
            >
              <SelectTrigger id="api-key-provider" className="w-full">
                <SelectValue>
                  {providers.find((item) => item.id === provider)?.label ??
                    "Choose provider"}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                {providers.map((item) => (
                  <SelectItem key={item.id} value={item.id}>
                    {item.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="api-key-value">API key</Label>
            <Input
              id="api-key-value"
              type="password"
              autoComplete="new-password"
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              required
            />
          </div>
        </form>
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={() => close(false)}>
            Cancel
          </Button>
          <Button
            type="submit"
            form="create-api-key-form"
            disabled={
              create.isPending || !name.trim() || !provider || !apiKey.trim()
            }
          >
            {create.isPending ? "Saving…" : "Create API key"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function ApiKeysPage() {
  const catalog = useAgentModelCatalog()
  const credentials = useProviderCredentials()
  const revoke = useRevokeProviderCredential()
  const [dialogOpen, setDialogOpen] = useState(false)

  if (catalog.isLoading) {
    return (
      <AppShell>
        <section className="mx-auto w-full max-w-6xl px-6 py-8 md:px-10 md:py-10">
          <p className="text-sm text-muted-foreground">Loading settings…</p>
        </section>
      </AppShell>
    )
  }
  const providerLabels = new Map<string, string>(
    catalog.data?.providers.map((item) => [item.id, item.label]) ?? [],
  )

  function handleRevoke(credentialId: string, name: string | null) {
    revoke.mutate(credentialId, {
      onSuccess: () =>
        toast.add({
          type: "success",
          title: "API key revoked",
          description: name
            ? `"${name}" can no longer be used by agents.`
            : "The key can no longer be used by agents.",
        }),
      onError: () =>
        toast.add({
          type: "error",
          title: "Key could not be revoked",
          description: "Please try again.",
        }),
    })
  }

  return (
    <AppShell>
      <section className="mx-auto w-full max-w-6xl px-6 py-8 md:px-10 md:py-10">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-xl font-medium tracking-tight">API keys</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Save your own API keys for model providers, then choose them from
              an agent&rsquo;s access settings. Keys are encrypted before storage
              and never shown again.
            </p>
          </div>
          <Button type="button" onClick={() => setDialogOpen(true)}>
            Create API key
          </Button>
        </div>
        {catalog.isError ? (
          <div
            role="alert"
            className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-destructive/40 bg-destructive/10 p-4"
          >
            <p className="text-sm text-destructive">
              Provider labels could not be loaded. Provider IDs are used as
              labels while the catalog is unavailable.
            </p>
            <Button
              type="button"
              variant="outline"
              onClick={() => void catalog.refetch()}
            >
              Try again
            </Button>
          </div>
        ) : null}
        {credentials.isLoading ? (
          <p className="mt-8 text-sm text-muted-foreground">
            Loading your API keys…
          </p>
        ) : credentials.credentials.length === 0 ? (
          <div className="mt-8 rounded-lg border border-white/14 bg-[#0a0a0c] p-8 text-center">
            <p className="text-sm font-medium">No API keys yet</p>
            <p className="mt-1 text-sm text-muted-foreground">
              Create your first key to let agents run on your own provider
              access instead of Trace-managed access.
            </p>
            <Button
              type="button"
              variant="outline"
              className="mt-5"
              onClick={() => setDialogOpen(true)}
            >
              Create API key
            </Button>
          </div>
        ) : (
          <div className="mt-8 grid gap-4">
            {credentials.credentials.map((credential) => (
              <article
                key={credential.id}
                className="flex flex-wrap items-start justify-between gap-4 rounded-lg border border-white/14 bg-[#0a0a0c] p-5"
              >
                <div className="min-w-0">
                  <h2 className="truncate text-sm font-medium">
                    {credential.name ?? "Unnamed key"}
                  </h2>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {providerLabels.get(credential.provider) ??
                      credential.provider}
                    {" · "}Created{" "}
                    {new Date(credential.created_at).toLocaleDateString()}
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  <span className="rounded-full border border-[#11ff99]/30 px-2 py-1 text-[11px] text-[#11ff99]">
                    Active
                  </span>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={revoke.isPending}
                    onClick={() =>
                      handleRevoke(credential.id, credential.name)
                    }
                  >
                    Revoke
                  </Button>
                </div>
              </article>
            ))}
          </div>
        )}
        {credentials.isError ? (
          <p role="alert" className="mt-4 text-sm text-destructive">
            Could not load your saved API keys. Try refreshing this page.
          </p>
        ) : null}
      </section>
      <CreateApiKeyDialog open={dialogOpen} onOpenChange={setDialogOpen} />
    </AppShell>
  )
}

export function SettingsIndexRedirect() {
  return <Navigate to="/settings/api-keys" replace />
}

export function LegacyCredentialsRedirect() {
  return <Navigate to="/settings/api-keys" replace />
}
