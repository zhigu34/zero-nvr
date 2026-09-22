#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ZERO_NVR_ENV_FILE:-$ROOT_DIR/.env}"
COMPOSE_FILE="$ROOT_DIR/docker-compose.yml"

env_get() {
  local key="$1"
  local fallback="${2:-}"
  if [[ ! -f "$ENV_FILE" ]]; then
    printf '%s' "$fallback"
    return 0
  fi

  local line value
  line="$(grep -E "^${key}=" "$ENV_FILE" | tail -n 1 || true)"
  if [[ -z "$line" ]]; then
    printf '%s' "$fallback"
    return 0
  fi
  value="${line#*=}"
  value="${value%$'\r'}"

  if [[ "$value" == \"*\" && "$value" == *\" ]]; then
    value="${value:1:${#value}-2}"
  elif [[ "$value" == \'*\' && "$value" == *\' ]]; then
    value="${value:1:${#value}-2}"
  fi
  printf '%s' "$value"
}

compose() {
  local profiles
  profiles="$(env_get COMPOSE_PROFILES "")"
  COMPOSE_PROFILES="$profiles" docker compose \
    --env-file "$ENV_FILE" \
    -f "$COMPOSE_FILE" \
    "$@"
}

require_command() {
  local command="$1"
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "error: required command not found: $command" >&2
    return 1
  fi
}

host_path() {
  local value="$1"
  if [[ "$value" = /* ]]; then
    printf '%s' "$value"
  else
    printf '%s/%s' "$ROOT_DIR" "$value"
  fi
}


protected_file_host_path() {
  local file_path="$1"
  local data_path

  if [[ "$file_path" == /var/lib/zero-nvr/* ]]; then
    data_path="$(env_get ZERO_NVR_DATA_PATH "./data/zero-nvr")"
    data_path="$(host_path "$data_path")"
    printf '%s/%s' \
      "$data_path" \
      "${file_path#/var/lib/zero-nvr/}"
    return 0
  fi

  host_path "$file_path"
}

protected_env_get() {
  local key="$1"
  local fallback="${2:-}"
  local direct file_path host_file value

  direct="$(env_get "$key" "")"
  file_path="$(env_get "${key}_FILE" "")"

  if [[ -n "$direct" && -n "$file_path" ]]; then
    echo "error: configure only one of $key or ${key}_FILE" >&2
    return 2
  fi
  if [[ -n "$direct" ]]; then
    printf '%s' "$direct"
    return 0
  fi
  if [[ -z "$file_path" ]]; then
    printf '%s' "$fallback"
    return 0
  fi

  host_file="$(protected_file_host_path "$file_path")"
  if [[ ! -f "$host_file" || ! -r "$host_file" ]]; then
    echo "error: ${key}_FILE is not a readable file: $file_path" >&2
    return 1
  fi

  value="$(cat -- "$host_file")"
  local carriage_return
  carriage_return="$(printf '\r')"
  value="${value%"$carriage_return"}"
  if [[ -z "$value" ]]; then
    echo "error: ${key}_FILE is empty: $file_path" >&2
    return 1
  fi
  if [[ "$value" == *}
\n'* ]]; then
    echo "error: ${key}_FILE must contain a single-line value: $file_path" >&2
    return 1
  fi
  printf '%s' "$value"
}
