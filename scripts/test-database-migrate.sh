#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

TARGET_URL="postgresql://zero_nvr:secret@db.example.test:5432/zero_nvr"
LEGACY_PREVIOUS_URL="postgresql://legacy:secret@legacy.example.test:5432/zero_nvr"

setup_stage() {
  local name="$1"
  local stage="$TMP_DIR/$name"
  local fake_bin="$stage/fake-bin"

  mkdir -p "$stage/scripts" "$stage/data/safety-backups/pre" "$fake_bin"

  cp "$ROOT_DIR/scripts/lib.sh" "$stage/scripts/lib.sh"
  cp "$ROOT_DIR/scripts/deployment-state.sh" "$stage/scripts/deployment-state.sh"
  cp "$ROOT_DIR/scripts/feature-profiles.sh" "$stage/scripts/feature-profiles.sh"
  cp "$ROOT_DIR/scripts/database-migrate.sh" "$stage/scripts/database-migrate.sh"

  cat > "$stage/scripts/check.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
echo "doctor: healthy"
EOF
  chmod +x "$stage/scripts/check.sh" "$stage/scripts/database-migrate.sh"

  cat > "$stage/docker-compose.yml" <<'EOF'
services:
  zero-nvr:
    image: zero-nvr:test
  zero-nvr-worker:
    image: zero-nvr:test
EOF

  printf 'consistent-sqlite-snapshot\n' > "$stage/data/safety-backups/pre/database.sqlite3"
  printf 'consistent-postgresql-snapshot\n' > "$stage/data/safety-backups/pre/database.pgcustom"

  cat > "$stage/.env" <<EOF
ZERO_NVR_DATA_PATH=$stage/data
ZERO_NVR_DATABASE_URL=
ZERO_NVR_DATABASE_PREVIOUS_URL=$LEGACY_PREVIOUS_URL
ZERO_NVR_DATABASE_MIGRATION_TARGET_URL=$TARGET_URL
ZERO_NVR_ENVIRONMENT=production
COMPOSE_PROFILES=
EOF

  cat > "$fake_bin/docker" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

: "${FAKE_DOCKER_LOG:?}"
: "${FAKE_DOCKER_STATE:?}"
printf '%s\n' "$*" >> "$FAKE_DOCKER_LOG"

args="$*"

case "$args" in
  "compose version"|"info")
    exit 0
    ;;
esac

if [[ "$args" == *" images -q zero-nvr"* ]]; then
  printf '%s\n' "sha256:zero-nvr-test"
  exit 0
fi

if [[ "$args" == *"python -m app.cli safety-snapshot"* ]]; then
  if [[ "${FAKE_SNAPSHOT_FAIL:-0}" == "1" ]]; then
    exit 1
  fi
  if [[ "${FAKE_SOURCE_BACKEND:-sqlite}" == "postgresql" ]]; then
    printf '%s\n' '{"safety_snapshot": "/var/lib/zero-nvr/safety-backups/pre/database.pgcustom", "database_engine": "postgresql", "size_bytes": 256}'
  else
    printf '%s\n' '{"safety_snapshot": "/var/lib/zero-nvr/safety-backups/pre/database.sqlite3", "database_engine": "sqlite", "size_bytes": 128}'
  fi
  exit 0
fi

if [[ "$args" == *"python -m app.cli database-preflight-sqlite"* ]]; then
  if [[ "${FAKE_PREFLIGHT_FAIL:-0}" == "1" ]]; then
    printf '%s\n' '{"allowed": false, "blockers": ["sqlite_preflight_target_disk_space_insufficient"]}'
    exit 1
  fi
  if [[ "$args" != *"--confirm-workload"* ]]; then
    printf '%s\n' '{"allowed": false, "blockers": ["sqlite_preflight_workload_confirmation_required"]}'
    exit 1
  fi
  printf '%s\n' '{"allowed": true, "blockers": [], "recent_write_rows": 12}'
  exit 0
fi

if [[ "$args" == *"python -m app.cli pre-database-migration-backup"* ]]; then
  printf '%s\n' '{"state": "COMPLETED", "verification_state": "PASSED", "restic_snapshot_id": "restic-test"}'
  exit 0
fi

if [[ "$args" == *"python -m app.cli database-transfer"* ]]; then
  if [[ "${FAKE_TRANSFER_FAIL:-0}" == "1" ]]; then
    exit 1
  fi
  printf '%s\n' '{"transferred": true, "source_backend": "sqlite", "target_backend": "postgresql"}'
  exit 0
fi

if [[ "$args" == *" stop zero-nvr-worker zero-nvr"* ]]; then
  exit 0
fi

if [[ "$args" == *" up -d --force-recreate --wait --wait-timeout 180 zero-nvr zero-nvr-worker"* ]]; then
  count=0
  if [[ -f "$FAKE_DOCKER_STATE" ]]; then
    count="$(cat "$FAKE_DOCKER_STATE")"
  fi
  count=$((count + 1))
  printf '%s\n' "$count" > "$FAKE_DOCKER_STATE"
  if [[ "${FAKE_CUTOVER_FAIL:-0}" == "1" && "$count" -eq 1 ]]; then
    exit 1
  fi
  exit 0
