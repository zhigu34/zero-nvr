#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

ENV_FILE="$TMP_DIR/.env"
cp "$ROOT_DIR/.env.example" "$ENV_FILE"

env_get() {
  local key="$1" fallback="${2:-}" line
  line="$(grep -E "^${key}=" "$ENV_FILE" | tail -n 1 || true)"
  if [[ -z "$line" ]]; then
    printf '%s' "$fallback"
  else
    printf '%s' "${line#*=}"
  fi
}

set_env_value() {
  local key="$1" value="$2" tmp
  tmp="$TMP_DIR/env.tmp"
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
  mv "$tmp" "$ENV_FILE"
}

. "$ROOT_DIR/scripts/build-sources.sh"

build_source_interactive() {
  return 0
}

printf '2\n' | configure_build_source_first_install >/tmp/zero-nvr-build-source-cn.out
grep -Fxq 'ZERO_NVR_BUILD_SOURCE_MODE=cn' "$ENV_FILE"

cp "$ROOT_DIR/.env.example" "$ENV_FILE"
printf '3\n' | configure_build_source_first_install >/tmp/zero-nvr-build-source-official.out
grep -Fxq 'ZERO_NVR_BUILD_SOURCE_MODE=official' "$ENV_FILE"

cp "$ROOT_DIR/.env.example" "$ENV_FILE"
printf '4\nhttps://deb.example/debian\nhttps://deb.example/security\nhttps://pypi.example/simple\nhttps://npm.example\n' \
  | configure_build_source_first_install >/tmp/zero-nvr-build-source-custom.out
grep -Fxq 'ZERO_NVR_BUILD_SOURCE_MODE=custom' "$ENV_FILE"
grep -Fxq 'DEBIAN_MIRROR=https://deb.example/debian' "$ENV_FILE"
grep -Fxq 'DEBIAN_SECURITY_MIRROR=https://deb.example/security' "$ENV_FILE"
grep -Fxq 'PYPI_INDEX_URL=https://pypi.example/simple' "$ENV_FILE"
grep -Fxq 'NPM_REGISTRY=https://npm.example' "$ENV_FILE"

cp "$ROOT_DIR/.env.example" "$ENV_FILE"
build_source_interactive() {
  return 1
}
configure_build_source_first_install >/tmp/zero-nvr-build-source-noninteractive.out
grep -Fxq 'ZERO_NVR_BUILD_SOURCE_MODE=auto' "$ENV_FILE"

echo "build source selection tests passed"
