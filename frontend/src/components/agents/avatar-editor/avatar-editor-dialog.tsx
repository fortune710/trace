import { useEffect, useMemo, useState, type KeyboardEvent } from "react"
import { FlipHorizontalIcon, ShuffleIcon } from "@hugeicons/core-free-icons"
import { HugeiconsIcon } from "@hugeicons/react"

import {
  AVATAR_CATEGORIES,
  AVATAR_VARIANTS,
  BACKGROUND_SWATCHES,
  buildAvatarSvg,
  getCategoryValue,
  loadAvatarEngine,
  normalizeAvatarConfig,
  randomAvatarConfig,
  setCategoryValue,
  svgToDataUri,
  type AvatarCategory,
  type AvatarConfig,
  type AvatarEngine,
  type VariantCategoryKey,
} from "@/components/agents/avatar-editor/avatar-config"
import { renderAvatarPng } from "@/components/agents/avatar-editor/render-avatar-png"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Skeleton } from "@/components/ui/skeleton"
import { toast } from "@/components/ui/toast"
import {
  useDeleteAgentAvatar,
  useUploadAgentAvatar,
} from "@/hooks/use-agents"
import type { Agent } from "@/lib/api"
import { cn } from "@/lib/utils"

type AvatarEditorDialogProps = {
  agent: Agent
  open: boolean
  onOpenChange: (open: boolean) => void
}

type TileProps = {
  label: string
  selected: boolean
  onSelect: () => void
  children: React.ReactNode
}

function OptionTile({ label, selected, onSelect, children }: TileProps) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      aria-label={label}
      title={label}
      onClick={onSelect}
      className={cn(
        "relative flex aspect-square items-center justify-center overflow-hidden rounded-lg border bg-white/[0.03] outline-none transition-all",
        "hover:border-white/30 hover:bg-white/[0.06] focus-visible:ring-2 focus-visible:ring-ring",
        selected
          ? "border-[#11ff99] ring-2 ring-[#11ff99]/25"
          : "border-white/12",
      )}
    >
      {children}
    </button>
  )
}

function variantLabel(category: AvatarCategory, variant: string) {
  return `${category.label} ${Number(variant.replace("variant", ""))}`
}

type OptionGridProps = {
  category: AvatarCategory
  engine: AvatarEngine | null
  config: AvatarConfig
  onChange: (config: AvatarConfig) => void
}

function VariantGrid({ category, engine, config, onChange }: OptionGridProps) {
  const key = category.key as VariantCategoryKey
  // Thumbnails depend on every category except the one being browsed, so picking
  // an option here does not regenerate the whole grid.
  const restKey = useMemo(() => {
    const rest: Partial<AvatarConfig> = { ...config }
    delete rest[key]
    return JSON.stringify(rest)
  }, [config, key])

  const thumbnails = useMemo(() => {
    if (!engine) {
      return []
    }

    const rest = JSON.parse(restKey) as AvatarConfig

    return AVATAR_VARIANTS[key].map((variant) => ({
      variant,
      source: svgToDataUri(
        buildAvatarSvg(engine, setCategoryValue(rest, key, variant), {
          size: 96,
          focus: category.focus,
        }),
      ),
    }))
  }, [engine, key, restKey, category.focus])

  const selected = getCategoryValue(config, key)

  if (!engine) {
    return (
      <>
        {Array.from({ length: 10 }, (_, index) => (
          <Skeleton
            key={index}
            className="aspect-square rounded-lg"
          />
        ))}
      </>
    )
  }

  return (
    <>
      {category.optional ? (
        <OptionTile
          label={`No ${category.label.toLowerCase()}`}
          selected={selected === undefined}
          onSelect={() => onChange(setCategoryValue(config, key, undefined))}
        >
          <span className="text-xs text-muted-foreground">None</span>
        </OptionTile>
      ) : null}
      {thumbnails.map((thumbnail) => (
        <OptionTile
          key={thumbnail.variant}
          label={variantLabel(category, thumbnail.variant)}
          selected={selected === thumbnail.variant}
          onSelect={() =>
            onChange(setCategoryValue(config, key, thumbnail.variant))
          }
        >
          <img
            src={thumbnail.source}
            alt=""
            width={96}
            height={96}
            draggable={false}
            className="size-full object-cover"
          />
        </OptionTile>
      ))}
    </>
  )
}

