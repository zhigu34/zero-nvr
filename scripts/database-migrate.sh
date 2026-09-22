#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
. "$SCRIPT_DIR/lib.sh"
. "$SCRIPT_DIR/deployment-state.sh"
. "$SCRIPT_DIR/feature-profiles.sh"

usage() {
  cat <<'EOF'
Usage:
  scripts/database-migrate.sh <postgres|sqlite> [--managed] [--target-url-env NAME] [--backup-policy ID_OR_NAME]

PostgreSQL target selection:
  - --managed forces the zero-nvr managed PostgreSQL profile.
  - otherwise, if NAME (default ZERO_NVR_DATABASE_MIGRATION_TARGET_URL)
    is set in .env, that external PostgreSQL URL is used.
  - if no external target URL is configured, managed PostgreSQL is used.

The target URL is never printed. The source database is retained after cutover.
EOF
}

set_env_value() {
  local key="$1"
  local value="$2"
  local tmp
  if [[ "$value" == *$'\n'* || "$value" == *$'\r'* ]]; then
    echo "error: refusing multiline environment value for $key" >&2
    return 1
  fi
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

database_backend() {
  local url="$1"
  case "$url" in
    ""|sqlite:*|sqlite+*)
      printf 'sqlite'
      ;;
    postgres:*|postgresql:*|postgresql+*)
      printf 'postgresql'
      ;;
    *)
      return 1
      ;;
  esac
}

effective_source_url() {
  local configured
  configured="$(env_get ZERO_NVR_DATABASE_URL "")"
  if [[ -n "$configured" ]]; then
    printf '%s' "$configured"
  else
    printf 'sqlite:////var/lib/zero-nvr/zero-nvr.db'
  fi
}

managed_postgres_url() {
  compose run --rm --no-deps zero-nvr \
    python -c '
import os
from sqlalchemy.engine import URL
password = os.environ.get("ZERO_NVR_POSTGRES_PASSWORD", "")
if not password:
    raise SystemExit("managed PostgreSQL password is unavailable")
url = URL.create(
    "postgresql+psycopg",
    username=os.environ.get("ZERO_NVR_POSTGRES_USER", "zero_nvr"),
    password=password,
    host="postgres",
    port=5432,
    database=os.environ.get("ZERO_NVR_POSTGRES_DB", "zero_nvr"),
)
print(url.render_as_string(hide_password=False))
'
}

recover_source() {
  local original_url="$1"
  local original_previous_url="$2"
  echo "Restoring original database configuration..." >&2
  set_env_value ZERO_NVR_DATABASE_URL "$original_url"
  set_env_value ZERO_NVR_DATABASE_PREVIOUS_URL "$original_previous_url"
  compose up -d --force-recreate --wait --wait-timeout 180 \
    zero-nvr zero-nvr-worker >/dev/null 2>&1 || true
  if ZERO_NVR_ENV_FILE="$ENV_FILE" \
    "$SCRIPT_DIR/check.sh" >/dev/null 2>&1; then
    echo "Original database deployment recovered." >&2
    return 0
  fi
  echo "error: original database deployment did not recover automatically" >&2
  return 1
}

target="${1:-}"
if [[ -z "$target" ]]; then
  usage >&2
  exit 2
fi
shift

managed=false
target_url_env="ZERO_NVR_DATABASE_MIGRATION_TARGET_URL"
backup_policy=""

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --managed)
      managed=true
      ;;
    --target-url-env)
      shift
      target_url_env="${1:-}"
      if [[ -z "$target_url_env" ]]; then
        echo "error: --target-url-env requires an environment variable name" >&2
        exit 2
      fi
      ;;
    --backup-policy)
      shift
      backup_policy="${1:-}"
      if [[ -z "$backup_policy" ]]; then
        echo "error: --backup-policy requires an id or name" >&2
        exit 2
      fi
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown database migration option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

case "$target" in
  postgres|postgresql)
    target="postgresql"
    ;;
  sqlite)
    ;;
  *)
    echo "error: database target must be postgres or sqlite" >&2
    exit 2
    ;;
esac

require_command docker
docker compose version >/dev/null
docker info >/dev/null

if [[ ! -f "$ENV_FILE" ]]; then
  echo "error: database migration requires an existing .env" >&2
  exit 1
fi

source_configured_url="$(env_get ZERO_NVR_DATABASE_URL "")"
source_previous_url="$(env_get ZERO_NVR_DATABASE_PREVIOUS_URL "")"
source_url="$(effective_source_url)"
source_backend="$(database_backend "$source_url" || true)"
if [[ -z "$source_backend" ]]; then
  echo "error: active database URL uses an unsupported backend" >&2
  exit 1
