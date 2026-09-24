#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
. "$SCRIPT_DIR/lib.sh"

usage() {
  cat <<'EOF'
Usage:
  ./deploy.sh camera-acceptance prepare <camera-id>
  ./deploy.sh camera-acceptance restart <camera-id>
  ./deploy.sh camera-acceptance status <camera-id>
  ./deploy.sh camera-acceptance verify <camera-id> --live-confirmed --playback-confirmed

The final verify intentionally requires operator confirmation of real browser
Live and timeline playback. Synthetic sources do not satisfy this gate.
EOF
}

action="${1:-}"
camera_id="${2:-}"

if [[ "$action" == "-h" || "$action" == "--help" || -z "$action" ]]; then
  usage
  [[ -n "$action" ]] && exit 0
  exit 2
fi

if [[ -z "$camera_id" ]]; then
  echo "error: camera-id is required" >&2
  usage >&2
  exit 2
fi

shift 2

case "$action" in
  prepare)
    [[ "$#" -eq 0 ]] || {
      echo "error: prepare accepts no extra arguments" >&2
      exit 2
    }
    ZERO_NVR_ENV_FILE="$ENV_FILE" \
      "$SCRIPT_DIR/check.sh" >/dev/null
    compose exec -T zero-nvr \
      python -m app.cli camera-acceptance \
      prepare --camera-id "$camera_id"
    ;;
  restart)
    [[ "$#" -eq 0 ]] || {
      echo "error: restart accepts no extra arguments" >&2
      exit 2
    }
    compose exec -T zero-nvr \
      python -m app.cli camera-acceptance \
      status --camera-id "$camera_id" >/dev/null

    compose restart zlmediakit
    compose restart zero-nvr zero-nvr-worker
    compose up -d --wait --wait-timeout 180 \
      zlmediakit zero-nvr zero-nvr-worker

    ZERO_NVR_ENV_FILE="$ENV_FILE" \
      "$SCRIPT_DIR/check.sh" >/dev/null

    compose exec -T zero-nvr \
      python -m app.cli camera-acceptance \
      mark-restart --camera-id "$camera_id"
    ;;
  status)
    [[ "$#" -eq 0 ]] || {
      echo "error: status accepts no extra arguments" >&2
      exit 2
    }
    compose exec -T zero-nvr \
      python -m app.cli camera-acceptance \
      status --camera-id "$camera_id"
    ;;
  verify)
    live=false
    playback=false
    while [[ "$#" -gt 0 ]]; do
      case "$1" in
        --live-confirmed)
          live=true
          ;;
        --playback-confirmed)
          playback=true
          ;;
        *)
          echo "error: unknown verify option: $1" >&2
          exit 2
          ;;
      esac
      shift
    done

    args=()
    [[ "$live" == true ]] \
      && args+=(--live-confirmed)
    [[ "$playback" == true ]] \
      && args+=(--playback-confirmed)

    ZERO_NVR_ENV_FILE="$ENV_FILE" \
      "$SCRIPT_DIR/check.sh" >/dev/null
    compose exec -T zero-nvr \
      python -m app.cli camera-acceptance \
      verify --camera-id "$camera_id" \
      "${args[@]}"
    ;;
  *)
    echo "error: unsupported camera-acceptance action: $action" >&2
    usage >&2
    exit 2
    ;;
esac
