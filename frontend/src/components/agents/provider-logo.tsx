import { AnthropicFill } from "@/components/logos/anthropic"
import { GoogleGeminiIcon } from "@/components/logos/gemini"
import { OpenaiChatgpt } from "@/components/logos/openai"
import { Xai } from "@/components/logos/xai"
import type { ModelProvider } from "@/lib/api"

export function ProviderLogo({
  provider,
  className = "size-4",
}: {
  provider: ModelProvider
  className?: string
}) {
  if (provider === "openai") {
    return (
      <OpenaiChatgpt aria-hidden="true" className={`${className} shrink-0`} />
    )
  }

  if (provider === "anthropic") {
    return (
      <AnthropicFill aria-hidden="true" className={`${className} shrink-0`} />
    )
  }

  if (provider === "xai") {
    return <Xai aria-hidden="true" className={`${className} shrink-0`} />
  }

  return (
    <GoogleGeminiIcon aria-hidden="true" className={`${className} shrink-0`} />
  )
}
