#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
. "$SCRIPT_DIR/lib.sh"

verified_backup=false
if [[ "${1:-}" == "--verified-safety-backup" ]]; then
  verified_backup=true
  shift
fi
if [[ "$#" -ne 0 ]]; then
  echo "error: unsupported migrate argument: $1" >&2
  exit 2
fi

preflight_args=(
  python -m app.cli migration-preflight
)
if [[ "$verified_backup" == "true" ]]; then
  preflight_args+=(--verified-safety-backup)
fi

compose run --rm --no-deps zero-nvr   "${preflight_args[@]}"

compose run --rm --no-deps zero-nvr   alembic upgrade head

compose run --rm --no-deps zero-nvr   python -m app.cli migration-verify