fi

if [[ "$args" == *" up -d --wait --wait-timeout 180 zero-nvr zero-nvr-worker"* ]]; then
  exit 0
fi

echo "unexpected fake docker invocation: $args" >&2
exit 1
EOF
  chmod +x "$fake_bin/docker"

  printf '%s' "$stage"
}

env_value() {
  local env_file="$1"
  local key="$2"
  grep -E "^${key}=" "$env_file" | tail -n 1 | cut -d= -f2-
}

assert_order() {
  local log="$1"
  local first="$2"
  local second="$3"
  local first_line second_line

  first_line="$(grep -n -F "$first" "$log" | head -n 1 | cut -d: -f1)"
  second_line="$(grep -n -F "$second" "$log" | head -n 1 | cut -d: -f1)"
  [[ -n "$first_line" && -n "$second_line" ]]
  (( first_line < second_line ))
}

run_success() {
  local stage
  stage="$(setup_stage success)"

  PATH="$stage/fake-bin:$PATH" \
  FAKE_DOCKER_LOG="$stage/docker.log" \
  FAKE_DOCKER_STATE="$stage/docker.state" \
    "$stage/scripts/database-migrate.sh" postgres > "$stage/output.log" 2>&1

  [[ "$(env_value "$stage/.env" ZERO_NVR_DATABASE_URL)" == "$TARGET_URL" ]]
  [[ "$(env_value "$stage/.env" ZERO_NVR_DATABASE_PREVIOUS_URL)" == "sqlite:////var/lib/zero-nvr/zero-nvr.db" ]]

  grep -Fq "Database migration completed: sqlite -> postgresql" "$stage/output.log"
  grep -Fq "Previous database retained for rollback grace period." "$stage/output.log"

  assert_order "$stage/docker.log" "python -m app.cli pre-database-migration-backup" " stop zero-nvr-worker zero-nvr"
  assert_order "$stage/docker.log" " stop zero-nvr-worker zero-nvr" "python -m app.cli safety-snapshot"
  assert_order "$stage/docker.log" "python -m app.cli safety-snapshot" "python -m app.cli database-transfer"
}

run_snapshot_failure() {
  local stage
  stage="$(setup_stage snapshot-failure)"

  if PATH="$stage/fake-bin:$PATH" \
    FAKE_DOCKER_LOG="$stage/docker.log" \
    FAKE_DOCKER_STATE="$stage/docker.state" \
    FAKE_SNAPSHOT_FAIL=1 \
      "$stage/scripts/database-migrate.sh" postgres > "$stage/output.log" 2>&1
  then
    echo "database migration unexpectedly succeeded after snapshot failure" >&2
    exit 1
  fi

  [[ -z "$(env_value "$stage/.env" ZERO_NVR_DATABASE_URL)" ]]
  [[ "$(env_value "$stage/.env" ZERO_NVR_DATABASE_PREVIOUS_URL)" == "$LEGACY_PREVIOUS_URL" ]]

  grep -Fq \
    "local database safety snapshot failed; restoring source services" \
    "$stage/output.log"
  grep -Fq "Original database deployment recovered." "$stage/output.log"
  grep -Fq \
    " up -d --force-recreate --wait --wait-timeout 180 zero-nvr zero-nvr-worker" \
    "$stage/docker.log"
  [[ "$(cat "$stage/docker.state")" == "1" ]]
  if grep -Fq "python -m app.cli database-transfer" "$stage/docker.log"; then
    echo "database transfer ran after snapshot failure" >&2
    exit 1
  fi
}

run_transfer_failure() {
  local stage
  stage="$(setup_stage transfer-failure)"

  if PATH="$stage/fake-bin:$PATH" \
    FAKE_DOCKER_LOG="$stage/docker.log" \
    FAKE_DOCKER_STATE="$stage/docker.state" \
    FAKE_TRANSFER_FAIL=1 \
      "$stage/scripts/database-migrate.sh" postgres > "$stage/output.log" 2>&1
  then
    echo "database migration unexpectedly succeeded after transfer failure" >&2
    exit 1
  fi

  [[ -z "$(env_value "$stage/.env" ZERO_NVR_DATABASE_URL)" ]]
  [[ "$(env_value "$stage/.env" ZERO_NVR_DATABASE_PREVIOUS_URL)" == "$LEGACY_PREVIOUS_URL" ]]

  grep -Fq "database transfer failed; active database configuration was not changed" "$stage/output.log"
  grep -Fq "Original database deployment recovered." "$stage/output.log"
  grep -Fq "Local source safety snapshot retained:" "$stage/output.log"
  [[ "$(cat "$stage/docker.state")" == "1" ]]
}

