#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
. "$SCRIPT_DIR/lib.sh"

verified_backup=false
maintenance=false

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --verified-safety-backup)
      verified_backup=true
      ;;
    --maintenance)
      maintenance=true
      ;;
    *)
      echo "error: unsupported migrate argument: $1" >&2
      exit 2
      ;;
  esac
  shift
done

preflight_args=(
  python -m app.cli migration-preflight
)
if [[ "$verified_backup" == "true" ]]; then
  preflight_args+=(--verified-safety-backup)
fi
if [[ "$maintenance" == "true" ]]; then
  preflight_args+=(--maintenance)
fi

compose run --rm --no-deps zero-nvr   "${preflight_args[@]}"

compose run --rm --no-deps zero-nvr   alembic upgrade head

compose run --rm --no-deps zero-nvr   python -m app.cli migration-verify
