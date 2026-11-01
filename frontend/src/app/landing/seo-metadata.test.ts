// @vitest-environment jsdom

import { describe, expect, it } from "vitest"

import indexHtml from "../../../index.html?raw"
import ogImage from "../../../public/og-image.png?inline"
import robots from "../../../public/robots.txt?raw"
import sitemap from "../../../public/sitemap.xml?raw"

const document = new DOMParser().parseFromString(indexHtml, "text/html")

function meta(attribute: "name" | "property", key: string) {
  return document
    .querySelector(`meta[${attribute}="${key}"]`)
    ?.getAttribute("content")
}

const siteUrl = document
  .querySelector('link[rel="canonical"]')
  ?.getAttribute("href")

describe("index.html SEO metadata", () => {
  it("has a title and a description that fits a search snippet", () => {
    const description = meta("name", "description")

    expect(document.title).toBe("Trace — Review your app before the world does")
    expect(description).toBeTruthy()
    expect(description?.length).toBeLessThanOrEqual(160)
  })

  it("uses an absolute https canonical URL for the site root", () => {
    expect(siteUrl).toMatch(/^https:\/\/[^/]+\/$/)
  })

  it("keeps Open Graph and Twitter tags on the canonical origin", () => {
    expect(meta("property", "og:url")).toBe(siteUrl)
    expect(meta("property", "og:type")).toBe("website")
    expect(meta("property", "og:title")).toBe(document.title)
    expect(meta("property", "og:image")).toBe(`${siteUrl}og-image.png`)
    expect(meta("property", "og:image:alt")).toBeTruthy()
    expect(meta("name", "twitter:card")).toBe("summary_large_image")
    expect(meta("name", "twitter:image")).toBe(meta("property", "og:image"))
    expect(meta("name", "twitter:image:alt")).toBeTruthy()
  })

  it("ships a 1200x630 PNG at the advertised image path", () => {
    const bytes = Uint8Array.from(atob(ogImage.split(",")[1]), (character) =>
      character.charCodeAt(0),
    )
    const header = new DataView(bytes.buffer)

    expect(String.fromCharCode(...bytes.subarray(1, 4))).toBe("PNG")
    expect(header.getUint32(16)).toBe(1200)
    expect(header.getUint32(20)).toBe(630)
    expect(meta("property", "og:image:width")).toBe("1200")
    expect(meta("property", "og:image:height")).toBe("630")
  })

  it("describes the product in valid structured data without a price", () => {
    const script = document.querySelector('script[type="application/ld+json"]')
    const data = JSON.parse(script?.textContent ?? "")

    expect(data["@type"]).toBe("SoftwareApplication")
    expect(data.url).toBe(siteUrl)
    expect(data.offers).toBeUndefined()
  })
})

describe("crawler files", () => {
  it("lists only the landing page in the sitemap", () => {
    expect(sitemap.match(/<loc>(.*?)<\/loc>/g)).toEqual([`<loc>${siteUrl}</loc>`])
  })

  it("points robots.txt at the sitemap and hides the signed-in app", () => {
    expect(robots).toContain(`Sitemap: ${siteUrl}sitemap.xml`)

    for (const path of ["/account", "/projects", "/reviews", "/sign-in"]) {
      expect(robots).toContain(`Disallow: ${path}`)
    }
  })
})
