import { runtimeConfig } from "@/lib/runtime-config"

export function agentInitials(name: string) {
  return name
    .split(" ")
    .map((part) => part[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase()
}

// Only uploaded avatars resolve to an image. Seeded keys such as
// `agent-defaults/example` are opaque, so they fall back to initials.
export function resolveAgentAvatarUrl(avatar: string | null | undefined) {
  if (!avatar) {
    return undefined
  }

  if (avatar.startsWith("/api/v1/agents/")) {
    return `${runtimeConfig.apiBaseUrl}${avatar}`
  }

  if (/^https?:\/\//i.test(avatar)) {
    return avatar
  }

  return undefined
}
