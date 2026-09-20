#!/usr/bin/env bash
set -euo pipefail

deployment_data_dir() {
  host_path "$(env_get ZERO_NVR_DATA_PATH)"
}

deployment_state_file() {
  printf '%s/deployment/state.env' "$(deployment_data_dir)"
}

deployment_state_get() {
  local key="$1"
  local state line
  state="$(deployment_state_file)"
  if [[ ! -f "$state" ]]; then
    return 0
  fi
  line="$(grep -E "^${key}=" "$state" | tail -n 1 || true)"
  if [[ -n "$line" ]]; then
    printf '%s' "${line#*=}"
  fi
}

valid_revision() {
  [[ "$1" =~ ^[0-9a-fA-F]{40}$ ]]
}

git_revision() {
  if ! command -v git >/dev/null 2>&1; then
    return 1
  fi
  git -C "$ROOT_DIR" rev-parse --verify HEAD 2>/dev/null
}

write_deployment_state() {
  local deployed="$1"
  local rollback="${2:-}"
  local snapshot="${3:-}"
  local pending_target="${4:-}"
  local pending_previous="${5:-}"
  local pending_snapshot="${6:-}"
  local state_dir state tmp

  state_dir="$(deployment_data_dir)/deployment"
  state="$state_dir/state.env"
  mkdir -p "$state_dir"
  tmp="$(mktemp "$state_dir/state.env.tmp.XXXXXX")"
  {
    printf 'DEPLOYED_REVISION=%s\n' "$deployed"
    printf 'ROLLBACK_REVISION=%s\n' "$rollback"
    printf 'ROLLBACK_SNAPSHOT_REL=%s\n' "$snapshot"
    printf 'PENDING_TARGET_REVISION=%s\n' "$pending_target"
    printf 'PENDING_PREVIOUS_REVISION=%s\n' "$pending_previous"
    printf 'PENDING_SNAPSHOT_REL=%s\n' "$pending_snapshot"
    printf 'UPDATED_AT=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  } > "$tmp"
  chmod 600 "$tmp"
  mv -f "$tmp" "$state"
}

record_installed_revision() {
  local revision
  revision="$(git_revision || true)"
  if valid_revision "$revision"; then
    write_deployment_state "$revision" "" ""
  else
    echo "WARN git revision unavailable; automatic rollback will remain disabled" >&2
  fi
}

SAFETY_SNAPSHOT_REL=""

create_local_safety_snapshot() {
  local output snapshot relative host_file

  output="$(
    compose run --rm --no-deps zero-nvr \
      python -m app.cli safety-snapshot
  )"
  printf '%s\n' "$output"

  snapshot="$(
    printf '%s\n' "$output" \
      | sed -n 's/.*"safety_snapshot": "\([^"]*\)".*/\1/p' \
      | tail -n 1
  )"

  case "$snapshot" in
    /var/lib/zero-nvr/safety-backups/*)
      relative="${snapshot#/var/lib/zero-nvr/}"
      ;;
    *)
      echo "error: zero-nvr did not return a valid local safety snapshot path" >&2
      return 1
      ;;
  esac

  if [[ "$relative" == *".."* ]]; then
    echo "error: unsafe local safety snapshot path" >&2
    return 1
  fi

  host_file="$(deployment_data_dir)/$relative"
  if [[ ! -f "$host_file" ]]; then
    echo "error: safety snapshot was not found on the host: $host_file" >&2
    return 1
  fi

  SAFETY_SNAPSHOT_REL="$relative"
}
