// @vitest-environment jsdom

import { render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import { ProposedDiff } from "@/components/findings/proposed-diff"
import { useFindingRemediations } from "@/hooks/use-findings"

vi.mock("@/hooks/use-findings", () => ({ useFindingRemediations: vi.fn() }))

const mockedUseFindingRemediations = vi.mocked(useFindingRemediations)

describe("ProposedDiff", () => {
  it("renders stored unified diff text without HTML interpretation", () => {
    mockedUseFindingRemediations.mockReturnValue({
      data: [
        {
          proposed_diff:
            "diff --git a/a.ts b/a.ts\n@@ -1 +1 @@\n-old\n+<script>alert(1)</script>",
        },
      ],
    } as ReturnType<typeof useFindingRemediations>)

    render(<ProposedDiff findingId="finding-a" />)

    expect(screen.getByText("Proposed diff")).toBeTruthy()
    expect(screen.getByText("+<script>alert(1)</script>")).toBeTruthy()
    expect(document.querySelector("script")).toBeNull()
  })
})
