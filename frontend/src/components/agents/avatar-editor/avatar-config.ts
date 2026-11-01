import type { AvatarConfig } from "@/lib/api"

export type { AvatarConfig }

export type VariantCategoryKey =
  | "eyes"
  | "brows"
  | "nose"
  | "lips"
  | "hair"
  | "glasses"
  | "beard"
  | "body"

export type AvatarCategoryKey = VariantCategoryKey | "backgroundColor"

export type AvatarCategory = {
  key: AvatarCategoryKey
  label: string
  // Optional categories can be switched off, which omits the key entirely.
  optional: boolean
  // Face parts are previewed zoomed in so the difference between variants is visible.
  focus: "face" | "full"
}

export const AVATAR_CATEGORIES: AvatarCategory[] = [
  { key: "eyes", label: "Eyes", optional: false, focus: "face" },
  { key: "brows", label: "Brows", optional: false, focus: "face" },
  { key: "nose", label: "Nose", optional: false, focus: "face" },
  { key: "lips", label: "Mouth", optional: false, focus: "face" },
  { key: "hair", label: "Hair", optional: false, focus: "full" },
  { key: "glasses", label: "Glasses", optional: true, focus: "face" },
  { key: "beard", label: "Beard", optional: true, focus: "face" },
  { key: "body", label: "Outfit", optional: false, focus: "full" },
  { key: "backgroundColor", label: "Background", optional: false, focus: "full" },
]

function variantIds(count: number) {
  return Array.from(
    { length: count },
    (_, index) => `variant${String(index + 1).padStart(2, "0")}`,
  )
}

// Counts come from the Notionists schema. Hair also has a "hat" id and the style
// has gesture ids, but neither matches the server's `variantNN` allowlist, so
// they are intentionally not offered.
export const AVATAR_VARIANTS: Record<VariantCategoryKey, string[]> = {
  eyes: variantIds(5),
  brows: variantIds(13),
  nose: variantIds(20),
  lips: variantIds(30),
  hair: variantIds(63),
  glasses: variantIds(11),
  beard: variantIds(12),
  body: variantIds(25),
}

export const BACKGROUND_SWATCHES = [
  "#ffd6de",
  "#ffdcbf",
  "#fff1b3",
  "#d4f1c9",
  "#bff0e6",
  "#bfe0ff",
  "#d3d0ff",
  "#ecd2ff",
  "#e6e6ea",
  "#8d8d98",
  "#2b2b31",
  "#0f3d2c",
]

export const DEFAULT_AVATAR_CONFIG: AvatarConfig = {
  eyes: "variant01",
  brows: "variant01",
  nose: "variant01",
  lips: "variant01",
  hair: "variant01",
  body: "variant01",
  backgroundColor: "#d3d0ff",
  flip: false,
}

const VARIANT_PATTERN = /^variant\d{2}$/
const HEX_PATTERN = /^#[0-9a-f]{6}$/

function isOption(key: VariantCategoryKey, value: unknown): value is string {
  return (
    typeof value === "string" &&
    VARIANT_PATTERN.test(value) &&
    AVATAR_VARIANTS[key].includes(value)
  )
}

export function isAvatarConfig(value: unknown): value is AvatarConfig {
  if (typeof value !== "object" || value === null) {
    return false
  }

  const candidate = value as Record<string, unknown>
  const required: VariantCategoryKey[] = [
    "eyes",
    "brows",
    "nose",
    "lips",
    "hair",
    "body",
  ]

  return (
    required.every((key) => isOption(key, candidate[key])) &&
    (candidate.glasses === undefined || isOption("glasses", candidate.glasses)) &&
    (candidate.beard === undefined || isOption("beard", candidate.beard)) &&
    typeof candidate.backgroundColor === "string" &&
    HEX_PATTERN.test(candidate.backgroundColor) &&
    typeof candidate.flip === "boolean"
  )
}

