import { BotIcon } from "@hugeicons/core-free-icons"
import { HugeiconsIcon } from "@hugeicons/react"

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar"
import type { Agent } from "@/lib/api"
import {
  agentInitials,
  resolveAgentAvatarUrl,
} from "@/components/agents/agent-avatar-utils"

type AgentAvatarProps = {
  agent: Pick<Agent, "name" | "avatar">
  size?: "default" | "sm" | "lg"
  className?: string
}

export function AgentAvatar({
  agent,
  size = "default",
  className,
}: AgentAvatarProps) {
  const initials = agentInitials(agent.name)

  return (
    <Avatar
      size={size}
      className={className}
    >
      <AvatarImage
        src={resolveAgentAvatarUrl(agent.avatar)}
        alt=""
      />
      <AvatarFallback>
        {initials || (
          <HugeiconsIcon
            icon={BotIcon}
            size={18}
          />
        )}
      </AvatarFallback>
    </Avatar>
  )
}