fi
if [[ "$source_backend" == "$target" ]]; then
  echo "error: active database is already $target" >&2
  exit 1
fi

if [[ -z "$(compose images -q zero-nvr 2>/dev/null || true)" ]]; then
  echo "error: zero-nvr must be installed before database migration" >&2
  exit 1
fi

target_url=""
target_description=""
if [[ "$target" == "postgresql" ]]; then
  external_url="$(env_get "$target_url_env" "")"
  if [[ "$managed" == true || -z "$external_url" ]]; then
    echo "Preparing managed PostgreSQL..."
    "$ROOT_DIR/deploy.sh" feature enable postgres
    target_url="$(managed_postgres_url)"
    target_description="managed PostgreSQL"
  else
    target_url="$external_url"
    target_description="external PostgreSQL"
  fi
else
  migration_dir="$(deployment_data_dir)/database-migrations"
  mkdir -p "$migration_dir"
  chmod 700 "$migration_dir"
  stamp="$(date -u +%Y%m%dT%H%M%S)"
  relative="database-migrations/zero-nvr-$stamp.db"
  host_target="$(deployment_data_dir)/$relative"
  if [[ -e "$host_target" ]]; then
    echo "error: SQLite migration target already exists: $host_target" >&2
    exit 1
  fi
  target_url="sqlite:////var/lib/zero-nvr/$relative"
  target_description="new retained SQLite database"
fi

target_backend="$(database_backend "$target_url" || true)"
if [[ "$target_backend" != "$target" ]]; then
  echo "error: selected migration target URL is not a $target database" >&2
  exit 1
fi

echo "Database migration: $source_backend -> $target_description"

environment="$(env_get ZERO_NVR_ENVIRONMENT "production")"
if [[ "$environment" == "production" ]]; then
  echo "Creating verified pre-database-migration restic backup..."
  backup_args=(
    python -m app.cli
    pre-database-migration-backup
  )
  if [[ -n "$backup_policy" ]]; then
    backup_args+=(--policy "$backup_policy")
  fi
  compose run --rm --no-deps zero-nvr \
    "${backup_args[@]}"
else
  echo "WARN ZERO_NVR_ENVIRONMENT=$environment; verified restic backup is not required" >&2
fi

echo "Stopping zero-nvr API and worker; ZLMediaKit remains running..."
compose stop zero-nvr-worker zero-nvr >/dev/null 2>&1 || true

echo "Creating quiesced local database safety snapshot..."
if ! create_local_safety_snapshot; then
  echo "error: local database safety snapshot failed; restoring source services" >&2
  recover_source \
    "$source_configured_url" \
    "$source_previous_url" || true
  exit 1
fi
local_snapshot="$SAFETY_SNAPSHOT_REL"

transfer_failed=false
if ! ZERO_NVR_DATABASE_MIGRATION_TARGET_URL="$target_url" \
  compose run --rm --no-deps \
    -e ZERO_NVR_DATABASE_MIGRATION_TARGET_URL \
    zero-nvr \
    python -m app.cli database-transfer; then
  transfer_failed=true
fi

if [[ "$transfer_failed" == true ]]; then
  echo "error: database transfer failed; active database configuration was not changed" >&2
  recover_source \
    "$source_configured_url" \
    "$source_previous_url" || true
  echo "Local source safety snapshot retained: $(deployment_data_dir)/$local_snapshot" >&2
  exit 1
fi

echo "Switching zero-nvr database configuration..."
set_env_value ZERO_NVR_DATABASE_PREVIOUS_URL "$source_url"
set_env_value ZERO_NVR_DATABASE_URL "$target_url"

cutover_ok=true
if ! compose up -d --force-recreate --wait --wait-timeout 180 \
    zero-nvr zero-nvr-worker; then
  cutover_ok=false
elif ! ZERO_NVR_ENV_FILE="$ENV_FILE" \
  "$SCRIPT_DIR/check.sh"; then
  cutover_ok=false
fi

if [[ "$cutover_ok" != true ]]; then
  echo "error: target database cutover failed" >&2
  recover_source \
    "$source_configured_url" \
    "$source_previous_url" || true
  echo "Transferred target database was retained for diagnosis." >&2
  echo "Local source safety snapshot retained: $(deployment_data_dir)/$local_snapshot" >&2
  exit 1
fi

echo "Database migration completed: $source_backend -> $target"
echo "Previous database retained for rollback grace period."
echo "Recording media was not modified."
