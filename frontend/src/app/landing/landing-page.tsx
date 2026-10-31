import "@fontsource/instrument-serif/400.css"
import "@fontsource-variable/geist-mono"

import { useRef, useState } from "react"

import { ApprovalSection } from "@/components/landing/approval-section"
import { FeatureGrid } from "@/components/landing/feature-grid"
import { HowItWorks } from "@/components/landing/how-it-works"
import { IntegrationsStrip } from "@/components/landing/integrations-strip"
import { LandingCta } from "@/components/landing/landing-cta"
import { LandingFaq } from "@/components/landing/landing-faq"
import { LandingFooter } from "@/components/landing/landing-footer"
import { LandingHero } from "@/components/landing/landing-hero"
import { LandingNav } from "@/components/landing/landing-nav"
import { PlatformsSection } from "@/components/landing/platforms-section"
import { ReviewMockup } from "@/components/landing/review-mockup"

export function LandingPage() {
  const pinRegionRef = useRef<HTMLDivElement>(null)
  const footerRegionRef = useRef<HTMLDivElement>(null)
  const [pinRegions] = useState(() => [pinRegionRef, footerRegionRef])

  return (
    <div className="min-h-svh overflow-x-clip bg-background text-foreground">
      <LandingNav pinWithinRefs={pinRegions} />
      <main>
        <LandingHero />
        {/* Starts one nav height above the screenshot so the nav pins just as the screenshot would reach it. */}
        <div
          ref={pinRegionRef}
          className="-mt-16 pt-16"
        >
          <div className="relative pb-8">
            <div
              aria-hidden="true"
              className="pointer-events-none absolute inset-x-0 top-0 h-[640px] bg-[radial-gradient(ellipse_at_top,rgba(0,117,255,0.26),transparent_65%)]"
            />
            <div className="relative">
              <ReviewMockup />
            </div>
          </div>
          <IntegrationsStrip />
          <FeatureGrid />
          <ApprovalSection />
          <HowItWorks />
          <PlatformsSection />
          <LandingFaq />
          <LandingCta />
        </div>
      </main>
      <div ref={footerRegionRef}>
        <LandingFooter />
      </div>
    </div>
  )
}

export default LandingPage
