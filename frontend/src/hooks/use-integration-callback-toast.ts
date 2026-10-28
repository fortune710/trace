import { useEffect, useRef } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"

import { toast } from "@/components/ui/toast"

const integrationMessages = {
  github: {
    success: {
      title: "GitHub connected",
      description: "Your repositories are ready to import.",
    },
    failure: {
      title: "GitHub connection failed",
    },
  },
  linear: {
    success: {
      title: "Linear connected",
      description: "You can now create Linear issues from findings.",
    },
    failure: {
      title: "Linear connection failed",
    },
  },
} as const

type IntegrationName = keyof typeof integrationMessages

const integrationNames = Object.keys(integrationMessages) as IntegrationName[]

export function useIntegrationCallbackToast() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const handledOutcome = useRef<string | null>(null)
  const integration = integrationNames.find((name) => {
    const outcome = searchParams.get(name)
    return outcome === "connected" || outcome === "failed"
  })
  const outcome = integration ? searchParams.get(integration) : null
  const requestId = searchParams.get("request_id")

  useEffect(() => {
    if (!integration || (outcome !== "connected" && outcome !== "failed")) {
      return
    }

    const outcomeKey = `${integration}:${outcome}`
    if (handledOutcome.current === outcomeKey) {
      return
    }
    handledOutcome.current = outcomeKey

    const messages = integrationMessages[integration]
    toast.add(
      outcome === "connected"
        ? {
            type: "success",
            ...messages.success,
          }
        : {
            type: "error",
            title: messages.failure.title,
            description: requestId
              ? `Please try again. Request ID: ${requestId}`
              : "Please try again.",
          },
    )
    void navigate("/settings/integrations", { replace: true })
  }, [integration, navigate, outcome, requestId])
}
