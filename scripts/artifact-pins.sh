#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/lib.sh"
. "$SCRIPT_DIR/deployment-state.sh"

artifact_git_ref() {
  local role="$1"
  case "$role" in
    rollback|pending|recovery)
      printf 'refs/zero-nvr/pins/%s' "$role"
      ;;
    *)
      echo "error: unsupported artifact pin role: $role" >&2
      return 2
      ;;
  esac
}

artifact_image_ref() {
  local role="$1"
  local revision="$2"
  local short

  artifact_git_ref "$role" >/dev/null
  if ! valid_revision "$revision"; then
    echo "error: invalid artifact revision: $revision" >&2
    return 2
  fi
  short="$(printf '%s' "$revision" | cut -c1-12)"
  printf 'zero-nvr:pin-%s-%s' "$role" "$short"
}

pin_git_revision() {
  local role="$1"
  local revision="$2"
  local ref

  require_command git
  if ! valid_revision "$revision"; then
    echo "error: cannot pin invalid Git revision: $revision" >&2
    return 2
  fi
  if ! git -C "$ROOT_DIR" cat-file -e "${revision}^{commit}" 2>/dev/null; then
    echo "error: cannot pin unavailable Git revision: $revision" >&2
    return 1
  fi

  ref="$(artifact_git_ref "$role")"
  git -C "$ROOT_DIR" update-ref "$ref" "$revision"
}

clear_git_pin() {
  local role="$1"
  local ref

  ref="$(artifact_git_ref "$role")"
  git -C "$ROOT_DIR" update-ref -d "$ref" >/dev/null 2>&1 || true
}

active_core_image_id() {
  local container_id image_id

  container_id="$(compose ps -a -q zero-nvr 2>/dev/null | head -n 1)"
  if [[ -z "$container_id" ]]; then
    echo "error: active zero-nvr container is unavailable" >&2
    return 1
  fi

  image_id="$(
    docker container inspect "$container_id"       --format '{{.Image}}' 2>/dev/null
  )"
  if [[ ! "$image_id" =~ ^sha256:[0-9a-fA-F]{64}$ ]]; then
    echo "error: active zero-nvr image identity is invalid" >&2
    return 1
  fi
  printf '%s' "$image_id"
}

artifact_image_exists() {
  local ref="$1"
  [[ -n "$ref" ]] || return 1
  docker image inspect "$ref" >/dev/null 2>&1
}

pin_image_source() {
  local role="$1"
  local revision="$2"
  local source="$3"
  local target

  target="$(artifact_image_ref "$role" "$revision")"
  docker image inspect "$source" >/dev/null
  docker tag "$source" "$target"
  printf '%s' "$target"
}

pin_active_core_image() {
  local role="$1"
  local revision="$2"
  local image_id

  image_id="$(active_core_image_id)"
  pin_image_source "$role" "$revision" "$image_id"
}

remove_artifact_image() {
  local ref="${1:-}"
  [[ -n "$ref" ]] || return 0
  case "$ref" in
    zero-nvr:pin-*)
      docker image rm "$ref" >/dev/null 2>&1 || true
      ;;
    *)
      echo "error: refusing to remove non-pin image ref: $ref" >&2
      return 2
      ;;
  esac
}
