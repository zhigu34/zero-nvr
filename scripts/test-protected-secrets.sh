#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

export ZERO_NVR_ENV_FILE="$tmp/.env"
# shellcheck source=scripts/lib.sh
. "$ROOT_DIR/scripts/lib.sh"

data_root="$tmp/data"
mkdir -p "$data_root/bootstrap-secrets"

cat > "$ZERO_NVR_ENV_FILE" <<EOF
ZERO_NVR_DATA_PATH=$data_root
ZERO_NVR_ZLM_API_SECRET=direct-secret-value
ZERO_NVR_ZLM_API_SECRET_FILE=
EOF

[[ "$(protected_env_get ZERO_NVR_ZLM_API_SECRET)" == "direct-secret-value" ]]

printf '%s\n' "file-secret-value" > "$data_root/bootstrap-secrets/zlm-api"
cat > "$ZERO_NVR_ENV_FILE" <<EOF
ZERO_NVR_DATA_PATH=$data_root
ZERO_NVR_ZLM_API_SECRET=
ZERO_NVR_ZLM_API_SECRET_FILE=/var/lib/zero-nvr/bootstrap-secrets/zlm-api
EOF

[[ "$(protected_env_get ZERO_NVR_ZLM_API_SECRET)" == "file-secret-value" ]]

cat > "$ZERO_NVR_ENV_FILE" <<EOF
ZERO_NVR_DATA_PATH=$data_root
ZERO_NVR_ZLM_API_SECRET=direct-secret-value
ZERO_NVR_ZLM_API_SECRET_FILE=/var/lib/zero-nvr/bootstrap-secrets/zlm-api
EOF

if protected_env_get ZERO_NVR_ZLM_API_SECRET >/dev/null 2>&1; then
  echo "error: protected_env_get accepted direct + file configuration" >&2
  exit 1
fi

cat > "$ZERO_NVR_ENV_FILE" <<EOF
ZERO_NVR_DATA_PATH=$data_root
ZERO_NVR_ZLM_API_SECRET=
ZERO_NVR_ZLM_API_SECRET_FILE=/var/lib/zero-nvr/bootstrap-secrets/missing
EOF

if protected_env_get ZERO_NVR_ZLM_API_SECRET >/dev/null 2>&1; then
  echo "error: protected_env_get accepted a missing file" >&2
  exit 1
fi

printf 'first-line\nsecond-line\n' > "$data_root/bootstrap-secrets/multiline"
cat > "$ZERO_NVR_ENV_FILE" <<EOF
ZERO_NVR_DATA_PATH=$data_root
ZERO_NVR_ZLM_API_SECRET=
ZERO_NVR_ZLM_API_SECRET_FILE=/var/lib/zero-nvr/bootstrap-secrets/multiline
EOF

if protected_env_get ZERO_NVR_ZLM_API_SECRET >/dev/null 2>&1; then
  echo "error: protected_env_get accepted a multiline file" >&2
  exit 1
fi

cat > "$ZERO_NVR_ENV_FILE" <<EOF
ZERO_NVR_DATA_PATH=$data_root
ZERO_NVR_ZLM_API_SECRET=
ZERO_NVR_ZLM_API_SECRET_FILE=
EOF

[[ "$(protected_env_get ZERO_NVR_ZLM_API_SECRET fallback-secret)" == "fallback-secret" ]]

printf '%s\n' "m"$(printf '%039d' 0 | tr '0' 'm') > "$data_root/bootstrap-secrets/master"
printf '%s\n' "z"$(printf '%039d' 0 | tr '0' 'z') > "$data_root/bootstrap-secrets/zlm-api"

cat > "$ZERO_NVR_ENV_FILE" <<EOF
ZERO_NVR_DATA_PATH=$data_root
ZERO_NVR_SECRET_KEY=
ZERO_NVR_SECRET_KEY_FILE=/var/lib/zero-nvr/bootstrap-secrets/master
ZERO_NVR_ZLM_API_SECRET=
ZERO_NVR_ZLM_API_SECRET_FILE=/var/lib/zero-nvr/bootstrap-secrets/zlm-api
EOF

fake_bin="$tmp/fake-bin"
mkdir -p "$fake_bin"
cat > "$fake_bin/docker" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" == *"python -m app.cli recovery-env"* ]]; then
  printf '%s\n' \
    'RESTIC_REPOSITORY=/backup/repository' \
    'RESTIC_PASSWORD=recovery-password'
  exit 0
fi
echo "unexpected docker invocation: $*" >&2
exit 1
EOF
chmod +x "$fake_bin/docker"

PATH="$fake_bin:$PATH" \
ZERO_NVR_ENV_FILE="$ZERO_NVR_ENV_FILE" \
  bash "$ROOT_DIR/scripts/recovery-kit.sh" "$tmp/recovery-kit" >/dev/null

grep -Fxq \
  "ZERO_NVR_SECRET_KEY=$(cat "$data_root/bootstrap-secrets/master")" \
  "$tmp/recovery-kit/zero-nvr.env"
grep -Fxq "ZERO_NVR_SECRET_KEY_FILE=" "$tmp/recovery-kit/zero-nvr.env"
grep -Fxq \
  "ZERO_NVR_ZLM_API_SECRET=$(cat "$data_root/bootstrap-secrets/zlm-api")" \
  "$tmp/recovery-kit/zero-nvr.env"
grep -Fxq "ZERO_NVR_ZLM_API_SECRET_FILE=" "$tmp/recovery-kit/zero-nvr.env"
grep -Fxq "RESTIC_REPOSITORY=/backup/repository" "$tmp/recovery-kit/recovery.env"

grep -Fxq "ZERO_NVR_SECRET_KEY=" "$ZERO_NVR_ENV_FILE"
grep -Fxq \
  "ZERO_NVR_SECRET_KEY_FILE=/var/lib/zero-nvr/bootstrap-secrets/master" \
  "$ZERO_NVR_ENV_FILE"
grep -Fxq "ZERO_NVR_ZLM_API_SECRET=" "$ZERO_NVR_ENV_FILE"
grep -Fxq \
  "ZERO_NVR_ZLM_API_SECRET_FILE=/var/lib/zero-nvr/bootstrap-secrets/zlm-api" \
  "$ZERO_NVR_ENV_FILE"

echo "protected environment secret tests passed"
