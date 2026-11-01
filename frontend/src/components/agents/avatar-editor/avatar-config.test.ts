// @vitest-environment jsdom

import { schema } from "@dicebear/notionists"
import { describe, expect, it } from "vitest"

import {
  AVATAR_CATEGORIES,
  AVATAR_VARIANTS,
  BACKGROUND_SWATCHES,
  DEFAULT_AVATAR_CONFIG,
  buildAvatarSvg,
  isAvatarConfig,
  loadAvatarEngine,
  normalizeAvatarConfig,
  randomAvatarConfig,
  setCategoryValue,
  type VariantCategoryKey,
} from "@/components/agents/avatar-editor/avatar-config"

type SchemaProperty = { items: { enum: string[] } }

function schemaVariants(key: VariantCategoryKey) {
  const property = (schema.properties as unknown as Record<string, SchemaProperty>)[key]
  return property.items.enum
}

function sequence(values: number[]) {
  let index = 0
  return () => values[index++ % values.length]
}

describe("avatar options", () => {
  it("only offers variant ids that exist in the Notionists schema", () => {
    for (const key of Object.keys(AVATAR_VARIANTS) as VariantCategoryKey[]) {
      const known = new Set(schemaVariants(key))

      for (const variant of AVATAR_VARIANTS[key]) {
        expect(known.has(variant), `${key} ${variant}`).toBe(true)
        expect(variant).toMatch(/^variant\d{2}$/)
      }
    }
  })

  it("covers every numbered variant the schema defines", () => {
    for (const key of Object.keys(AVATAR_VARIANTS) as VariantCategoryKey[]) {
      const numbered = schemaVariants(key).filter((variant) =>
        /^variant\d{2}$/.test(variant),
      )
      expect([...AVATAR_VARIANTS[key]].sort()).toEqual([...numbered].sort())
    }
  })

  it("only offers lowercase #rrggbb backgrounds", () => {
    for (const color of BACKGROUND_SWATCHES) {
      expect(color).toMatch(/^#[0-9a-f]{6}$/)
    }
  })

  it("has a valid default config", () => {
    expect(isAvatarConfig(DEFAULT_AVATAR_CONFIG)).toBe(true)
  })
})

describe("randomAvatarConfig", () => {
  it("only produces valid variant ids and colors", () => {
    for (let run = 0; run < 200; run += 1) {
      const config = randomAvatarConfig()

      expect(isAvatarConfig(config)).toBe(true)
      expect(BACKGROUND_SWATCHES).toContain(config.backgroundColor)

      for (const key of Object.keys(AVATAR_VARIANTS) as VariantCategoryKey[]) {
        const value = config[key]
        if (value !== undefined) {
          expect(schemaVariants(key)).toContain(value)
        }
      }
    }
  })

  it("reaches both ends of every list and is deterministic for a given source", () => {
    const low = randomAvatarConfig(() => 0)
    const high = randomAvatarConfig(() => 0.999999)

    expect(low.hair).toBe("variant01")
    expect(high.hair).toBe("variant63")
    expect(low.glasses).toBe("variant01")
    expect(high.glasses).toBeUndefined()
    expect(randomAvatarConfig(sequence([0.2, 0.7, 0.4]))).toEqual(
      randomAvatarConfig(sequence([0.2, 0.7, 0.4])),
    )
  })
})

describe("config helpers", () => {
  it("falls back to defaults for unknown saved values", () => {
    const config = normalizeAvatarConfig({
      eyes: "variant03",
      brows: "variant99",
      hair: "<script>",
      glasses: "nope",
      beard: "variant02",
      backgroundColor: "red",
      flip: "yes",
    })

    expect(config.eyes).toBe("variant03")
    expect(config.brows).toBe(DEFAULT_AVATAR_CONFIG.brows)
    expect(config.hair).toBe(DEFAULT_AVATAR_CONFIG.hair)
    expect(config.glasses).toBeUndefined()
    expect(config.beard).toBe("variant02")
    expect(config.backgroundColor).toBe(DEFAULT_AVATAR_CONFIG.backgroundColor)
    expect(config.flip).toBe(false)
    expect(normalizeAvatarConfig(null)).toEqual(DEFAULT_AVATAR_CONFIG)
  })

  it("removes an optional part instead of storing an empty value", () => {
    const withGlasses = setCategoryValue(
      DEFAULT_AVATAR_CONFIG,
      "glasses",
      "variant04",
    )

    expect(withGlasses.glasses).toBe("variant04")
    expect("glasses" in setCategoryValue(withGlasses, "glasses", undefined)).toBe(
      false,
    )
  })
})

describe("buildAvatarSvg", () => {
  it("renders an svg for every option of every category", async () => {
    const engine = await loadAvatarEngine()

    for (const category of AVATAR_CATEGORIES) {
      if (category.key === "backgroundColor") {
        for (const color of BACKGROUND_SWATCHES) {
          const svg = buildAvatarSvg(
            engine,
            setCategoryValue(DEFAULT_AVATAR_CONFIG, "backgroundColor", color),
          )
          expect(svg.startsWith("<svg")).toBe(true)
          expect(svg.toLowerCase()).toContain(color)
        }
        continue
      }

      for (const variant of AVATAR_VARIANTS[category.key]) {
        const svg = buildAvatarSvg(
          engine,
          setCategoryValue(DEFAULT_AVATAR_CONFIG, category.key, variant),
          { size: 96, focus: category.focus },
        )
        expect(svg.startsWith("<svg"), `${category.key} ${variant}`).toBe(true)
      }
    }
  })

  it("honours the size, focus, glasses and flip options", async () => {
    const engine = await loadAvatarEngine()
    const plain = buildAvatarSvg(engine, DEFAULT_AVATAR_CONFIG, { size: 128 })
    const glasses = buildAvatarSvg(
      engine,
      setCategoryValue(DEFAULT_AVATAR_CONFIG, "glasses", "variant01"),
      { size: 128 },
    )
    const flipped = buildAvatarSvg(
      engine,
      { ...DEFAULT_AVATAR_CONFIG, flip: true },
      { size: 128 },
    )
    const face = buildAvatarSvg(engine, DEFAULT_AVATAR_CONFIG, {
      size: 128,
      focus: "face",
    })

    expect(plain).toContain('width="128"')
    expect(glasses).not.toBe(plain)
    expect(flipped).not.toBe(plain)
    expect(plain).toContain('viewBox="0 0 1744 1744"')
    expect(face).not.toContain('viewBox="0 0 1744 1744"')
    expect(buildAvatarSvg(engine, DEFAULT_AVATAR_CONFIG, { size: 128 })).toBe(plain)
  })
})