function BackgroundGrid({
  config,
  onChange,
}: Pick<OptionGridProps, "config" | "onChange">) {
  return (
    <>
      {BACKGROUND_SWATCHES.map((color, index) => (
        <OptionTile
          key={color}
          label={`Background ${index + 1}`}
          selected={config.backgroundColor === color}
          onSelect={() =>
            onChange(setCategoryValue(config, "backgroundColor", color))
          }
        >
          <span
            className="size-full"
            style={{ backgroundColor: color }}
          />
        </OptionTile>
      ))}
      <label
        className="relative flex aspect-square cursor-pointer flex-col items-center justify-center gap-1 overflow-hidden rounded-lg border border-dashed border-white/20 text-xs text-muted-foreground transition-colors focus-within:ring-2 focus-within:ring-ring hover:border-white/40 hover:text-foreground"
      >
        <span>Custom</span>
        <input
          type="color"
          aria-label="Custom background color"
          value={config.backgroundColor}
          onChange={(event) =>
            onChange(
              setCategoryValue(
                config,
                "backgroundColor",
                event.target.value.toLowerCase(),
              ),
            )
          }
          className="size-6 cursor-pointer rounded-full border-0 bg-transparent p-0"
        />
      </label>
    </>
  )
}

type EditorBodyProps = {
  agent: Agent
  onOpenChange: (open: boolean) => void
}

