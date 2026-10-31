import { Link } from "react-router-dom"

import { resolveDesktopDownloadUrl } from "@/components/landing/desktop-download"
import { REPOSITORY_URL } from "@/components/landing/landing-content"
import { TraceWordmark } from "@/components/landing/landing-nav"

const linkClassName =
  "rounded-md text-sm text-foreground/70 transition-colors hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"

export function LandingFooter() {
  return (
    <footer className="border-t border-white/6">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-10 px-6 py-16 md:px-10">
        <div className="flex flex-col justify-between gap-8 md:flex-row">
          <Link
            to="/"
            aria-label="Trace home"
          >
            <TraceWordmark />
          </Link>
          <nav
            aria-label="Footer"
            className="flex flex-wrap gap-x-8 gap-y-3"
          >
            <Link
              to="/sign-in"
              className={linkClassName}
            >
              Sign in
            </Link>
            <Link
              to="/sign-up"
              className={linkClassName}
            >
              Sign up
            </Link>
            <a
              href={resolveDesktopDownloadUrl()}
              className={linkClassName}
            >
              Download for macOS
            </a>
            <a
              href={REPOSITORY_URL}
              className={linkClassName}
            >
              GitHub
            </a>
          </nav>
        </div>
        <p className="border-t border-white/4 pt-6 text-xs text-muted-foreground">
          © {new Date().getFullYear()} Trace. Legal findings are informational
          guidance, not legal advice.
        </p>
      </div>
    </footer>
  )
}
