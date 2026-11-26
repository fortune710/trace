import { Component, type ErrorInfo, type ReactNode } from "react"

import { captureAnalyticsException, logAnalytics } from "@/lib/analytics"
import { Button } from "@/components/ui/button"

type Props = {
  children: ReactNode
}

type State = {
  hasError: boolean
}

export class AnalyticsErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false }

  static getDerivedStateFromError(): State {
    return { hasError: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    captureAnalyticsException(error, {
      component_stack: info.componentStack?.slice(0, 2000),
      source: "react_error_boundary",
    })
    logAnalytics("error", "react_error_boundary", {
      message: error.message.slice(0, 200),
      source: "react_error_boundary",
    })
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="mx-auto flex min-h-svh w-full max-w-lg flex-col items-start justify-center gap-4 px-6 py-10">
          <h1 className="text-2xl font-medium tracking-tight">
            Something went wrong
          </h1>
          <p className="text-sm text-muted-foreground">
            Trace hit an unexpected error. Reload the page to continue.
          </p>
          <Button
            type="button"
            onClick={() => {
              this.setState({ hasError: false })
              window.location.assign("/")
            }}
          >
            Reload
          </Button>
        </div>
      )
    }

    return this.props.children
  }
}
