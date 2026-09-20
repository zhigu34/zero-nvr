#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
SCRIPT_DIR="$ROOT_DIR/scripts"
. "$SCRIPT_DIR/lib.sh"
. "$SCRIPT_DIR/deployment-state.sh"

cd "$ROOT_DIR"

usage() {
  cat <<'EOF'
Usage:
  ./deploy.sh [install]
  ./deploy.sh update [version] [--backup-policy <id-or-name>]
  ./deploy.sh rollback [version]
  ./deploy.sh status
  ./deploy.sh doctor
  ./deploy.sh migrate
  ./deploy.sh backup [reason] [policy-id-or-name]
  ./deploy.sh restore list
  ./deploy.sh restore [snapshot-id|latest] --force
  ./deploy.sh recovery-kit export [directory] [policy-id-or-name]
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
  "$SCRIPT_DIR/migrate.sh"
  compose up -d --wait --wait-timeout 180
  ZERO_NVR_ENV_FILE="$ENV_FILE" "$SCRIPT_DIR/check.sh"
  record_installed_revision
}

update_stack() {
  local backup_policy="${1:-}"
  local requested_ref="${2:-}"
  local target_revision previous_revision
  local previous_rollback_revision previous_rollback_snapshot
  local pending_target environment current_source
  local rollback_revision="" rollback_snapshot=""
  local stage_dir="" stage_image="" configured_image=""

  preflight
  ensure_env
  ensure_host_dirs

  current_source="$(git_revision || true)"
  if [[ -n "$requested_ref" ]]; then
    require_command git
    if ! git -C "$ROOT_DIR" diff --quiet --ignore-submodules -- \
        || ! git -C "$ROOT_DIR" diff --cached --quiet --ignore-submodules --; then
      echo "error: version-pinned update requires a clean tracked Git worktree" >&2
      echo "commit or stash source changes first; untracked runtime files are ignored" >&2
      return 1
    fi

    target_revision="$(resolve_git_revision "$requested_ref" || true)"
    if ! valid_revision "$target_revision"; then
      echo "error: update version/ref is not available in this Git clone: $requested_ref" >&2
      echo "fetch the desired release/ref first, then retry" >&2
      return 1
    fi

    stage_dir="$(mktemp -d "${TMPDIR:-/tmp}/zero-nvr-update.XXXXXX")"
    rmdir "$stage_dir"
    stage_image="zero-nvr:update-stage-$(printf '%s' "$target_revision" | cut -c1-12)"

    cleanup_update_stage() {
      if [[ -n "${stage_dir:-}" ]]; then
        git -C "$ROOT_DIR" worktree remove --force "$stage_dir" >/dev/null 2>&1 || true
        rm -rf "$stage_dir" >/dev/null 2>&1 || true
      fi
      if [[ -n "${stage_image:-}" ]]; then
        docker image rm "$stage_image" >/dev/null 2>&1 || true
      fi
    }
    trap cleanup_update_stage EXIT

    echo "Staging update revision $target_revision..."
    git -C "$ROOT_DIR" worktree add --detach "$stage_dir" "$target_revision" >/dev/null
    cp "$ENV_FILE" "$stage_dir/.env"
    chmod 600 "$stage_dir/.env"

    COMPOSE_PROFILES="$(env_get COMPOSE_PROFILES "")" \
      docker compose \
        --env-file "$ENV_FILE" \
        -f "$stage_dir/docker-compose.yml" \
        config --quiet

    docker build --pull \
      --file "$stage_dir/backend/Dockerfile" \
      --tag "$stage_image" \
      "$stage_dir"
  else
    target_revision="$current_source"
  fi
  previous_revision="$(deployment_state_get DEPLOYED_REVISION)"
  previous_rollback_revision="$(deployment_state_get ROLLBACK_REVISION)"
  previous_rollback_snapshot="$(deployment_state_get ROLLBACK_SNAPSHOT_REL)"
  pending_target="$(deployment_state_get PENDING_TARGET_REVISION)"

  if valid_revision "$pending_target"; then
    echo "error: a previous update is still marked pending: $pending_target" >&2
    echo "run ./deploy.sh rollback before retrying update" >&2
    return 1
  fi

  SAFETY_SNAPSHOT_REL=""
  if [[ -n "$(compose images -q zero-nvr 2>/dev/null || true)" ]]; then
    echo "Creating pre-upgrade database safety snapshot..."
    create_local_safety_snapshot

    environment="$(env_get ZERO_NVR_ENVIRONMENT "production")"
    if [[ "$environment" == "production" ]]; then
      echo "Creating verified pre-upgrade restic backup..."
      backup_args=(
        python -m app.cli pre-upgrade-backup
      )
      if [[ -n "$backup_policy" ]]; then
        backup_args+=(--policy "$backup_policy")
      fi
      compose run --rm --no-deps zero-nvr         "${backup_args[@]}"
    else
      echo "WARN ZERO_NVR_ENVIRONMENT=$environment; verified restic pre-upgrade backup is not required" >&2
    fi
  else
    echo "WARN zero-nvr image is not installed; no pre-upgrade safety snapshot created" >&2
  fi

  if valid_revision "$target_revision" \
    && valid_revision "$previous_revision" \
    && [[ "$previous_revision" != "$target_revision" ]] \
    && [[ -n "$SAFETY_SNAPSHOT_REL" ]]; then
    write_deployment_state \
      "$previous_revision" \
      "$previous_rollback_revision" \
      "$previous_rollback_snapshot" \
      "$target_revision" \
      "$previous_revision" \
      "$SAFETY_SNAPSHOT_REL"
  fi

  if [[ -n "$requested_ref" ]]; then
    echo "Switching source checkout to pinned revision $target_revision..."
    git -C "$ROOT_DIR" checkout --detach "$target_revision"
    configured_image="$(env_get ZERO_NVR_IMAGE "zero-nvr:local")"
    docker tag "$stage_image" "$configured_image"
  fi

  prepare_zlm
  if [[ -z "$requested_ref" ]]; then
    compose build --pull zero-nvr
  fi

  echo "Stopping zero-nvr control plane for explicit schema migration; ZLMediaKit remains running..."
  compose stop zero-nvr-worker zero-nvr >/dev/null 2>&1 || true

  if ! "$SCRIPT_DIR/migrate.sh"; then
    echo "error: database migration failed; deployment remains pending" >&2
    echo "run ./deploy.sh rollback to restore the recorded pre-upgrade safety point" >&2
    return 1
  fi

  compose up -d --wait --wait-timeout 180
  ZERO_NVR_ENV_FILE="$ENV_FILE" "$SCRIPT_DIR/check.sh"

  if valid_revision "$target_revision"; then
    if valid_revision "$previous_revision" \
      && [[ "$previous_revision" != "$target_revision" ]] \
      && [[ -n "$SAFETY_SNAPSHOT_REL" ]]; then
      rollback_revision="$previous_revision"
      rollback_snapshot="$SAFETY_SNAPSHOT_REL"
    elif [[ "$previous_revision" == "$target_revision" ]]; then
      rollback_revision="$previous_rollback_revision"
      rollback_snapshot="$previous_rollback_snapshot"
    else
      echo "WARN previous deployment revision is unknown; this update cannot be automatically rolled back by version" >&2
    fi

    write_deployment_state \
      "$target_revision" \
      "$rollback_revision" \
      "$rollback_snapshot"
  else
    echo "WARN target Git revision unavailable; deployment state was not advanced" >&2
  fi
}

