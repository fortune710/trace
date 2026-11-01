import { cn } from "cn"

import {
  AgentConfigMockup,
  EvidenceMockup,
  HandoffMockup,
  ReviewAnglesMockup,
} from "@/components/landing/feature-mockups"
import {
  bentoFeatures,
  type BentoFeature,
} from "@/components/landing/landing-content"
import { SectionHeading } from "@/components/landing/section-heading"

const mockups: Record<BentoFeature["id"], () => React.JSX.Element> = {
  "review-angles": ReviewAnglesMockup,
  evidence: EvidenceMockup,
  reviewers: AgentConfigMockup,
  handoff: HandoffMockup,
}

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
      <ul className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-6">
        {bentoFeatures.map((feature) => {
          const Mockup = mockups[feature.id]

          return (
            <li
              key={feature.id}
              className={cn(
                "flex min-w-0 flex-col gap-6 rounded-xl border border-border bg-card p-6 md:p-8",
                feature.className,
              )}
            >
              <div className="flex flex-col gap-3">
                <h3 className="text-xl font-medium tracking-tight">
                  {feature.title}
                </h3>
                <p className="text-base text-pretty text-foreground/70">
                  {feature.description}
                </p>
              </div>
              <div className="mt-auto">
                <Mockup />
              </div>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
