import { faqs } from "@/components/landing/landing-content"
import { SectionHeading } from "@/components/landing/section-heading"

export function LandingFaq() {
  return (
    <section
      id="faq"
      aria-labelledby="faq-title"
      className="mx-auto flex w-full max-w-3xl scroll-mt-16 flex-col gap-14 px-6 py-24 md:px-10"
    >
      <SectionHeading
        id="faq-title"
        eyebrow="FAQ"
        title="Questions, answered"
      />
      <div className="flex flex-col divide-y divide-white/6 rounded-xl border border-border bg-card">
        {faqs.map((item) => (
          <details
            key={item.question}
            className="group px-6 py-5"
          >
            <summary className="flex cursor-pointer list-none items-center justify-between gap-4 text-base font-medium marker:hidden focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 [&::-webkit-details-marker]:hidden">
              {item.question}
              <span
                aria-hidden="true"
                className="font-code text-lg text-muted-foreground transition-transform group-open:rotate-45"
              >
                +
              </span>
            </summary>
            <p className="pt-3 text-base text-pretty text-foreground/70">
              {item.answer}
            </p>
          </details>
        ))}
      </div>
    </section>
  )
}
