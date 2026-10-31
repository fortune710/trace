export type DiffLineKind = "addition" | "context" | "deletion"

export type DiffLine = {
  content: string
  kind: DiffLineKind
  newLineNumber: number | null
  oldLineNumber: number | null
}

export type FileDiff = {
  additions: number
  deletions: number
  lines: DiffLine[]
  path: string
}

function pathFromHeader(path: string) {
  if (path.startsWith('"')) {
    try {
      path = JSON.parse(path) as string
    } catch {
      return path
    }
  }
  if (path === "/dev/null") return path
  return path.replace(/^[ab]\//, "")
}

function hunkStart(line: string) {
  const match = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(line)
  if (!match) return null

  return {
    newLineNumber: Number.parseInt(match[2], 10),
    oldLineNumber: Number.parseInt(match[1], 10),
  }
}

export function parseUnifiedDiff(diff: string): FileDiff[] {
  const files: FileDiff[] = []
  let currentFile: FileDiff | null = null
  let oldLineNumber = 0
  let newLineNumber = 0
  let insideHunk = false

  for (const line of diff.split("\n")) {
    let filePath: string | null = null
    const plainHeader = /^diff --git a\/(.+) b\/\1$/.exec(line)
    const quotedHeader = /^diff --git ("(?:[^"\\]|\\.)*") ("(?:[^"\\]|\\.)*")$/.exec(line)
    if (plainHeader) {
      filePath = plainHeader[1]
    } else if (quotedHeader) {
      filePath = pathFromHeader(quotedHeader[2])
    }
    if (filePath !== null) {
      currentFile = {
        additions: 0,
        deletions: 0,
        lines: [],
        path: filePath,
      }
      files.push(currentFile)
      insideHunk = false
      continue
    }

    if (!currentFile) continue

    if (!insideHunk && line.startsWith("--- ")) continue

    if (!insideHunk && line.startsWith("+++ ")) {
      const newPath = pathFromHeader(line.slice(4).split("\t", 1)[0])
      currentFile.path = newPath === "/dev/null" ? currentFile.path : newPath
      continue
    }

    const startingLineNumbers = hunkStart(line)
    if (startingLineNumbers) {
      oldLineNumber = startingLineNumbers.oldLineNumber
      newLineNumber = startingLineNumbers.newLineNumber
      insideHunk = true
      continue
    }

    if (!insideHunk || line.startsWith("\\ No newline at end of file")) continue
    if (!line || ![" ", "+", "-"].includes(line[0])) continue

    if (line.startsWith("+")) {
      currentFile.lines.push({
        content: line.slice(1),
        kind: "addition",
        newLineNumber,
        oldLineNumber: null,
      })
      currentFile.additions += 1
      newLineNumber += 1
      continue
    }

    if (line.startsWith("-")) {
      currentFile.lines.push({
        content: line.slice(1),
        kind: "deletion",
        newLineNumber: null,
        oldLineNumber,
      })
      currentFile.deletions += 1
      oldLineNumber += 1
      continue
    }

    const content = line.startsWith(" ") ? line.slice(1) : line
    currentFile.lines.push({
      content,
      kind: "context",
      newLineNumber,
      oldLineNumber,
    })
    oldLineNumber += 1
    newLineNumber += 1
  }

  return files
}
