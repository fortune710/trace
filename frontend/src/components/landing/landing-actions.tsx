import { cn } from "cn"
import { Link } from "react-router-dom"

import { resolveDesktopDownloadUrl } from "@/components/landing/desktop-download"
import LogoApple from "@/components/logos/apple"
import { buttonVariants } from "@/components/ui/button"

type LandingActionsProps = {
  className?: string
  downloadVariant?: "default" | "secondary"
}

export function LandingActions({
  className,
  downloadVariant = "default",
}: LandingActionsProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center gap-3 sm:flex-row",
        className,
      )}
    >
      <a
        href={resolveDesktopDownloadUrl()}
        className={cn(
          buttonVariants({
            variant: downloadVariant,
            size: "lg",
          }),
          "h-11 w-full px-5 sm:h-10 sm:w-auto",
          downloadVariant === "secondary" && "border-border",
        )}
      >
        <LogoApple
          aria-hidden="true"
          className="size-4"
          data-icon="inline-start"
        />
        Download for macOS
      </a>
      <Link
        to="/sign-in"
        className={cn(
          buttonVariants({
            variant: "secondary",
            size: "lg",
          }),
          "h-11 w-full border-border px-5 sm:h-10 sm:w-auto",
        )}
      >
        Continue on web
      </Link>
    </div>
  )
}