// Saved configs come from the server. Anything unknown falls back to the default
// for that key, so an older or hand-edited value can never break the editor.
export function normalizeAvatarConfig(value: unknown): AvatarConfig {
  if (typeof value !== "object" || value === null) {
    return { ...DEFAULT_AVATAR_CONFIG }
  }

  const candidate = value as Record<string, unknown>
  const config: AvatarConfig = { ...DEFAULT_AVATAR_CONFIG }
  const required: VariantCategoryKey[] = [
    "eyes",
    "brows",
    "nose",
    "lips",
    "hair",
    "body",
  ]

  for (const key of required) {
    const option = candidate[key]
    if (isOption(key, option)) {
      config[key] = option
    }
  }

  if (isOption("glasses", candidate.glasses)) {
    config.glasses = candidate.glasses
  }

  if (isOption("beard", candidate.beard)) {
    config.beard = candidate.beard
  }

  if (
    typeof candidate.backgroundColor === "string" &&
    HEX_PATTERN.test(candidate.backgroundColor)
  ) {
    config.backgroundColor = candidate.backgroundColor
  }

  if (typeof candidate.flip === "boolean") {
    config.flip = candidate.flip
  }

  return config
}

function pick<T>(values: T[], random: () => number) {
  return values[Math.min(values.length - 1, Math.floor(random() * values.length))]
}

export function randomAvatarConfig(random: () => number = Math.random): AvatarConfig {
  const config: AvatarConfig = {
    eyes: pick(AVATAR_VARIANTS.eyes, random),
    brows: pick(AVATAR_VARIANTS.brows, random),
    nose: pick(AVATAR_VARIANTS.nose, random),
    lips: pick(AVATAR_VARIANTS.lips, random),
    hair: pick(AVATAR_VARIANTS.hair, random),
    body: pick(AVATAR_VARIANTS.body, random),
    backgroundColor: pick(BACKGROUND_SWATCHES, random),
    flip: random() < 0.5,
  }

  if (random() < 0.3) {
    config.glasses = pick(AVATAR_VARIANTS.glasses, random)
  }

  if (random() < 0.2) {
    config.beard = pick(AVATAR_VARIANTS.beard, random)
  }

  return config
}

export function getCategoryValue(
  config: AvatarConfig,
  key: AvatarCategoryKey,
): string | undefined {
  return config[key]
}

export function setCategoryValue(
  config: AvatarConfig,
  key: AvatarCategoryKey,
  value: string | undefined,
): AvatarConfig {
  const next = { ...config }

  if (value === undefined) {
    if (key === "glasses" || key === "beard") {
      delete next[key]
    }
    return next
  }

  next[key] = value
  return next
}

export type AvatarEngine = {
  createAvatar: typeof import("@dicebear/core").createAvatar
  notionists: typeof import("@dicebear/notionists")
}

let enginePromise: Promise<AvatarEngine> | null = null

// DiceBear and the Notionists art are large, so they load on first use and stay
// out of the main bundle.
export function loadAvatarEngine(): Promise<AvatarEngine> {
  if (!enginePromise) {
    enginePromise = Promise.all([
      import("@dicebear/core"),
      import("@dicebear/notionists"),
    ])
      .then(([core, notionists]) => ({
        createAvatar: core.createAvatar,
        notionists,
      }))
      .catch((error: unknown) => {
        enginePromise = null
        throw error
      })
  }

  return enginePromise
}

// Centered on the avatar's vertical axis (x = 872) so a flipped avatar crops the same way.
const FACE_VIEW_BOX = "562 520 620 620"

export function buildAvatarSvg(
  engine: AvatarEngine,
  config: AvatarConfig,
  options: { size?: number; focus?: AvatarCategory["focus"] } = {},
): string {
  const styleOptions = {
    seed: "trace-agent",
    size: options.size ?? 256,
    eyes: [config.eyes],
    brows: [config.brows],
    nose: [config.nose],
    lips: [config.lips],
    hair: [config.hair],
    body: [config.body],
    glasses: config.glasses ? [config.glasses] : undefined,
    glassesProbability: config.glasses ? 100 : 0,
    beard: config.beard ? [config.beard] : undefined,
    beardProbability: config.beard ? 100 : 0,
    gestureProbability: 0,
    bodyIconProbability: 0,
    backgroundColor: [config.backgroundColor.replace("#", "")],
    flip: config.flip,
  }
  const svg = engine
    .createAvatar(
      engine.notionists,
      styleOptions as Parameters<typeof engine.createAvatar>[1],
    )
    .toString()

  if (options.focus === "face") {
    return svg.replace(/viewBox="[^"]*"/, `viewBox="${FACE_VIEW_BOX}"`)
  }

  return svg
}

export function svgToDataUri(svg: string): string {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
}
