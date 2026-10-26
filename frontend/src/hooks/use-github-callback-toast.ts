import { useEffect, useRef } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"

import { toast } from "@/components/ui/toast"

export function useGitHubCallbackToast() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const handledOutcome = useRef<string | null>(null)
  const outcome = searchParams.get("github")
  const requestId = searchParams.get("request_id")

  useEffect(() => {
    if ((outcome !== "connected" && outcome !== "failed") || handledOutcome.current === outcome) {
      return
    }
    handledOutcome.current = outcome

    toast.add(
      outcome === "connected"
        ? {
            type: "success",
            title: "GitHub connected",
            description: "Your repositories are ready to import.",
          }
        : {
            type: "error",
            title: "GitHub connection failed",
            description: requestId
              ? `Please try again. Request ID: ${requestId}`
              : "Please try again.",
          },
    )
    void navigate("/settings/integrations", { replace: true })
  }, [navigate, outcome, requestId])
}
