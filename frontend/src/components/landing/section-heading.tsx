import type { ReactNode } from "react"

import { cn } from "cn"

type SectionHeadingProps = {
  id?: string
  eyebrow?: string
  title: ReactNode
  description?: ReactNode
  align?: "left" | "center"
}

export function SectionHeading({
  id,
  eyebrow,
  title,
  description,
  align = "center",
}: SectionHeadingProps) {
  return (
    <div
      className={cn(
        "flex flex-col gap-4",
        align === "center" && "mx-auto items-center text-center",
      )}
    >
      {eyebrow ? (
        <p className="text-sm font-medium tracking-wide text-muted-foreground">
          {eyebrow}
        </p>
      ) : null}
      <h2
        id={id}
        className="max-w-3xl font-display text-[40px] leading-none tracking-tight text-balance sm:text-5xl md:text-6xl lg:text-7xl"
      >
        {title}
      </h2>
      {description ? (
        <p className="max-w-2xl text-lg text-pretty text-foreground/70">
          {description}
        </p>
      ) : null}
    </div>
  )
}
