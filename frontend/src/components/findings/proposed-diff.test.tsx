// @vitest-environment jsdom

import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import { ProposedDiff } from "@/components/findings/proposed-diff"
import { parseUnifiedDiff } from "@/components/findings/unified-diff"
import reliableFixtures from "@/components/findings/fixtures/reliable-patches.json"
import { useFindingRemediations } from "@/hooks/use-findings"

vi.mock("@/hooks/use-findings", () => ({ useFindingRemediations: vi.fn() }))

const mockedUseFindingRemediations = vi.mocked(useFindingRemediations)

describe("ProposedDiff", () => {
  const diff = [
    "diff --git a/src/a.ts b/src/a.ts",
    "index 1111111..2222222 100644",
    "--- a/src/a.ts",
    "+++ b/src/a.ts",
    "@@ -1,2 +1,2 @@",
    " const retained = true",
    "-const oldValue = false",
    "+const newValue = true",
    "diff --git a/src/b.ts b/src/b.ts",
    "new file mode 100644",
    "--- /dev/null",
    "+++ b/src/b.ts",
    "@@ -0,0 +1 @@",
    "+<script>alert(1)</script>",
  ].join("\n")

  it("parses line numbers and changes per file", () => {
    expect(parseUnifiedDiff(diff)).toEqual([
      {
        additions: 1,
        deletions: 1,
        lines: [
          {
            content: "const retained = true",
            kind: "context",
            newLineNumber: 1,
            oldLineNumber: 1,
          },
          {
            content: "const oldValue = false",
            kind: "deletion",
            newLineNumber: null,
            oldLineNumber: 2,
          },
          {
            content: "const newValue = true",
            kind: "addition",
            newLineNumber: 2,
            oldLineNumber: null,
          },
        ],
        path: "src/a.ts",
      },
      {
        additions: 1,
        deletions: 0,
        lines: [
          {
            content: "<script>alert(1)</script>",
            kind: "addition",
            newLineNumber: 1,
            oldLineNumber: null,
          },
        ],
        path: "src/b.ts",
      },
    ])
  })

  it("renders every file as a closed, safe accordion", () => {
    mockedUseFindingRemediations.mockReturnValue({
      data: [{ proposed_diff: diff }],
    } as ReturnType<typeof useFindingRemediations>)

    render(<ProposedDiff findingId="finding-a" />)

    expect(screen.getByText("Proposed changes")).toBeTruthy()
    expect(screen.getByText("src/a.ts")).toBeTruthy()
    expect(screen.getByText("src/b.ts")).toBeTruthy()
    expect(document.querySelectorAll("details")[0].open).toBe(false)

    fireEvent.click(screen.getByText("src/a.ts"))

    expect(document.querySelectorAll("details")[0].open).toBe(true)
    expect(screen.getByText("const retained = true")).toBeTruthy()
    expect(screen.getByText("const oldValue = false")).toBeTruthy()
    expect(screen.getByText("const newValue = true")).toBeTruthy()
    expect(screen.queryByText("@@ -1,2 +1,2 @@")).toBeNull()
    expect(document.querySelector("script")).toBeNull()
  })
})
it("renders paths and line counts from the shared native patch fixtures", () => {
  for (const fixture of reliableFixtures) {
    const files = parseUnifiedDiff(fixture.diff)
    expect(files).toHaveLength(1)
    expect(files[0].path).toBe(fixture.path)
  }
})

