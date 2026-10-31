import { LandingActions } from "@/components/landing/landing-actions"

export function LandingHero() {
  return (
    <section
      aria-labelledby="landing-hero-title"
      className="mx-auto flex w-full max-w-6xl flex-col items-center px-6 pt-20 pb-16 text-center md:px-10 md:pt-28 md:pb-20 lg:pt-32"
    >
      <div className="flex flex-col items-center gap-8 motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-2 motion-safe:duration-700">
        <p className="rounded-full border border-white/10 bg-popover px-3 py-1 text-xs text-foreground/85">
          Pre-launch review for builders
        </p>
        <h1
          id="landing-hero-title"
          className="max-w-4xl font-display text-[44px] leading-none tracking-tight text-balance sm:text-[56px] md:text-[76px] lg:text-[96px]"
        >
          Review your app before the world does.
        </h1>
        <p className="max-w-2xl text-lg text-pretty text-foreground/70 md:text-xl">
          Specialist AI reviewers read your code for security, engineering,
          product, legal and accessibility risks, then propose fixes you approve
          before anything changes.
        </p>
        <div className="flex flex-col items-center gap-3 self-stretch sm:self-auto">
          <LandingActions />
          <p className="text-sm text-muted-foreground">
            Requires macOS 10.15 or later. Or start in your browser.
          </p>
        </div>
      </div>
    </section>
  )
}
