import { steps } from "@/components/landing/landing-content"
import { SectionHeading } from "@/components/landing/section-heading"

export function HowItWorks() {
  return (
    <section
      id="how-it-works"
      aria-labelledby="how-it-works-title"
      className="mx-auto flex w-full max-w-6xl scroll-mt-16 flex-col gap-14 px-6 py-24 md:px-10"
    >
      <SectionHeading
        id="how-it-works-title"
        eyebrow="How it works"
        title="From import to fix in three steps"
      />
      <ol className="grid gap-4 md:grid-cols-3">
        {steps.map((step, index) => (
          <li
            key={step.title}
            className="flex flex-col gap-4 rounded-xl border border-border bg-card p-8"
          >
            <span className="font-code text-sm text-muted-foreground">
              {String(index + 1).padStart(2, "0")}
            </span>
            <h3 className="text-xl font-medium tracking-tight">{step.title}</h3>
            <p className="text-base text-pretty text-foreground/70">
              {step.description}
            </p>
          </li>
        ))}
      </ol>
    </section>
  )
}
