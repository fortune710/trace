import { describe, expect, it } from "vitest"

import { assertPathFree } from "@/test/path-redaction"

describe("assertPathFree", () => {
  it.each([
    "/Users/trace/project",
    "/private/var/folders/trace/project",
    "C:\\Users\\trace\\project",
    "\\\\server\\share\\trace-project",
  ])("rejects an absolute local path: %s", (path) => {
    expect(() => assertPathFree({ error: path })).toThrow("absolute local path")
  })

  it("allows safe display metadata and opaque source IDs", () => {
    expect(() => assertPathFree({ sourceId: "source-123", displayName: "Trace project" })).not.toThrow()
  })
})
