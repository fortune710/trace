import { Tick02Icon } from "@hugeicons/core-free-icons"
import { HugeiconsIcon } from "@hugeicons/react"
import { Link } from "react-router-dom"

import { resolveDesktopDownloadUrl } from "@/components/landing/desktop-download"
import { platforms } from "@/components/landing/landing-content"
import { SectionHeading } from "@/components/landing/section-heading"
import LogoApple from "@/components/logos/apple"
import { buttonVariants } from "@/components/ui/button"

export function PlatformsSection() {
  return (
    <section
      id="platforms"
      aria-labelledby="platforms-title"
      className="mx-auto flex w-full max-w-6xl scroll-mt-16 flex-col gap-14 px-6 py-24 md:px-10"
    >
      <SectionHeading
        id="platforms-title"
        eyebrow="Platforms"
        title="Review where your code lives"
        description="Use the browser for GitHub projects or the macOS app for folders on your machine. Same reviewers, same findings."
      />
      <div className="grid gap-4 md:grid-cols-2">
        {platforms.map((platform) => (
          <div
            key={platform.name}
            className="flex flex-col gap-6 rounded-xl border border-border bg-card p-8"
          >
            <div className="flex flex-col gap-2">
              <h3 className="text-2xl font-medium tracking-tight">
                {platform.name}
              </h3>
              <p className="text-base text-foreground/70">
                {platform.description}
              </p>
            </div>
            <ul className="flex flex-col gap-3">
              {platform.points.map((point) => (
                <li
                  key={point}
                  className="flex items-start gap-2.5 text-sm text-foreground/85"
                >
                  <HugeiconsIcon
                    icon={Tick02Icon}
                    size={16}
                    strokeWidth={2}
                    className="mt-0.5 shrink-0 text-muted-foreground"
                  />
                  {point}
                </li>
              ))}
            </ul>
            {platform.name === "Web" ? (
              <Link
                to="/sign-in"
                className={buttonVariants({
                  variant: "secondary",
                  size: "lg",
                  className: "mt-auto h-11 w-fit border-border px-5 sm:h-10",
                })}
              >
                Continue on web
              </Link>
            ) : (
              <a
                href={resolveDesktopDownloadUrl()}
                className={buttonVariants({
                  variant: "secondary",
                  size: "lg",
                  className: "mt-auto h-11 w-fit border-border px-5 sm:h-10",
                })}
              >
                <LogoApple
                  aria-hidden="true"
                  className="size-4"
                  data-icon="inline-start"
                />
                Download for macOS
              </a>
            )}
          </div>
        ))}
      </div>
    </section>
  )
}
