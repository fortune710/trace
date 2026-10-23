import type { ModelProvider } from "@/lib/api"

const providerInitials = {
  openai: "O",
  anthropic: "A",
  google: "G",
  xai: "X",
} satisfies Record<ModelProvider, string>

export function ProviderLogo({ provider }: { provider: ModelProvider }) {
  // Render a local initial mark instead of hotlinking third-party
  // favicons: external requests would leak the user's IP address and
  // request metadata to four third parties on every page load, and a
  // strict img-src CSP (web or Tauri) blocks them anyway.
  return (
    <span
      aria-hidden="true"
      className="flex size-4 shrink-0 items-center justify-center overflow-hidden rounded-sm bg-white p-px text-[9px] font-semibold text-black"
    >
      {providerInitials[provider]}
    </span>
  )
}
