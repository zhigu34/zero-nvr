#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
. "$SCRIPT_DIR/lib.sh"

reason="${1:-manual}"
policy="${2:-}"

args=(python -m app.cli backup --reason "$reason")
if [[ -n "$policy" ]]; then
  args+=(--policy "$policy")
fi

compose run --rm --no-deps zero-nvr "${args[@]}"
