import { LandingActions } from "@/components/landing/landing-actions"

export function LandingCta() {
  return (
    <section
      aria-labelledby="landing-cta-title"
      className="relative overflow-hidden py-32"
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 top-0 h-[560px] bg-[radial-gradient(ellipse_at_top,rgba(255,89,0,0.2),transparent_65%)]"
      />
      <div className="relative mx-auto flex w-full max-w-6xl flex-col items-center gap-10 px-6 text-center md:px-10">
        <h2
          id="landing-cta-title"
          className="max-w-3xl font-display text-[40px] leading-none tracking-tight text-balance sm:text-5xl md:text-6xl lg:text-7xl"
        >
          Find what is wrong before your users do.
        </h2>
        <LandingActions />
      </div>
    </section>
  )
}
