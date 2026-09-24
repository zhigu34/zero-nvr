#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
. "$SCRIPT_DIR/lib.sh"

usage() {
  cat <<'EOF'
Usage:
  ./deploy.sh release-check <8|16> [--max-age-hours HOURS]

Checks persisted host validation evidence. The 8-camera V1 baseline requires
a matching benchmark, a soak of at least 3600 seconds, and a recent verified
backup. The 16-camera extended target requires the matching
16-camera-extended benchmark only; it is not a second long-duration baseline.
The command does not start a benchmark, soak, backup, restore, or any Docker
mutation.
EOF
}

expected="${1:-}"
if [[ "$expected" == "-h" || "$expected" == "--help" ]]; then
  usage
  exit 0
fi
shift || true

if [[ "$expected" != "8" && "$expected" != "16" ]]; then
  echo "error: release-check target must be 8 or 16 cameras" >&2
  usage >&2
  exit 2
fi

max_age_hours=168
while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --max-age-hours)
      shift
      max_age_hours="${1:-}"
      if [[ -z "$max_age_hours" ]]; then
        echo "error: --max-age-hours requires a value" >&2
        exit 2
      fi
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown release-check option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

if [[ ! "$max_age_hours" =~ ^[1-9][0-9]*$ ]]; then
  echo "error: --max-age-hours must be a positive integer" >&2
  exit 2
fi

require_command docker
docker compose version >/dev/null
docker info >/dev/null

if [[ ! -f "$ENV_FILE" ]]; then
  echo "error: .env is missing" >&2
  exit 1
fi

ZERO_NVR_ENV_FILE="$ENV_FILE" "$SCRIPT_DIR/check.sh"

for service in zero-nvr zero-nvr-worker zlmediakit; do
  if [[ -z "$(compose ps -q "$service" 2>/dev/null || true)" ]]; then
    echo "error: core service is not running: $service" >&2
    exit 1
  fi
done

compose exec -T zero-nvr \
  python -m app.cli release-readiness \
  --expected-cameras "$expected" \
  --max-age-hours "$max_age_hours"
