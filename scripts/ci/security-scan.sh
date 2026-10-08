#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"

if ! command -v gitleaks >/dev/null 2>&1; then
  cat >&2 <<'EOF'
gitleaks is required for the security scan.
Install it from https://github.com/gitleaks/gitleaks/releases and rerun this command.
CI uses the pinned gitleaks GitHub Action in .github/workflows/merge-checks.yml.
EOF
  exit 127
fi

gitleaks detect \
  --source "$ROOT_DIR" \
  --gitleaks-ignore-path "$ROOT_DIR/.gitleaksignore" \
  --redact \
  --no-banner
