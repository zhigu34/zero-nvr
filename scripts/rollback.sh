#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
. "$SCRIPT_DIR/lib.sh"
. "$SCRIPT_DIR/deployment-state.sh"
. "$SCRIPT_DIR/artifact-pins.sh"
. "$SCRIPT_DIR/release-manifest.sh"

requested="${1:-}"
if [[ "$#" -gt 1 ]]; then
  echo "error: rollback accepts at most one recorded version" >&2
  exit 2
fi

preflight_rollback() {
  require_command docker
  require_command git
  docker compose version >/dev/null
  docker info >/dev/null

  if [[ ! -f "$ENV_FILE" ]]; then
    echo "error: .env is missing" >&2
    return 1
  fi

  if ! git -C "$ROOT_DIR" diff --quiet --ignore-submodules -- \
      || ! git -C "$ROOT_DIR" diff --cached --quiet --ignore-submodules --; then
    echo "error: rollback requires a clean tracked Git worktree" >&2
    echo "commit or stash source changes first; untracked runtime files are ignored" >&2
    return 1
  fi
}

resolve_target() {
  local recorded="$1"
  local context="$2"
  local resolved

  if ! valid_revision "$recorded"; then
    echo "error: no valid $context revision is available" >&2
    return 1
  fi

  if [[ -z "$requested" ]]; then
    printf '%s' "$recorded"
    return 0
  fi

  resolved="$(
    git -C "$ROOT_DIR" rev-parse --verify "${requested}^{commit}" 2>/dev/null \
      || true
  )"
  if [[ "$resolved" != "$recorded" ]]; then
    echo "error: requested version does not match the recorded $context revision" >&2
    echo "recorded revision: $recorded" >&2
    return 1
  fi
  printf '%s' "$recorded"
}

preflight_rollback

deployed="$(deployment_state_get DEPLOYED_REVISION)"
recorded_rollback="$(deployment_state_get ROLLBACK_REVISION)"
recorded_snapshot="$(deployment_state_get ROLLBACK_SNAPSHOT_REL)"
recorded_image="$(deployment_state_get ROLLBACK_IMAGE_REF)"
pending_target="$(deployment_state_get PENDING_TARGET_REVISION)"
pending_previous="$(deployment_state_get PENDING_PREVIOUS_REVISION)"
pending_snapshot="$(deployment_state_get PENDING_SNAPSHOT_REL)"
pending_previous_image="$(deployment_state_get PENDING_PREVIOUS_IMAGE_REF)"
current_source="$(git_revision || true)"
mode="normal"

if ! valid_revision "$deployed"; then
  echo "error: recorded deployed revision is unavailable" >&2
  exit 1
fi

if valid_revision "$pending_target" \
  && [[ "$pending_previous" == "$deployed" ]] \
  && { [[ "$current_source" == "$pending_target" ]] \
    || [[ "$current_source" == "$pending_previous" ]]; }; then
  mode="failed-update"
  target="$(resolve_target "$pending_previous" "pre-update")"
  snapshot_rel="$pending_snapshot"
  target_image_ref="$pending_previous_image"
  echo "Detected failed/pending update $pending_target; recovering deployed revision $target."
elif [[ "$current_source" == "$deployed" ]]; then
  target="$(resolve_target "$recorded_rollback" "rollback")"
  snapshot_rel="$recorded_snapshot"
  target_image_ref="$recorded_image"
else
  echo "error: source checkout does not match deployed or pending update state" >&2
  echo "deployed: ${deployed:-unavailable}" >&2
  echo "pending: ${pending_target:-none}" >&2
  echo "checkout: ${current_source:-unavailable}" >&2
  exit 1
fi

case "$snapshot_rel" in
  safety-backups/*/database.sqlite3|safety-backups/*/database.pgcustom)
    ;;
  *)
    echo "error: recorded rollback safety snapshot is invalid" >&2
    exit 1
    ;;
esac

snapshot_host="$(deployment_data_dir)/$snapshot_rel"
if [[ ! -f "$snapshot_host" ]]; then
  echo "error: recorded rollback safety snapshot is missing: $snapshot_host" >&2
  exit 1
fi

if ! git -C "$ROOT_DIR" cat-file -e "${target}^{commit}" 2>/dev/null; then
  echo "error: recorded rollback revision is not available in this Git clone: $target" >&2
  exit 1
fi

configured_image="$(env_get ZERO_NVR_IMAGE "zero-nvr:local")"
current_image_id="$(active_core_image_id)"
recovery_image="$(
  pin_image_source recovery "$current_source" "$current_image_id"
)"
pin_git_revision recovery "$current_source"

target_short="$(printf '%s' "$target" | cut -c1-12)"
stage_image="zero-nvr:rollback-stage-$target_short"
stage_dir=""

