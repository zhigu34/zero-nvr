#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

setup_repo() {
  local repo_dir="$1"
  mkdir -p \
    "$repo_dir/scripts" \
    "$repo_dir/backend" \
    "$repo_dir/fake-bin" \
    "$repo_dir/data/safety-backups/recorded" \
    "$repo_dir/data/safety-backups/pre" \
    "$repo_dir/recordings"

  cp "$ROOT_DIR/scripts/lib.sh" "$repo_dir/scripts/lib.sh"
  cp "$ROOT_DIR/scripts/deployment-state.sh" "$repo_dir/scripts/deployment-state.sh"
  cp "$ROOT_DIR/scripts/artifact-pins.sh" "$repo_dir/scripts/artifact-pins.sh"
  cp "$ROOT_DIR/scripts/release-manifest.sh" "$repo_dir/scripts/release-manifest.sh"
  cp "$ROOT_DIR/scripts/rollback.sh" "$repo_dir/scripts/rollback.sh"
  chmod +x "$repo_dir/scripts/rollback.sh"

  cat > "$repo_dir/scripts/check.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
echo "doctor: healthy"
EOF
  chmod +x "$repo_dir/scripts/check.sh"

  cat > "$repo_dir/fake-bin/docker" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

args="$*"

if [[ "$args" == "compose version" ]]; then
  exit 0
fi
if [[ "$args" == "info" ]]; then
  exit 0
fi
if [[ "$args" == *" ps -q zero-nvr"* ]]; then
  echo "fake-zero-nvr-container"
  exit 0
fi
if [[ "$args" == "container inspect fake-zero-nvr-container --format {{.Image}}" ]]; then
  printf 'sha256:%064d\n' 2
  exit 0
fi
if [[ "$args" == "image inspect "* ]]; then
  exit 0
fi
if [[ "$args" == *"python -m app.cli safety-snapshot"* ]]; then
  printf '%s\n' '{"safety_snapshot": "/var/lib/zero-nvr/safety-backups/pre/database.sqlite3", "database_engine": "sqlite", "size_bytes": 128}'
  exit 0
fi

exit 0
EOF
  chmod +x "$repo_dir/fake-bin/docker"

  cat > "$repo_dir/docker-compose.yml" <<'EOF'
services:
  zero-nvr:
    image: zero-nvr:test
EOF

  cat > "$repo_dir/backend/Dockerfile" <<'EOF'
FROM scratch
EOF

  printf 'recording-bytes-must-survive\n' > "$repo_dir/recordings/keep.mp4"
  printf 'recorded-db-snapshot\n' > "$repo_dir/data/safety-backups/recorded/database.sqlite3"
  printf 'pre-rollback-db-snapshot\n' > "$repo_dir/data/safety-backups/pre/database.sqlite3"

  git -C "$repo_dir" init -q
  git -C "$repo_dir" config user.email "rollback-test@example.invalid"
  git -C "$repo_dir" config user.name "zero-nvr rollback test"
  git -C "$repo_dir" add scripts docker-compose.yml backend
  git -C "$repo_dir" commit -qm "revision A"
  REV_A="$(git -C "$repo_dir" rev-parse HEAD)"

  printf 'revision-b\n' > "$repo_dir/revision.txt"
  git -C "$repo_dir" add revision.txt
  git -C "$repo_dir" commit -qm "revision B"
  REV_B="$(git -C "$repo_dir" rev-parse HEAD)"

  cat > "$repo_dir/.env" <<EOF
ZERO_NVR_DATA_PATH=$repo_dir/data
ZERO_NVR_RECORDINGS_PATH=$repo_dir/recordings
ZERO_NVR_IMAGE=zero-nvr:test
COMPOSE_PROFILES=
EOF

  RECORDING_HASH="$(
    sha256sum "$repo_dir/recordings/keep.mp4" |
      awk '{print $1}'
  )"
}

assert_recording_unchanged() {
  local repo_dir="$1"
  local after
  after="$(
    sha256sum "$repo_dir/recordings/keep.mp4" |
      awk '{print $1}'
  )"
  [[ "$after" == "$RECORDING_HASH" ]]
}

