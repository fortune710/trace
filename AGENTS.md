# Development Instructions

## Application Page Layout

- In `AppShell`, use `mx-auto w-full max-w-6xl px-6 py-8 md:px-10 md:py-10` for primary application page content unless a deliberately constrained form or detail view requires an exception.

## Loading Skeletons

- Every routed page must have a dedicated loading skeleton component in the matching `frontend/src/components/<feature>/` folder. Pages that intentionally share one layout, such as the authentication flows, may share a single explicitly named skeleton component.
- Initial asynchronous page loading must render that skeleton instead of text-only loading copy. The skeleton must use `frontend/src/components/ui/skeleton.tsx` and mirror the page's structure, spacing, responsive grid, and primary content shape.

## TypeScript and TSX Formatting

- Format TypeScript and TSX for readability. Do not condense component or function bodies, JSX trees, or return statements onto a single line.
- Use one prop per line when a JSX element has multiple props or would otherwise be difficult to scan.
- Keep nested conditional rendering and callback bodies expanded across lines.

## Merge-check verification

- Before committing, run the GitHub Actions merge checks locally with `act` when the required runner support is available. If `act` cannot faithfully run a job (for example, a macOS or Windows job), run that workflow job's equivalent commands locally instead.
- Do not commit until the applicable merge-check commands pass, or explicitly report the environment-specific blocker and its impact to the user.

## End-to-end regression verification

- When a UI layout, navigation, or interaction flow is significantly redesigned, update and run the affected Playwright end-to-end tests before committing.
