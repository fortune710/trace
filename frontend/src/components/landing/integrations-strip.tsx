import type { ComponentType, SVGProps } from "react"

import Anthropic from "@/components/logos/anthropic"
import Github from "@/components/logos/github"
import Google from "@/components/logos/google"
import Linear from "@/components/logos/linear"
import OpenAI from "@/components/logos/openai"
import Xai from "@/components/logos/xai"

type Integration = {
  name: string
  Logo: ComponentType<SVGProps<SVGSVGElement>>
}

const integrations: Integration[] = [
  {
    name: "GitHub",
    Logo: Github,
  },
  {
    name: "Linear",
    Logo: Linear,
  },
  {
    name: "OpenAI",
    Logo: OpenAI,
  },
  {
    name: "Anthropic",
    Logo: Anthropic,
  },
  {
    name: "Google",
    Logo: Google,
  },
  {
    name: "xAI",
    Logo: Xai,
  },
]

export function IntegrationsStrip() {
  return (
    <section
      aria-label="Integrations"
      className="mx-auto flex w-full max-w-6xl flex-col items-center gap-8 px-6 py-16 md:px-10"
    >
      <p className="max-w-xl text-center text-sm text-muted-foreground">
        Connect your repository. Bring your own model key or use Trace-managed
        access.
      </p>
      <ul className="flex flex-wrap items-center justify-center gap-x-10 gap-y-6 text-foreground/60">
        {integrations.map(({ name, Logo }) => (
          <li
            key={name}
            className="flex items-center gap-2.5"
          >
            <Logo
              aria-hidden="true"
              className="size-5"
            />
            <span className="text-base font-medium">{name}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}
