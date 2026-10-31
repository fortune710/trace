# Trace desktop development

Trace uses Tauri 2 to package the existing Vite React application for macOS and
Windows. The supported baseline is macOS 10.15 or later and Windows 10 or 11.

## Prerequisites

All platforms require Rust 1.90 or later and Bun. The desktop project pins Rust
1.90.0 in `frontend/src-tauri/rust-toolchain.toml`. macOS desktop development
requires Xcode Command Line Tools. Windows desktop development requires the
Visual Studio C++ Build Tools with **Desktop development with C++** selected,
plus Microsoft Edge WebView2.

The Tauri CLI and frontend plugins are installed from `frontend/package.json`.

## Environment modes

Vite modes provide build-time configuration:

```text
frontend/.env                 # local shared defaults; ignored
frontend/.env.example         # committed template
frontend/.env.web             # committed web defaults
frontend/.env.web.local       # local web overrides; ignored
frontend/.env.desktop         # committed desktop defaults
frontend/.env.desktop.local   # local desktop overrides; ignored
```

Only `VITE_*` values are available to frontend code. They are compiled into the
bundle and must never contain secrets, credentials, tokens, or absolute local
filesystem paths.

```bash
bun run --cwd frontend dev
bun run --cwd frontend dev:desktop
bun run --cwd frontend build
bun run --cwd frontend build:desktop
bun run --cwd frontend tauri:dev
bun run --cwd frontend tauri:build
```

`dev` and `build` use the `web` mode. Tauri commands use the `desktop` mode.
The runtime environment is determined by Tauri's `isTauri()` API, not by
`VITE_APP_MODE`.

The public landing page at `/` renders only in the browser. Inside the desktop
app, `/` redirects to `/account`. Its "Download for macOS" button points to
`VITE_DESKTOP_DOWNLOAD_URL` when that is set to an `https:` URL, and otherwise to
the repository's latest GitHub release.

The backend separately allows credentialed desktop origins with
`AUTH_DESKTOP_ALLOWED_ORIGINS`. Local development should include
`http://127.0.0.1:5173`; packaged builds use the configured Tauri webview
origins (`https://tauri.localhost` and `tauri://localhost`). This setting is
backend-only and must not be copied into a `VITE_*` variable. GitHub and Google
desktop sign-in reuse the existing server-side provider credentials and callback
URLs; no provider secret belongs in the desktop bundle.

## Storage boundary

The desktop SQLite database is created in Tauri's application-data directory.
Its path is not configured through an environment variable. Local projects and
their canonical source paths stay on the device and are partitioned by the
authenticated account. API projects are copied into the local cache at desktop
startup; local projects are preserved during refreshes.

The desktop source contract and store interfaces live in
`frontend/src/lib/desktop-projects.ts`. Desktop folder selection is provided by
`useLocalFolderPicker()`. The native picker validates and canonicalizes the
selected folder, grants filesystem scope only after explicit selection, and
stores the canonical path only in the account-scoped local database. React
receives an opaque source ID and safe display metadata. Local project creation is
completed entirely in the desktop database: the dialog skips repository and branch
selection for local folders, defaults the project name to the safe folder label,
and revalidates the source before inserting the local record. Missing, moved,
unreadable, and permission-denied folders remain recoverable without exposing
their paths.