run_cutover_failure() {
  local stage
  stage="$(setup_stage cutover-failure)"

  if PATH="$stage/fake-bin:$PATH" \
    FAKE_DOCKER_LOG="$stage/docker.log" \
    FAKE_DOCKER_STATE="$stage/docker.state" \
    FAKE_CUTOVER_FAIL=1 \
      "$stage/scripts/database-migrate.sh" postgres > "$stage/output.log" 2>&1
  then
    echo "database migration unexpectedly succeeded after cutover failure" >&2
    exit 1
  fi

  [[ -z "$(env_value "$stage/.env" ZERO_NVR_DATABASE_URL)" ]]
  [[ "$(env_value "$stage/.env" ZERO_NVR_DATABASE_PREVIOUS_URL)" == "$LEGACY_PREVIOUS_URL" ]]

  grep -Fq "target database cutover failed" "$stage/output.log"
  grep -Fq "Original database deployment recovered." "$stage/output.log"
  grep -Fq "Transferred target database was retained for diagnosis." "$stage/output.log"
  [[ "$(cat "$stage/docker.state")" == "2" ]]
}

prepare_postgresql_source() {
  local stage="$1"
  cat > "$stage/.env" <<EOF
ZERO_NVR_DATA_PATH=$stage/data
ZERO_NVR_DATABASE_URL=$TARGET_URL
ZERO_NVR_DATABASE_PREVIOUS_URL=
ZERO_NVR_DATABASE_MIGRATION_TARGET_URL=
ZERO_NVR_ENVIRONMENT=production
COMPOSE_PROFILES=
EOF
}

run_sqlite_preflight_requires_confirmation() {
  local stage
  stage="$(setup_stage sqlite-unconfirmed)"
  prepare_postgresql_source "$stage"

  if PATH="$stage/fake-bin:$PATH" \
    FAKE_DOCKER_LOG="$stage/docker.log" \
    FAKE_DOCKER_STATE="$stage/docker.state" \
    FAKE_SOURCE_BACKEND=postgresql \
      "$stage/scripts/database-migrate.sh" sqlite > "$stage/output.log" 2>&1
  then
    echo "PostgreSQL -> SQLite migration bypassed workload confirmation" >&2
    exit 1
  fi

  grep -Fq "PostgreSQL -> SQLite preflight refused migration" "$stage/output.log"
  grep -Fq "database-preflight-sqlite" "$stage/docker.log"
  if grep -Fq "pre-database-migration-backup" "$stage/docker.log"; then
    echo "backup ran after refused SQLite preflight" >&2
    exit 1
  fi
}

run_sqlite_preflight_blocks_hard_failure() {
  local stage
  stage="$(setup_stage sqlite-blocked)"
  prepare_postgresql_source "$stage"

  if PATH="$stage/fake-bin:$PATH" \
    FAKE_DOCKER_LOG="$stage/docker.log" \
    FAKE_DOCKER_STATE="$stage/docker.state" \
    FAKE_SOURCE_BACKEND=postgresql \
    FAKE_PREFLIGHT_FAIL=1 \
      "$stage/scripts/database-migrate.sh" sqlite \
        --confirm-sqlite-workload > "$stage/output.log" 2>&1
  then
    echo "PostgreSQL -> SQLite migration bypassed hard preflight blocker" >&2
    exit 1
  fi

  grep -Fq "sqlite_preflight_target_disk_space_insufficient" "$stage/output.log"
  if grep -Fq " stop zero-nvr-worker zero-nvr" "$stage/docker.log"; then
    echo "source was quiesced after refused SQLite preflight" >&2
    exit 1
  fi
}

run_sqlite_confirmed_success() {
  local stage active
  stage="$(setup_stage sqlite-confirmed)"
  prepare_postgresql_source "$stage"

  PATH="$stage/fake-bin:$PATH" \
  FAKE_DOCKER_LOG="$stage/docker.log" \
  FAKE_DOCKER_STATE="$stage/docker.state" \
  FAKE_SOURCE_BACKEND=postgresql \
    "$stage/scripts/database-migrate.sh" sqlite \
      --confirm-sqlite-workload > "$stage/output.log" 2>&1

  active="$(env_value "$stage/.env" ZERO_NVR_DATABASE_URL)"
  [[ "$active" == sqlite:////var/lib/zero-nvr/database-migrations/zero-nvr-*.db ]]
  [[ "$(env_value "$stage/.env" ZERO_NVR_DATABASE_PREVIOUS_URL)" == "$TARGET_URL" ]]

  grep -Fq '"allowed": true' "$stage/output.log"
  grep -Fq "Database migration completed: postgresql -> sqlite" "$stage/output.log"
  assert_order "$stage/docker.log" "database-preflight-sqlite --confirm-workload" "pre-database-migration-backup"
  assert_order "$stage/docker.log" " stop zero-nvr-worker zero-nvr" "python -m app.cli safety-snapshot"
  grep -Fq "database.pgcustom" "$stage/output.log"
}

run_success
run_snapshot_failure
run_transfer_failure
run_cutover_failure
run_sqlite_preflight_requires_confirmation
run_sqlite_preflight_blocks_hard_failure
run_sqlite_confirmed_success

echo "database migration: ok"
