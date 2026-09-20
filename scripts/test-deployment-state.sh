#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

cat > "$tmp/test.env" <<EOF
ZERO_NVR_DATA_PATH=$tmp/data
EOF

export ZERO_NVR_ENV_FILE="$tmp/test.env"
. "$ROOT_DIR/scripts/lib.sh"
. "$ROOT_DIR/scripts/deployment-state.sh"

dep="1111111111111111111111111111111111111111"
prev="2222222222222222222222222222222222222222"
pending="3333333333333333333333333333333333333333"
snap="safety-backups/one/database.sqlite3"
pending_snap="safety-backups/two/database.sqlite3"

write_deployment_state \
  "$dep" \
  "$prev" \
  "$snap" \
  "$pending" \
  "$dep" \
  "$pending_snap"

[[ "$(deployment_state_get DEPLOYED_REVISION)" == "$dep" ]]
[[ "$(deployment_state_get ROLLBACK_REVISION)" == "$prev" ]]
[[ "$(deployment_state_get ROLLBACK_SNAPSHOT_REL)" == "$snap" ]]
[[ "$(deployment_state_get PENDING_TARGET_REVISION)" == "$pending" ]]
[[ "$(deployment_state_get PENDING_PREVIOUS_REVISION)" == "$dep" ]]
[[ "$(deployment_state_get PENDING_SNAPSHOT_REL)" == "$pending_snap" ]]

state="$(deployment_state_file)"
mode="$(stat -c '%a' "$state")"
[[ "$mode" == "600" ]]

marker="$tmp/should-not-exist"
malicious="\$(touch \"$marker\")"
printf 'EVIL=%s\n' "$malicious" >> "$state"
value="$(deployment_state_get EVIL)"
[[ "$value" == "$malicious" ]]
[[ ! -e "$marker" ]]

write_deployment_state "$prev" "$dep" "$pending_snap"
[[ "$(deployment_state_get DEPLOYED_REVISION)" == "$prev" ]]
[[ "$(deployment_state_get ROLLBACK_REVISION)" == "$dep" ]]
[[ -z "$(deployment_state_get PENDING_TARGET_REVISION)" ]]

echo "deployment-state: ok"
