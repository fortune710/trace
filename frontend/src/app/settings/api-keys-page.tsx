import { useRef, useState, type FormEvent } from "react"
import { Navigate } from "react-router-dom"

import { AppShell } from "@/components/layout/app-shell"
import { ProviderLogo } from "@/components/agents/provider-logo"
import { ApiKeysPageSkeleton } from "@/components/settings/api-keys-page-skeleton"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { toast } from "@/components/ui/toast"
import {
  useCreateProviderCredential,
  useProviderCredentials,
  useRotateProviderCredential,
} from "@/hooks/use-agents"
import type { ModelProvider } from "@/lib/api"

const providerDetails: Array<{
  provider: ModelProvider
  title: string
  description: string
}> = [
  {
    provider: "openai",
    title: "OpenAI API Key",
    description: "Use OpenAI models with your own API key.",
  },
  {
    provider: "anthropic",
    title: "Anthropic API Key",
    description: "Use Claude models with your own API key.",
  },
  {
    provider: "google",
    title: "Google API Key",
    description: "Use Google models with your Google AI Studio key.",
  },
  {
    provider: "xai",
    title: "xAI API Key",
    description: "Use Grok models with your own xAI API key.",
  },
]

function ProviderApiKeyCard({
  provider,
  title,
  description,
}: (typeof providerDetails)[number]) {
  const credentials = useProviderCredentials()
  const create = useCreateProviderCredential()
  const rotate = useRotateProviderCredential()
  const [apiKey, setApiKey] = useState("")
  const submittingKey = useRef<string | null>(null)
  const credential = credentials.credentials.find(
    (item) => item.provider === provider,
  )
  const isSaving = create.isPending || rotate.isPending

  function saveApiKey() {
    const nextApiKey = apiKey.trim()
    if (!nextApiKey || isSaving || submittingKey.current === nextApiKey) {
      return
    }

    submittingKey.current = nextApiKey
    const payload = {
      provider,
      kind: "api_key" as const,
      payload: { api_key: nextApiKey },
    }
    const callbacks = {
      onSuccess: () => {
        setApiKey("")
        submittingKey.current = null
        toast.add({
          type: "success",
          title: "API key saved",
          description: `${title} is encrypted and ready for agents.`,
        })
      },
      onError: () => {
        submittingKey.current = null
        toast.add({
          type: "error",
          title: "Key could not be saved",
          description: "Please try again.",
        })
      },
    }

    if (credential) {
      rotate.mutate(
        { credentialId: credential.id, credential: payload },
        callbacks,
      )
      return
    }

    create.mutate(payload, callbacks)
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    saveApiKey()
  }

  return (
    <section aria-labelledby={`${provider}-api-key-heading`}>
      <h2
        id={`${provider}-api-key-heading`}
        className="flex items-center gap-3 text-xl font-medium tracking-tight"
      >
        <ProviderLogo provider={provider} className="size-6" />
        {title}
      </h2>
      <p className="mt-1 text-base text-muted-foreground">{description}</p>
      <form
        className="mt-4 rounded-lg border border-white/6 bg-card p-4"
        onSubmit={handleSubmit}
      >
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <Label htmlFor={`${provider}-api-key`} className="text-base">
            API Key
          </Label>
          <Input
            id={`${provider}-api-key`}
            type="password"
            autoComplete="new-password"
            value={apiKey}
            onChange={(event) => setApiKey(event.target.value)}
            placeholder={
              credential ? "API key saved — enter a new key" : "Enter API key"
            }
            disabled={isSaving}
            className="h-10 w-full sm:max-w-80"
          />
        </div>
        <p className="mt-4 text-sm text-muted-foreground">
          {isSaving
            ? "Saving your API key…"
            : "Press Enter to save. Keys are encrypted and never shown again."}
        </p>
      </form>
    </section>
  )
}

export function ApiKeysPage() {
  const credentials = useProviderCredentials()

  if (credentials.isLoading) {
    return (
      <AppShell>
        <section className="mx-auto w-full max-w-6xl px-6 py-8 md:px-10 md:py-10">
          <ApiKeysPageSkeleton />
        </section>
      </AppShell>
    )
  }

  return (
    <AppShell>
      <section className="mx-auto w-full max-w-6xl px-6 py-8 md:px-10 md:py-10">
        <div className="grid max-w-4xl gap-12">
          <header className="max-w-2xl">
            <h1 className="text-xl font-medium tracking-tight">API keys</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Save your own API keys for model providers, then choose them from
              an agent&rsquo;s access settings. Keys are encrypted before
              storage and never shown again.
            </p>
          </header>
          {providerDetails.map((details) => (
            <ProviderApiKeyCard key={details.provider} {...details} />
          ))}
        </div>
        {credentials.isError ? (
          <p role="alert" className="mt-6 text-sm text-destructive">
            Could not load your saved API keys. You can still save a replacement
            key for a provider.
          </p>
        ) : null}
      </section>
    </AppShell>
  )
}

export function SettingsIndexRedirect() {
  return <Navigate to="/settings/api-keys" replace />
}

export function LegacyCredentialsRedirect() {
  return <Navigate to="/settings/api-keys" replace />
}
