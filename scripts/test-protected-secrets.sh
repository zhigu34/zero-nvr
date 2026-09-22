#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

export ZERO_NVR_ENV_FILE="$tmp/.env"
# shellcheck source=scripts/lib.sh
. "$ROOT_DIR/scripts/lib.sh"

data_root="$tmp/data"
mkdir -p "$data_root/bootstrap"

cat > "$ZERO_NVR_ENV_FILE" <<EOF
ZERO_NVR_DATA_PATH=$data_root
ZERO_NVR_ZLM_API_SECRET=direct-secret-value
ZERO_NVR_ZLM_API_SECRET_FILE=
EOF

[[ "$(protected_env_get ZERO_NVR_ZLM_API_SECRET)" == "direct-secret-value" ]]

printf '%s\n' "file-secret-value" > "$data_root/bootstrap/zlm-api"
cat > "$ZERO_NVR_ENV_FILE" <<EOF
ZERO_NVR_DATA_PATH=$data_root
ZERO_NVR_ZLM_API_SECRET=
ZERO_NVR_ZLM_API_SECRET_FILE=/var/lib/zero-nvr/bootstrap/zlm-api
EOF

[[ "$(protected_env_get ZERO_NVR_ZLM_API_SECRET)" == "file-secret-value" ]]

cat > "$ZERO_NVR_ENV_FILE" <<EOF
ZERO_NVR_DATA_PATH=$data_root
ZERO_NVR_ZLM_API_SECRET=direct-secret-value
ZERO_NVR_ZLM_API_SECRET_FILE=/var/lib/zero-nvr/bootstrap/zlm-api
EOF

if protected_env_get ZERO_NVR_ZLM_API_SECRET >/dev/null 2>&1; then
  echo "error: protected_env_get accepted direct + file configuration" >&2
  exit 1
fi

cat > "$ZERO_NVR_ENV_FILE" <<EOF
ZERO_NVR_DATA_PATH=$data_root
ZERO_NVR_ZLM_API_SECRET=
ZERO_NVR_ZLM_API_SECRET_FILE=/var/lib/zero-nvr/bootstrap/missing
EOF

if protected_env_get ZERO_NVR_ZLM_API_SECRET >/dev/null 2>&1; then
  echo "error: protected_env_get accepted a missing file" >&2
  exit 1
fi

cat > "$ZERO_NVR_ENV_FILE" <<EOF
ZERO_NVR_DATA_PATH=$data_root
ZERO_NVR_ZLM_API_SECRET=
ZERO_NVR_ZLM_API_SECRET_FILE=
EOF

[[ "$(protected_env_get ZERO_NVR_ZLM_API_SECRET fallback-secret)" == "fallback-secret" ]]

echo "protected environment secret tests passed"