run_normal_rollback() {
  local repo_dir="$tmp/normal"
  mkdir -p "$repo_dir"
  setup_repo "$repo_dir"

  mkdir -p "$repo_dir/data/deployment"
  cat > "$repo_dir/data/deployment/state.env" <<EOF
DEPLOYED_REVISION=$REV_B
ROLLBACK_REVISION=$REV_A
ROLLBACK_SNAPSHOT_REL=safety-backups/recorded/database.sqlite3
PENDING_TARGET_REVISION=
PENDING_PREVIOUS_REVISION=
PENDING_SNAPSHOT_REL=
ROLLBACK_IMAGE_REF=zero-nvr:pin-rollback-${REV_A:0:12}
PENDING_PREVIOUS_IMAGE_REF=
UPDATED_AT=2026-09-20T00:00:00Z
EOF

  PATH="$repo_dir/fake-bin:$PATH" \
  ZERO_NVR_ENV_FILE="$repo_dir/.env" \
    "$repo_dir/scripts/rollback.sh" \
      > "$repo_dir/rollback.log"

  [[ "$(git -C "$repo_dir" rev-parse HEAD)" == "$REV_A" ]]
  grep -Fxq "DEPLOYED_REVISION=$REV_A" \
    "$repo_dir/data/deployment/state.env"
  grep -Fxq "ROLLBACK_REVISION=$REV_B" \
    "$repo_dir/data/deployment/state.env"
  grep -Fxq \
    "ROLLBACK_SNAPSHOT_REL=safety-backups/pre/database.sqlite3" \
    "$repo_dir/data/deployment/state.env"
  grep -Fq "Rollback completed:" "$repo_dir/rollback.log"
  grep -Fq "Recording media was not modified." "$repo_dir/rollback.log"
  assert_recording_unchanged "$repo_dir"
}

run_failed_update_recovery() {
  local repo_dir="$tmp/failed-update"
  mkdir -p "$repo_dir"
  setup_repo "$repo_dir"

  mkdir -p "$repo_dir/data/deployment"
  cat > "$repo_dir/data/deployment/state.env" <<EOF
DEPLOYED_REVISION=$REV_A
ROLLBACK_REVISION=
ROLLBACK_SNAPSHOT_REL=
PENDING_TARGET_REVISION=$REV_B
PENDING_PREVIOUS_REVISION=$REV_A
PENDING_SNAPSHOT_REL=safety-backups/recorded/database.sqlite3
ROLLBACK_IMAGE_REF=
PENDING_PREVIOUS_IMAGE_REF=zero-nvr:pin-pending-${REV_A:0:12}
UPDATED_AT=2026-09-20T00:00:00Z
EOF

  PATH="$repo_dir/fake-bin:$PATH" \
  ZERO_NVR_ENV_FILE="$repo_dir/.env" \
    "$repo_dir/scripts/rollback.sh" \
      > "$repo_dir/rollback.log"

  [[ "$(git -C "$repo_dir" rev-parse HEAD)" == "$REV_A" ]]
  grep -Fxq "DEPLOYED_REVISION=$REV_A" \
    "$repo_dir/data/deployment/state.env"
  grep -Fxq "ROLLBACK_REVISION=" \
    "$repo_dir/data/deployment/state.env"
  grep -Fxq "PENDING_TARGET_REVISION=" \
    "$repo_dir/data/deployment/state.env"
  grep -Fq "Failed update recovered:" "$repo_dir/rollback.log"
  grep -Fq "Recording media was not modified." "$repo_dir/rollback.log"
  assert_recording_unchanged "$repo_dir"
}

run_requested_revision_guard() {
  local repo_dir="$tmp/requested-guard"
  mkdir -p "$repo_dir"
  setup_repo "$repo_dir"

  mkdir -p "$repo_dir/data/deployment"
  cat > "$repo_dir/data/deployment/state.env" <<EOF
DEPLOYED_REVISION=$REV_B
ROLLBACK_REVISION=$REV_A
ROLLBACK_SNAPSHOT_REL=safety-backups/recorded/database.sqlite3
PENDING_TARGET_REVISION=
PENDING_PREVIOUS_REVISION=
PENDING_SNAPSHOT_REL=
ROLLBACK_IMAGE_REF=zero-nvr:pin-rollback-${REV_A:0:12}
PENDING_PREVIOUS_IMAGE_REF=
UPDATED_AT=2026-09-20T00:00:00Z
EOF

  if PATH="$repo_dir/fake-bin:$PATH" \
    ZERO_NVR_ENV_FILE="$repo_dir/.env" \
      "$repo_dir/scripts/rollback.sh" "$REV_B" \
        > "$repo_dir/guard.log" 2>&1; then
    echo "rollback unexpectedly accepted an unrecorded target" >&2
    exit 1
  fi

  [[ "$(git -C "$repo_dir" rev-parse HEAD)" == "$REV_B" ]]
  grep -Fq \
    "requested version does not match the recorded rollback revision" \
    "$repo_dir/guard.log"
  assert_recording_unchanged "$repo_dir"
}

run_normal_rollback
run_failed_update_recovery
run_requested_revision_guard

echo "rollback: ok"
