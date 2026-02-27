#!/bin/bash
set -euo pipefail

EXPECTED_VERSION="0.1.0"
MARKER="$HOME/.local/share/guardrail/.installed-version"
MARKETPLACE="$HOME/.claude/plugins/marketplaces/tpdox"

NEEDS_INSTALL=0
if ! command -v guardrail-mcp &>/dev/null; then
  NEEDS_INSTALL=1
elif [ ! -f "$MARKER" ] || [ "$(cat "$MARKER")" != "$EXPECTED_VERSION" ]; then
  NEEDS_INSTALL=1
fi

if [ "$NEEDS_INSTALL" -eq 1 ]; then
  echo "Installing guardrail v$EXPECTED_VERSION..." >&2
  if [ -f "$MARKETPLACE/pyproject.toml" ]; then
    uv tool install --force "$MARKETPLACE" >&2
  else
    uv tool install --force "guardrail @ git+https://github.com/tpdox/guardrail" >&2
  fi
  mkdir -p "$(dirname "$MARKER")"
  echo "$EXPECTED_VERSION" > "$MARKER"
fi

# Config discovery: env var > XDG > marketplace copy
CONFIG=""
if [ -n "${GUARDRAIL_CONFIG:-}" ]; then CONFIG="$GUARDRAIL_CONFIG"
elif [ -f "$HOME/.config/guardrail/guardrail.yml" ]; then CONFIG="$HOME/.config/guardrail/guardrail.yml"
fi

if [ -n "$CONFIG" ]; then exec guardrail-mcp --config "$CONFIG"
else exec guardrail-mcp
fi