function AvatarEditorBody({ agent, onOpenChange }: EditorBodyProps) {
  const [config, setConfig] = useState<AvatarConfig>(() =>
    agent.avatar_config
      ? normalizeAvatarConfig(agent.avatar_config)
      : randomAvatarConfig(),
  )
  const [activeKey, setActiveKey] = useState(AVATAR_CATEGORIES[0].key)
  const [engine, setEngine] = useState<AvatarEngine | null>(null)
  const [engineFailed, setEngineFailed] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const uploadAvatar = useUploadAgentAvatar()
  const deleteAvatar = useDeleteAgentAvatar()
  const isRemoving = deleteAvatar.isPending
  const isBusy = isSaving || isRemoving
  const activeCategory =
    AVATAR_CATEGORIES.find((category) => category.key === activeKey) ??
    AVATAR_CATEGORIES[0]

  useEffect(() => {
    let cancelled = false

    loadAvatarEngine()
      .then((loaded) => {
        if (!cancelled) {
          setEngine(loaded)
        }
      })
      .catch(() => {
        if (!cancelled) {
          setEngineFailed(true)
        }
      })

    return () => {
      cancelled = true
    }
  }, [])

  const previewSource = useMemo(
    () =>
      engine
        ? svgToDataUri(buildAvatarSvg(engine, config, { size: 400 }))
        : null,
    [engine, config],
  )

  function moveTab(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const step =
      event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0

    if (step === 0) {
      return
    }

    event.preventDefault()
    const next =
      AVATAR_CATEGORIES[
        (index + step + AVATAR_CATEGORIES.length) % AVATAR_CATEGORIES.length
      ]
    setActiveKey(next.key)
    document.getElementById(`avatar-editor-${next.key}-tab`)?.focus()
  }

  async function save() {
    setIsSaving(true)

    try {
      const file = await renderAvatarPng(config)
      await uploadAvatar.mutateAsync({ agentId: agent.id, file, config })
      toast.add({
        type: "success",
        title: "Avatar saved",
        description: `${agent.name} has a new look.`,
      })
      onOpenChange(false)
    } catch {
      toast.add({
        type: "error",
        title: "Avatar could not be saved",
        description: "Please try again.",
      })
    } finally {
      setIsSaving(false)
    }
  }

  async function remove() {
    try {
      await deleteAvatar.mutateAsync(agent.id)
      toast.add({
        type: "success",
        title: "Avatar removed",
        description: `${agent.name} is back to its initials.`,
      })
      onOpenChange(false)
    } catch {
      toast.add({
        type: "error",
        title: "Avatar could not be removed",
        description: "Please try again.",
      })
    }
  }

  return (
    <>
      <DialogHeader className="px-6 pt-6 pr-14">
        <DialogTitle>Edit avatar</DialogTitle>
        <DialogDescription>
          Build a look for {agent.name}. The image is drawn in your browser and
          uploaded when you save.
        </DialogDescription>
      </DialogHeader>

      <div className="grid gap-6 px-6 md:grid-cols-[13rem_minmax(0,1fr)]">
        <div className="flex flex-col items-center gap-4">
          <div className="relative size-44 overflow-hidden rounded-full border border-white/14 bg-white/[0.03] shadow-[0_0_0_6px_rgba(255,255,255,0.03)]">
            {previewSource ? (
              <img
                src={previewSource}
                alt="Avatar preview"
                width={176}
                height={176}
                draggable={false}
                className="size-full object-cover"
              />
            ) : (
              <Skeleton className="size-full rounded-full" />
            )}
          </div>
          <div className="flex w-full flex-wrap justify-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={isBusy || !engine}
              onClick={() => setConfig(randomAvatarConfig())}
            >
              <HugeiconsIcon
                icon={ShuffleIcon}
                strokeWidth={2}
              />
              Randomize
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              aria-pressed={config.flip}
              disabled={isBusy || !engine}
              onClick={() =>
                setConfig((current) => ({ ...current, flip: !current.flip }))
              }
            >
              <HugeiconsIcon
                icon={FlipHorizontalIcon}
                strokeWidth={2}
              />
              Flip
            </Button>
          </div>
        </div>

        <div className="min-w-0">
          <div
            role="tablist"
            aria-label="Avatar parts"
            className="flex overflow-x-auto border-b border-white/10"
          >
            {AVATAR_CATEGORIES.map((category, index) => (
              <button
                key={category.key}
                type="button"
                role="tab"
                id={`avatar-editor-${category.key}-tab`}
                aria-selected={activeKey === category.key}
                aria-controls="avatar-editor-panel"
                tabIndex={activeKey === category.key ? 0 : -1}
                onClick={() => setActiveKey(category.key)}
                onKeyDown={(event) => moveTab(event, index)}
                className={cn(
                  "mr-4 shrink-0 border-b-2 px-1 pb-2.5 text-sm outline-none transition-colors focus-visible:text-foreground",
                  activeKey === category.key
                    ? "border-foreground text-foreground"
                    : "border-transparent text-muted-foreground hover:text-foreground",
                )}
              >
                {category.label}
              </button>
            ))}
          </div>

          <div
            role="tabpanel"
            id="avatar-editor-panel"
            aria-labelledby={`avatar-editor-${activeCategory.key}-tab`}
            className="mt-4"
          >
            {engineFailed ? (
              <p className="text-sm text-muted-foreground">
                The avatar parts could not be loaded. Close this dialog and try
                again.
              </p>
            ) : (
              <div className="h-72 overflow-y-auto pr-1">
                <div
                  role="radiogroup"
                  aria-label={activeCategory.label}
                  className="grid grid-cols-4 gap-2 sm:grid-cols-5"
                >
                  {activeCategory.key === "backgroundColor" ? (
                    <BackgroundGrid
                      config={config}
                      onChange={setConfig}
                    />
                  ) : (
                    <VariantGrid
                      key={activeCategory.key}
                      category={activeCategory}
                      engine={engine}
                      config={config}
                      onChange={setConfig}
                    />
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      <DialogFooter className="items-center border-t border-white/10 px-6 py-4 sm:justify-between">
        <p className="text-xs text-muted-foreground">
          Art: Notionists by Zoish (CC0), via DiceBear.
        </p>
        <div className="flex flex-col-reverse gap-2 sm:flex-row">
          {agent.avatar ? (
            <Button
              type="button"
              variant="destructive"
              disabled={isBusy}
              onClick={() => void remove()}
            >
              {isRemoving ? "Removing..." : "Remove avatar"}
            </Button>
          ) : null}
          <Button
            type="button"
            disabled={isBusy || !engine}
            onClick={() => void save()}
          >
            {isSaving ? "Saving..." : "Save avatar"}
          </Button>
        </div>
      </DialogFooter>
    </>
  )
}

export function AvatarEditorDialog({
  agent,
  open,
  onOpenChange,
}: AvatarEditorDialogProps) {
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
    >
      <DialogContent className="max-h-[calc(100svh-2rem)] max-w-4xl gap-5 overflow-y-auto border-white/14 bg-[#101012] p-0 pb-0">
        <AvatarEditorBody
          agent={agent}
          onOpenChange={onOpenChange}
        />
      </DialogContent>
    </Dialog>
  )
}