cleanup() {
  if [[ -n "${stage_dir:-}" ]]; then
    git -C "$ROOT_DIR" worktree remove --force "$stage_dir" >/dev/null 2>&1 || true
    rm -rf "$stage_dir" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

if artifact_image_exists "$target_image_ref"; then
  echo "Using pinned rollback image $target_image_ref."
  rollback_image_source="$target_image_ref"
else
  echo "Pinned rollback image unavailable; rebuilding revision $target."
  stage_dir="$(mktemp -d "${TMPDIR:-/tmp}/zero-nvr-rollback.XXXXXX")"
  rmdir "$stage_dir"
  git -C "$ROOT_DIR" worktree add --detach "$stage_dir" "$target" >/dev/null
  docker build \
    --file "$stage_dir/backend/Dockerfile" \
    --tag "$stage_image" \
    "$stage_dir"
  rollback_image_source="$stage_image"
fi

echo "Creating pre-rollback database safety snapshot..."
create_local_safety_snapshot
pre_rollback_snapshot="$SAFETY_SNAPSHOT_REL"

echo "Stopping zero-nvr control plane; ZLMediaKit remains running..."
compose stop zero-nvr-worker zero-nvr >/dev/null 2>&1 || true

apply_rollback() {
  compose run --rm --no-deps zero-nvr \
    python -m app.cli restore-safety-snapshot \
    --path "/var/lib/zero-nvr/$snapshot_rel" \
    --force || return 1

  git -C "$ROOT_DIR" checkout --detach "$target" || return 1
  docker tag "$rollback_image_source" "$configured_image" || return 1

  if [[ -x "$SCRIPT_DIR/render-zlm-config.sh" ]]; then
    ZERO_NVR_ENV_FILE="$ENV_FILE" \
      "$SCRIPT_DIR/render-zlm-config.sh" || return 1
  fi

  compose up -d --wait --wait-timeout 180 \
    zero-nvr zero-nvr-worker || return 1

  ZERO_NVR_ENV_FILE="$ENV_FILE" \
    "$SCRIPT_DIR/check.sh" || return 1

  if [[ -f "$ROOT_DIR/release-manifest.json" ]]; then
    record_release_manifest "$target" || return 1
  else
    rm -f "$(release_manifest_runtime_path)"
  fi
}

if ! apply_rollback; then
  echo "Rollback failed; attempting to recover the pre-rollback state $current_source..." >&2

  git -C "$ROOT_DIR" checkout --detach "$current_source" >/dev/null 2>&1 || true
  docker tag "$recovery_image" "$configured_image" >/dev/null 2>&1 || true

  if [[ -x "$SCRIPT_DIR/render-zlm-config.sh" ]]; then
    ZERO_NVR_ENV_FILE="$ENV_FILE" \
      "$SCRIPT_DIR/render-zlm-config.sh" >/dev/null 2>&1 || true
  fi

  if [[ -n "$pre_rollback_snapshot" ]]; then
    compose run --rm --no-deps zero-nvr \
      python -m app.cli restore-safety-snapshot \
      --path "/var/lib/zero-nvr/$pre_rollback_snapshot" \
      --force >/dev/null 2>&1 || true
  fi

  compose up -d --wait --wait-timeout 180 \
    zero-nvr zero-nvr-worker >/dev/null 2>&1 || true

  if ZERO_NVR_ENV_FILE="$ENV_FILE" \
    "$SCRIPT_DIR/check.sh" >/dev/null 2>&1; then
    echo "Previous deployment recovered after rollback failure." >&2
    remove_artifact_image "$recovery_image"
    clear_git_pin recovery
  else
    echo "error: automatic recovery also failed" >&2
    echo "retained database safety points:" >&2
    echo "  $(deployment_data_dir)/$snapshot_rel" >&2
    echo "  $(deployment_data_dir)/$pre_rollback_snapshot" >&2
  fi
  exit 1
fi

if [[ "$mode" == "failed-update" ]]; then
  write_deployment_state \
    "$target" \
    "$recorded_rollback" \
    "$recorded_snapshot" \
    "" "" "" \
    "$recorded_image"

  remove_artifact_image "$pending_previous_image"
  clear_git_pin pending
  remove_artifact_image "$recovery_image"
  clear_git_pin recovery
else
  new_rollback_image="$(
    pin_image_source rollback "$deployed" "$recovery_image"
  )"
  pin_git_revision rollback "$deployed"

  write_deployment_state \
    "$target" \
    "$deployed" \
    "$pre_rollback_snapshot" \
    "" "" "" \
    "$new_rollback_image"

  if [[ -n "$recorded_image" \
    && "$recorded_image" != "$new_rollback_image" ]]; then
    remove_artifact_image "$recorded_image"
  fi
  remove_artifact_image "$recovery_image"
  clear_git_pin recovery
fi

docker image rm "$stage_image" >/dev/null 2>&1 || true

if [[ "$mode" == "failed-update" ]]; then
  echo "Failed update recovered: $current_source -> $target"
else
  echo "Rollback completed: $deployed -> $target"
fi
echo "Recording media was not modified."
