import { useMutation } from "@tanstack/react-query";

import { Linear } from "@/components/logos/linear";
import { Button } from "@/components/ui/button";
import { toast } from "@/components/ui/toast";
import { ApiError, authApi } from "@/lib/api";

function errorMessage(error: unknown) {
  return error instanceof ApiError
    ? error.message
    : "Unable to start the Linear connection. Please try again.";
}

export function LinearIntegrationCard() {
  const connect = useMutation({
    mutationFn: authApi.beginLinearConnection,
    onSuccess: ({ authorization_url }) => {
      window.location.assign(authorization_url);
    },
    onError: (error) => {
      toast.add({
        type: "error",
        title: "Linear connection could not start",
        description: errorMessage(error),
      });
    },
  });
  const isConnectionStarting = connect.isPending || connect.isSuccess;

  return (
    <article className="rounded-lg border border-border bg-card p-5">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <span
            aria-hidden="true"
            className="flex size-10 items-center justify-center rounded-md bg-foreground text-background"
          >
            <Linear className="size-5" />
          </span>
          <div>
            <h2 className="text-sm font-medium">Linear</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Create tracked Linear issues from remediation findings.
            </p>
          </div>
        </div>
      </div>

      <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4">
        <p className="text-sm text-muted-foreground">
          Connect a Linear account to authorize issue creation.
        </p>
        <Button
          size="sm"
          type="button"
          disabled={isConnectionStarting}
          onClick={() => connect.mutate()}
        >
          {isConnectionStarting ? "Connecting…" : "Connect Linear"}
        </Button>
      </div>
    </article>
  );
}
