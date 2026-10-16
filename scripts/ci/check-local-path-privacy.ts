import assert from "node:assert/strict"
import { readFile } from "node:fs/promises"
import path from "node:path"

const repositoryDirectory = path.resolve(import.meta.dir, "../..")

async function source(relativePath: string) {
  return readFile(path.join(repositoryDirectory, relativePath), "utf8")
}

function functionBody(contents: string, functionName: string) {
  const start = contents.indexOf(`function ${functionName}`)
  assert.notEqual(start, -1, `${functionName} must exist`)

  const openingBrace = contents.indexOf("{", start)
  assert.notEqual(openingBrace, -1, `${functionName} must have a body`)

  let depth = 0
  for (let index = openingBrace; index < contents.length; index += 1) {
    if (contents[index] === "{") depth += 1
    if (contents[index] !== "}") continue

    depth -= 1
    if (depth === 0) return contents.slice(start, index + 1)
  }

  throw new Error(`${functionName} has an unterminated body`)
}

const desktopProjects = await source("frontend/src/lib/desktop-projects.ts")
const folderPicker = await source("frontend/src/hooks/use-local-folder-picker.ts")
const nativePicker = await source("frontend/src-tauri/src/folder_picker.rs")

assert.doesNotMatch(
  functionBody(desktopProjects, "toProjectResponse"),
  /canonicalPath/,
  "safe project responses must not include canonicalPath",
)
assert.doesNotMatch(
  functionBody(folderPicker, "safeSelection"),
  /canonicalPath/,
  "safe picker selections must not include canonicalPath",
)
assert.match(nativePicker, /pub struct FolderPickerError \{\s*pub code:/s)
const nativeErrorStruct = nativePicker.slice(
  nativePicker.indexOf("pub struct FolderPickerError"),
  nativePicker.indexOf("}", nativePicker.indexOf("pub struct FolderPickerError")) + 1,
)
assert.doesNotMatch(
  nativeErrorStruct,
  /canonical_path|path:/,
  "native picker errors must not serialize paths",
)

const productionFrontendFiles = [
  "frontend/src/lib/desktop-projects.ts",
  "frontend/src/hooks/use-local-folder-picker.ts",
  "frontend/src/lib/local-projects-database.ts",
]

for (const relativePath of productionFrontendFiles) {
  const contents = await source(relativePath)
  assert.doesNotMatch(
    contents,
    /(?:console\.(?:log|warn|error)|telemetry|analytics)[^\n]*(?:canonicalPath|localCanonicalPath|source\.contents)/,
    `${relativePath} must not log or emit local paths or source contents`,
  )
}

console.log("desktop local-path privacy scan passed")
