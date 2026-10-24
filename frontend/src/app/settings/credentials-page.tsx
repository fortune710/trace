import { useState, type FormEvent } from "react"
import { NavLink, Navigate } from "react-router-dom"

import { AppShell } from "@/components/layout/app-shell"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { toast } from "@/components/ui/toast"
import { useAgentModelCatalog, useProviderCredentials, useSaveProviderCredential } from "@/hooks/use-agents"
import type { ModelProvider } from "@/lib/api"

type ProviderKeyDialogProps = { provider: ModelProvider | null; label: string; open: boolean; onOpenChange: (open: boolean) => void }

function ProviderKeyDialog({ provider, label, open, onOpenChange }: ProviderKeyDialogProps) {
  const [apiKey, setApiKey] = useState("")
  const save = useSaveProviderCredential()

  function close(nextOpen: boolean) {
    onOpenChange(nextOpen)
    if (!nextOpen) setApiKey("")
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!provider || !apiKey.trim()) return
    save.mutate({ provider, kind: "api_key", payload: { api_key: apiKey.trim() } }, { onSuccess: () => { toast.add({ type: "success", title: `${label} key saved`, description: "Your key is encrypted and ready for agent configuration." }); close(false) }, onError: () => toast.add({ type: "error", title: "Key could not be saved", description: "Please try again." }) })
  }

  return <Dialog open={open} onOpenChange={close}><DialogContent><DialogHeader><DialogTitle>Save {label} API key</DialogTitle><DialogDescription>Your key is encrypted before storage and is never shown again.</DialogDescription></DialogHeader><form id="provider-key-form" onSubmit={submit}><div className="grid gap-2"><Label htmlFor="provider-api-key">API key</Label><Input id="provider-api-key" type="password" autoComplete="new-password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} required /></div></form><DialogFooter><Button type="button" variant="ghost" onClick={() => close(false)}>Cancel</Button><Button type="submit" form="provider-key-form" disabled={save.isPending || !apiKey.trim()}>{save.isPending ? "Saving…" : "Save API key"}</Button></DialogFooter></DialogContent></Dialog>
}

export function CredentialsPage() {
  const catalog = useAgentModelCatalog()
  const credentials = useProviderCredentials()
  const [selected, setSelected] = useState<{ provider: ModelProvider; label: string } | null>(null)

  if (catalog.isLoading) return <AppShell><section className="mx-auto w-full max-w-6xl px-6 py-8 md:px-10 md:py-10"><p className="text-sm text-muted-foreground">Loading settings…</p></section></AppShell>
  if (catalog.isError) return <AppShell><section className="mx-auto w-full max-w-6xl px-6 py-8 md:px-10 md:py-10"><Button type="button" variant="outline" onClick={() => void catalog.refetch()}>Try again</Button></section></AppShell>

  return <AppShell><section className="mx-auto grid w-full max-w-6xl gap-8 px-6 py-8 md:grid-cols-[11rem_1fr] md:px-10 md:py-10"><aside><h1 className="text-xl font-medium tracking-tight md:hidden">Settings</h1><nav className="mt-4 flex gap-2 md:mt-0 md:flex-col" aria-label="Settings"><NavLink to="/settings/credentials" className="rounded-md bg-[#101012] px-3 py-2 text-sm text-foreground">Credentials</NavLink></nav></aside><div><h1 className="hidden text-xl font-medium tracking-tight md:block">Credentials</h1><p className="mt-1 text-sm text-muted-foreground">Save an API key for a model provider, then choose it from an agent’s access settings.</p><div className="mt-8 grid gap-4 md:grid-cols-2">{catalog.data?.providers.map((provider) => { const credential = credentials.credentials.find((item) => item.provider === provider.id); return <article key={provider.id} className="rounded-lg border border-white/14 bg-[#0a0a0c] p-5"><div className="flex items-start justify-between gap-4"><div><h2 className="text-sm font-medium">{provider.label}</h2><p className="mt-1 text-xs text-muted-foreground">{credential ? "API key saved" : "Use Trace-managed access or save your own key."}</p></div><span className={`rounded-full border px-2 py-1 text-[11px] ${credential ? "border-[#11ff99]/30 text-[#11ff99]" : "border-white/10 text-muted-foreground"}`}>{credential ? "Connected" : "Not connected"}</span></div><p className="mt-5 truncate font-mono text-xs text-muted-foreground">{provider.models.map((model) => model.id).join(" · ")}</p><div className="mt-5"><Button type="button" variant="outline" size="sm" onClick={() => setSelected({ provider: provider.id, label: provider.label })}>{credential ? "Replace API key" : "Save API key"}</Button></div></article> })}</div>{credentials.isError ? <p role="alert" className="mt-4 text-sm text-destructive">Could not load your saved credentials. Try refreshing this page.</p> : null}</div></section><ProviderKeyDialog provider={selected?.provider ?? null} label={selected?.label ?? "provider"} open={selected !== null} onOpenChange={(open) => !open && setSelected(null)} /></AppShell>
}

export function SettingsIndexRedirect() {
  return <Navigate to="/settings/credentials" replace />
}