command="${1:-install}"
shift || true

case "$command" in
  install)
    install_stack
    ;;
  update)
    backup_policy=""
    target_ref=""
    while [[ "$#" -gt 0 ]]; do
      case "$1" in
        --backup-policy)
          shift
          backup_policy="${1:-}"
          if [[ -z "$backup_policy" ]]; then
            echo "error: --backup-policy requires an id or name" >&2
            exit 2
          fi
          ;;
        -*)
          echo "error: unknown update option: $1" >&2
          exit 2
          ;;
        *)
          if [[ -n "$target_ref" ]]; then
            echo "error: update accepts at most one version/ref" >&2
            exit 2
          fi
          target_ref="$1"
          ;;
      esac
      shift
    done
    update_stack "$backup_policy" "$target_ref"
    ;;
  rollback)
    bash "$SCRIPT_DIR/rollback.sh" "$@"
    ;;
  status)
    ensure_env
    compose ps
    if [[ -f "$(deployment_state_file)" ]]; then
      echo
      echo "Deployment state:"
      echo "  deployed: $(deployment_state_get DEPLOYED_REVISION)"
      echo "  rollback: $(deployment_state_get ROLLBACK_REVISION)"
      pending="$(deployment_state_get PENDING_TARGET_REVISION)"
      if [[ -n "$pending" ]]; then
        echo "  pending:  $pending"
      fi
    fi
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
    if [[ ! -f "$ENV_FILE" ]]; then
      echo "error: restore requires the original RecoveryKit .env; refusing to generate a new master key" >&2
      exit 1
    fi
    if [[ ${#$(env_get ZERO_NVR_SECRET_KEY)} -lt 32 ]]; then
      echo "error: original ZERO_NVR_SECRET_KEY is missing from .env" >&2
      exit 1
    fi
    ensure_host_dirs
    build_backend
    if [[ "${1:-}" != "list" ]]; then
      for key in ZERO_NVR_ZLM_API_SECRET ZERO_NVR_ZLM_HOOK_SECRET; do
        if [[ ${#$(env_get "$key")} -lt 32 ]]; then
          echo "error: RecoveryKit .env is missing $key" >&2
          exit 1
        fi
      done
      prepare_zlm
    fi
    "$SCRIPT_DIR/restore.sh" "$@"
    ;;
  recovery-kit)
    subcommand="${1:-}"
    shift || true
    case "$subcommand" in
      export)
        ensure_env
        output="${1:-$ROOT_DIR/recovery-kit}"
        policy="${2:-}"
        "$SCRIPT_DIR/recovery-kit.sh" "$output" "$policy"
        ;;
      *)
        echo "error: unsupported recovery-kit command: $subcommand" >&2
        usage >&2
        exit 2
        ;;
    esac
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
