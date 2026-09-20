#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
. "$SCRIPT_DIR/lib.sh"

recovery_env="${ZERO_NVR_RECOVERY_ENV:-$ROOT_DIR/deploy/recovery.env}"

usage() {
  cat <<'EOF'
Usage:
  scripts/restore.sh list
  scripts/restore.sh [snapshot-id|latest] --force

The restore bootstrap credentials are read from deploy/recovery.env by default.
The deployment .env must contain the original ZERO_NVR_SECRET_KEY.
EOF
}

if [[ ! -f "$recovery_env" ]]; then
  echo "error: recovery environment not found: $recovery_env" >&2
  echo "copy deploy/recovery.env.example to deploy/recovery.env and fill it from the RecoveryKit" >&2
  exit 1
fi

recovery_env="$(CDPATH= cd -- "$(dirname -- "$recovery_env")" && pwd)/$(basename -- "$recovery_env")"

run_restic() {
  compose run --rm --no-deps \
    -v "$recovery_env:/run/zero-nvr-recovery.env:ro" \
    zero-nvr \
    sh -ec '
      set -a
      . /run/zero-nvr-recovery.env
      set +a
      : "${RESTIC_REPOSITORY:?RESTIC_REPOSITORY is required}"
      : "${RESTIC_PASSWORD:?RESTIC_PASSWORD is required}"
      exec restic "$@"
    ' restic "$@"
}

command="${1:-latest}"
shift || true

if [[ "$command" == "list" ]]; then
  run_restic snapshots --tag zero-nvr
  exit 0
fi

force=false
for arg in "$@"; do
  case "$arg" in
    --force) force=true ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown restore option: $arg" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ "$force" != true ]]; then
  echo "error: restore is destructive and requires --force" >&2
  usage >&2
  exit 2
fi

snapshot="$command"
staging="/var/cache/zero-nvr/restore-staging"

echo "Stopping zero-nvr control plane; ZLMediaKit remains running..."
compose stop zero-nvr-worker zero-nvr >/dev/null 2>&1 || true

compose run --rm --no-deps zero-nvr \
  sh -ec 'rm -rf /var/cache/zero-nvr/restore-staging && mkdir -p /var/cache/zero-nvr/restore-staging'

if [[ "$snapshot" == "latest" ]]; then
  run_restic restore latest \
    --tag zero-nvr \
    --target "$staging"
else
  run_restic restore "$snapshot" \
    --target "$staging"
fi

echo "Validating staged backup and replacing database atomically..."
compose run --rm --no-deps zero-nvr \
  python -m app.cli restore-staged \
  --root "$staging" \
  --force

compose run --rm --no-deps zero-nvr \
  sh -ec 'rm -rf /var/cache/zero-nvr/restore-staging'

echo "Starting restored control plane..."
compose up -d zero-nvr zero-nvr-worker

echo "Restore completed. Recording media was not modified."
