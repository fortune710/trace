import { useEffect, useState, type RefObject } from "react"

import { Menu01Icon } from "@hugeicons/core-free-icons"
import { HugeiconsIcon } from "@hugeicons/react"
import { cn } from "cn"
import { Link } from "react-router-dom"

import traceLogo from "@/assets/trace-logo.png"
import { navLinks } from "@/components/landing/landing-content"
import { Button, buttonVariants } from "@/components/ui/button"
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet"
import { useSession } from "@/hooks/use-session"

export function TraceWordmark() {
  return (
    <span className="flex items-center gap-2">
      <img
        src={traceLogo}
        alt=""
        width={24}
        height={24}
        className="size-6 rounded-md"
      />
      <span className="font-mono text-sm tracking-tight">trace</span>
    </span>
  )
}

type LandingNavProps = {
  pinWithinRefs: Array<RefObject<HTMLElement | null>>
}

function usePinnedWithin(regionRefs: Array<RefObject<HTMLElement | null>>) {
  const [pinned, setPinned] = useState(false)

  useEffect(() => {
    const regions = regionRefs
      .map((regionRef) => regionRef.current)
      .filter((region): region is HTMLElement => region !== null)

    if (regions.length === 0 || typeof IntersectionObserver === "undefined") {
      return
    }

    // The regions together run from the product screenshot to the end of the
    // page. The zero-height root sits on the top edge of the viewport, so a
    // region intersects exactly while the viewport top is inside it. Observing
    // the whole remainder (not just the screenshot) keeps the state correct
    // when the user jumps past it, for example through an anchor link or the
    // End key.
    const active = new Set<Element>()
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            active.add(entry.target)
          } else {
            active.delete(entry.target)
          }
        }

        setPinned(active.size > 0)
      },
      { rootMargin: "0px 0px -100% 0px" },
    )

    for (const region of regions) {
      observer.observe(region)
    }

    return () => observer.disconnect()
  }, [regionRefs])

  return pinned
}

export function LandingNav({ pinWithinRefs }: LandingNavProps) {
  const session = useSession()
  const pinned = usePinnedWithin(pinWithinRefs)
  const [menuOpen, setMenuOpen] = useState(false)
  const hasSession = Boolean(session.data)
  const accountHref = hasSession ? "/account" : "/sign-in"
  const accountLabel = hasSession ? "Open app" : "Sign in"

  return (
    <div className="h-16">
      <header
        data-pinned={pinned}
        className={cn(
          "z-40 w-full border-b",
          pinned
            ? "fixed inset-x-0 top-0 border-white/6 bg-background/80 backdrop-blur-md motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-top-2 motion-safe:duration-300"
            : "relative border-transparent",
        )}
      >
        <div className="mx-auto flex h-16 w-full max-w-6xl items-center justify-between px-6 md:px-10">
          <div className="flex items-center gap-10">
            <Link
              to="/"
              aria-label="Trace home"
            >
              <TraceWordmark />
            </Link>
            <nav
              aria-label="Primary"
              className="hidden items-center gap-1 lg:flex"
            >
              {navLinks.map((link) => (
                <a
                  key={link.href}
                  href={link.href}
                  className="rounded-md px-3 py-2 text-sm text-foreground/70 transition-colors hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
                >
                  {link.label}
                </a>
              ))}
            </nav>
          </div>
          <div className="flex items-center gap-2">
            <Link
              to={accountHref}
              className={buttonVariants({
                variant: "secondary",
                size: "default",
                className: "border-border",
              })}
            >
              {accountLabel}
            </Link>
            <Sheet
              open={menuOpen}
              onOpenChange={setMenuOpen}
            >
              <SheetTrigger
                render={
                  <Button
                    variant="ghost"
                    size="icon"
                    className="lg:hidden"
                    aria-label="Open menu"
                  />
                }
              >
                <HugeiconsIcon
                  icon={Menu01Icon}
                  size={20}
                  strokeWidth={2}
                />
              </SheetTrigger>
              <SheetContent side="right">
                <SheetHeader>
                  <SheetTitle>
                    <TraceWordmark />
                  </SheetTitle>
                </SheetHeader>
                <nav
                  aria-label="Mobile"
                  className="flex flex-col gap-1 px-4"
                >
                  {navLinks.map((link) => (
                    <a
                      key={link.href}
                      href={link.href}
                      onClick={() => setMenuOpen(false)}
                      className="rounded-md px-3 py-3 text-base text-foreground/85 hover:bg-muted"
                    >
                      {link.label}
                    </a>
                  ))}
                </nav>
              </SheetContent>
            </Sheet>
          </div>
        </div>
      </header>
    </div>
  )
}
