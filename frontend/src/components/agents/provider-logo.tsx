import { useState } from "react"

import type { ModelProvider } from "@/lib/api"

const providerLogoUrls = {
  openai: "https://openai.com/favicon.ico",
  anthropic: "https://www.anthropic.com/favicon.ico",
  google: "https://gemini.google.com/favicon.ico",
  xai: "https://x.ai/favicon.ico",
} satisfies Record<ModelProvider, string>

const providerInitials = {
  openai: "O",
  anthropic: "A",
  google: "G",
  xai: "X",
} satisfies Record<ModelProvider, string>

export function ProviderLogo({ provider }: { provider: ModelProvider }) {
  const [failed, setFailed] = useState(false)

  return <span aria-hidden="true" className="flex size-4 shrink-0 items-center justify-center overflow-hidden rounded-sm bg-white p-px text-[9px] font-semibold text-black">{failed ? providerInitials[provider] : <img src={providerLogoUrls[provider]} alt="" className="size-full object-contain" onError={() => setFailed(true)} />}</span>
}
