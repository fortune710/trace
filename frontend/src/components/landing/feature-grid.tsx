import { cn } from "cn"

import {
  features,
  reviewCategories,
} from "@/components/landing/landing-content"
import { SectionHeading } from "@/components/landing/section-heading"

export function FeatureGrid() {
  return (
    <section
      id="features"
      aria-labelledby="features-title"
      className="mx-auto flex w-full max-w-6xl scroll-mt-16 flex-col gap-14 px-6 py-24 md:px-10"
    >
      <SectionHeading
        id="features-title"
        eyebrow="Features"
        title="A review team that reports to you"
        description="Trace finds the risks, explains them in plain language and leaves every decision with you."
      />
      <ul className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {features.map((feature) => (
          <li
            key={feature.title}
            className={cn(
              "flex flex-col gap-3 rounded-xl border border-border bg-card p-8",
              feature.wide && "lg:col-span-2",
            )}
          >
            <h3 className="text-xl font-medium tracking-tight">
              {feature.title}
            </h3>
            <p className="text-base text-pretty text-foreground/70">
              {feature.description}
            </p>
            {feature.wide ? (
              <ul
                aria-label="Review categories"
                className="mt-auto flex flex-wrap gap-2 pt-4"
              >
                {reviewCategories.map((category) => (
                  <li
                    key={category}
                    className="rounded-full border border-white/10 bg-popover px-3 py-1 text-xs text-foreground/85"
                  >
                    {category}
                  </li>
                ))}
              </ul>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  )
}
