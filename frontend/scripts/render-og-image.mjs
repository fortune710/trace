// Renders public/og-image.png, the 1200x630 social preview used by index.html.
// Run with `bun run og:image` after changing the copy or styling below.

import { readFile, writeFile } from "node:fs/promises"
import { fileURLToPath } from "node:url"

import { chromium } from "@playwright/test"

const WIDTH = 1200
const HEIGHT = 630

const root = new URL("../", import.meta.url)

async function dataUri(relativePath, mimeType) {
  const file = await readFile(new URL(relativePath, root))

  return `data:${mimeType};base64,${file.toString("base64")}`
}

const [serif, mono, sans, logo] = await Promise.all([
  dataUri(
    "node_modules/@fontsource/instrument-serif/files/instrument-serif-latin-400-normal.woff2",
    "font/woff2",
  ),
  dataUri(
    "node_modules/@fontsource-variable/geist-mono/files/geist-mono-latin-wght-normal.woff2",
    "font/woff2",
  ),
  dataUri(
    "node_modules/@fontsource-variable/figtree/files/figtree-latin-wght-normal.woff2",
    "font/woff2",
  ),
  dataUri("src/assets/trace-logo.png", "image/png"),
])

const html = `<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <style>
      @font-face {
        font-family: "Instrument Serif";
        src: url(${serif}) format("woff2");
      }
      @font-face {
        font-family: "Geist Mono";
        src: url(${mono}) format("woff2");
        font-weight: 100 900;
      }
      @font-face {
        font-family: "Figtree";
        src: url(${sans}) format("woff2");
        font-weight: 300 900;
      }

      * {
        box-sizing: border-box;
        margin: 0;
      }

      body {
        position: relative;
        width: ${WIDTH}px;
        height: ${HEIGHT}px;
        overflow: hidden;
        background: #000;
        color: #fcfdff;
        font-family: "Figtree", sans-serif;
      }

      .glow {
        position: absolute;
        inset: 0;
        background: radial-gradient(
          ellipse 760px 460px at 82% 0%,
          rgba(0, 117, 255, 0.34),
          transparent 70%
        );
      }

      .frame {
        position: absolute;
        inset: 0;
        border: 1px solid rgba(255, 255, 255, 0.06);
      }

      .copy {
        position: absolute;
        top: 64px;
        left: 72px;
        bottom: 64px;
        width: 560px;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
      }

      .wordmark {
        display: flex;
        align-items: center;
        gap: 12px;
        font-family: "Geist Mono", monospace;
        font-size: 28px;
        letter-spacing: -0.02em;
      }

      .wordmark img {
        width: 36px;
        height: 36px;
        object-fit: contain;
      }

      h1 {
        font-family: "Instrument Serif", serif;
        font-size: 92px;
        font-weight: 400;
        line-height: 1;
        letter-spacing: -0.96px;
      }

      .subtitle {
        margin-top: 28px;
        font-size: 26px;
        line-height: 1.35;
        text-wrap: balance;
        color: rgba(252, 253, 255, 0.7);
      }

      .origin {
        font-family: "Geist Mono", monospace;
        font-size: 20px;
        color: #888e90;
      }

      .stack {
        position: absolute;
        top: 112px;
        left: 668px;
        width: 472px;
        display: flex;
        flex-direction: column;
        gap: 16px;
      }

      .card {
        border: 1px solid rgba(255, 255, 255, 0.14);
        border-radius: 14px;
        background: #0a0a0c;
        padding: 28px;
      }

      .card.faded {
        opacity: 0.55;
      }

      .meta {
        display: flex;
        align-items: center;
        gap: 12px;
      }

      .badge {
        border-radius: 6px;
        padding: 4px 10px;
        font-size: 16px;
        font-weight: 600;
        letter-spacing: 0.04em;
        text-transform: uppercase;
      }

      .badge.critical {
        background: rgba(239, 68, 68, 0.15);
        color: #fca5a5;
      }

      .badge.high {
        background: rgba(249, 115, 22, 0.15);
        color: #fdba74;
      }

      .category {
        font-size: 16px;
        font-weight: 500;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        color: #a1a4a5;
      }

      .title {
        margin-top: 16px;
        font-size: 26px;
        font-weight: 500;
        line-height: 1.2;
        letter-spacing: -0.4px;
      }

      .explanation {
        margin-top: 12px;
        font-size: 18px;
        line-height: 1.45;
        color: #a1a4a5;
      }

      .footer {
        margin-top: 24px;
        display: flex;
        align-items: center;
        justify-content: space-between;
      }

      .reviewer {
        display: flex;
        align-items: center;
        gap: 10px;
        font-size: 18px;
        color: rgba(252, 253, 255, 0.86);
      }

      .avatar {
        width: 30px;
        height: 30px;
        border-radius: 50%;
        background: #101012;
        border: 1px solid rgba(255, 255, 255, 0.14);
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 14px;
        font-weight: 600;
      }

      .source {
        border: 1px solid rgba(255, 255, 255, 0.14);
        border-radius: 6px;
        padding: 3px 9px;
        font-family: "Geist Mono", monospace;
        font-size: 15px;
        color: rgba(252, 253, 255, 0.7);
      }

      .actions {
        margin-top: 24px;
        display: flex;
        gap: 12px;
      }

      .button {
        border-radius: 8px;
        padding: 10px 20px;
        font-size: 18px;
        font-weight: 500;
      }

      .button.primary {
        background: #fcfdff;
        color: #000;
      }

      .button.ghost {
        border: 1px solid rgba(255, 255, 255, 0.14);
        color: rgba(252, 253, 255, 0.86);
      }

      .fade {
        position: absolute;
        inset: auto 0 0 0;
        height: 200px;
        background: linear-gradient(to top, #000, transparent);
      }
    </style>
  </head>
  <body>
    <div class="glow"></div>
    <div class="copy">
      <div class="wordmark">
        <img src="${logo}" alt="" />
        <span>trace</span>
      </div>
      <div>
        <h1>Review your app before the world does.</h1>
        <p class="subtitle">
          Specialist AI reviewers flag what could cost you and your users,
          before launch.
        </p>
      </div>
      <p class="origin">trace.fortunealebiosu.dev</p>
    </div>
    <div class="stack">
      <div class="card">
        <div class="meta">
          <span class="badge critical">critical</span>
          <span class="category">security</span>
        </div>
        <p class="title">Live payment key committed in .env.example</p>
        <p class="explanation">
          A live payment key sits in a file that ships with the repository, so
          anyone who can read the code can use it.
        </p>
        <div class="footer">
          <span class="reviewer">
            <span class="avatar">S</span>
            Sentinel
          </span>
          <span class="source">.env.example</span>
        </div>
        <div class="actions">
          <span class="button primary">Accept</span>
          <span class="button ghost">Dismiss</span>
        </div>
      </div>
      <div class="card faded">
        <div class="meta">
          <span class="badge high">high</span>
          <span class="category">engineering</span>
        </div>
        <p class="title">Webhook handler has no error handling or retry path</p>
      </div>
    </div>
    <div class="fade"></div>
    <div class="frame"></div>
  </body>
</html>`

const browser = await chromium.launch()

try {
  const page = await browser.newPage({
    viewport: { width: WIDTH, height: HEIGHT },
  })

  await page.setContent(html)
  await page.evaluate(() => document.fonts.ready)

  const image = await page.screenshot({ type: "png" })
  const output = fileURLToPath(new URL("public/og-image.png", root))

  await writeFile(output, image)
  console.log(`Wrote public/og-image.png (${image.length} bytes)`)
} finally {
  await browser.close()
}
