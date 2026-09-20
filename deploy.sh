#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
SCRIPT_DIR="$ROOT_DIR/scripts"
. "$SCRIPT_DIR/lib.sh"

cd "$ROOT_DIR"

usage() {
  cat <<'EOF'
Usage:
  ./deploy.sh [install]
  ./deploy.sh update
  ./deploy.sh status
  ./deploy.sh doctor
  ./deploy.sh migrate
  ./deploy.sh backup [reason] [policy-id-or-name]
  ./deploy.sh restore list
  ./deploy.sh restore [snapshot-id|latest] --force
  ./deploy.sh admin reset-password <username>

Core deployment is intentionally three containers:
  zero-nvr API + zero-nvr worker + ZLMediaKit
EOF
}

random_hex_32() {
  od -An -N32 -tx1 /dev/urandom | tr -d ' \n'
}

set_env_value() {
  local key="$1"
  local value="$2"
  local tmp
  tmp="$(mktemp "$ROOT_DIR/.env.tmp.XXXXXX")"
  awk -v key="$key" -v value="$value" '
    BEGIN { found=0 }
    index($0, key "=") == 1 {
      print key "=" value
      found=1
      next
    }
    { print }
    END {
      if (!found) print key "=" value
    }
  ' "$ENV_FILE" > "$tmp"
  chmod 600 "$tmp"
  mv -f "$tmp" "$ENV_FILE"
}

ensure_env() {
  if [[ ! -f "$ENV_FILE" ]]; then
    cp "$ROOT_DIR/.env.example" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    echo "created: $ENV_FILE"
  fi

  local key value
  for key in \
    ZERO_NVR_SECRET_KEY \
    ZERO_NVR_ZLM_API_SECRET \
    ZERO_NVR_ZLM_HOOK_SECRET
  do
    value="$(env_get "$key")"
    if [[ -z "$value" ]]; then
      value="$(random_hex_32)"
      set_env_value "$key" "$value"
      echo "generated: $key"
    elif [[ ${#value} -lt 32 ]]; then
      echo "error: $key must be at least 32 characters" >&2
      exit 1
    fi
  done
}

ensure_host_dirs() {
  local key value path
  for key in \
    ZERO_NVR_DATA_PATH \
    ZERO_NVR_CACHE_PATH \
    ZERO_NVR_RECORDINGS_PATH
  do
    value="$(env_get "$key")"
    if [[ -z "$value" ]]; then
      echo "error: $key is empty" >&2
      exit 1
    fi
    path="$(host_path "$value")"
    mkdir -p "$path"
  done
}

preflight() {
  require_command docker
  docker compose version >/dev/null
  docker info >/dev/null
}

prepare_zlm() {
  local image
  image="$(env_get ZERO_NVR_ZLM_IMAGE "zlmediakit/zlmediakit:master")"
  docker pull "$image"
  ZERO_NVR_ENV_FILE="$ENV_FILE" \
    "$SCRIPT_DIR/render-zlm-config.sh"
}

build_backend() {
  compose build zero-nvr
}

install_stack() {
  preflight
  ensure_env
  ensure_host_dirs
  prepare_zlm
  build_backend
  compose up -d --wait --wait-timeout 180
  ZERO_NVR_ENV_FILE="$ENV_FILE" "$SCRIPT_DIR/check.sh"
}

update_stack() {
  preflight
  ensure_env
  ensure_host_dirs

  if [[ -n "$(compose images -q zero-nvr 2>/dev/null || true)" ]]; then
    echo "Creating pre-upgrade database safety snapshot..."
    compose run --rm --no-deps zero-nvr \
      python -m app.cli safety-snapshot
  else
    echo "WARN zero-nvr image is not installed; no pre-upgrade safety snapshot created" >&2
  fi

  prepare_zlm
  compose build --pull zero-nvr
  compose up -d --wait --wait-timeout 180
  ZERO_NVR_ENV_FILE="$ENV_FILE" "$SCRIPT_DIR/check.sh"
}

command="${1:-install}"
shift || true

case "$command" in
  install)
    install_stack
    ;;
  update)
    if [[ "$#" -ne 0 ]]; then
      echo "error: version-pinned update arguments are not implemented yet; check out the desired repo version first" >&2
      exit 2
    fi
    update_stack
    ;;
  status)
    ensure_env
    compose ps
    ;;
  doctor|check)
    ensure_env
    ensure_host_dirs
    ZERO_NVR_ENV_FILE="$ENV_FILE" "$SCRIPT_DIR/check.sh"
    ;;
  migrate)
    ensure_env
    "$SCRIPT_DIR/migrate.sh"
    ;;
  backup)
    ensure_env
    reason="${1:-manual}"
    policy="${2:-}"
    "$SCRIPT_DIR/backup.sh" "$reason" "$policy"
    ;;
  restore)
    preflight
    ensure_env
    ensure_host_dirs
    build_backend
    "$SCRIPT_DIR/restore.sh" "$@"
    ;;
  admin)
    subcommand="${1:-}"
    shift || true
    case "$subcommand" in
      reset-password)
        username="${1:-}"
        if [[ -z "$username" ]]; then
          echo "error: username is required" >&2
          exit 2
        fi
        ensure_env
        compose run --rm --no-deps zero-nvr \
          python -m app.cli admin-reset-password \
          --username "$username"
        ;;
      *)
        echo "error: unsupported admin command: $subcommand" >&2
        usage >&2
        exit 2
        ;;
    esac
    ;;
  feature)
    echo "error: managed optional service profiles are not yet present in docker-compose.yml" >&2
    echo "External Frigate/OpenList/MQTT integrations remain configurable in the product UI." >&2
    exit 2
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    echo "error: unknown command: $command" >&2
    usage >&2
    exit 2
    ;;
esac
