# Development Instructions

## TypeScript and TSX Formatting

- Format TypeScript and TSX for readability. Do not condense component or function bodies, JSX trees, or return statements onto a single line.
- Use one prop per line when a JSX element has multiple props or would otherwise be difficult to scan.
- Keep nested conditional rendering and callback bodies expanded across lines.

## Merge-check verification

- Before committing, run the GitHub Actions merge checks locally with `act` when the required runner support is available. If `act` cannot faithfully run a job (for example, a macOS or Windows job), run that workflow job's equivalent commands locally instead.
- Do not commit until the applicable merge-check commands pass, or explicitly report the environment-specific blocker and its impact to the user.
