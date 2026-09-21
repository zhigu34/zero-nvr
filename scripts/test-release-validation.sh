#!/usr/bin/env bash
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

cat > "$tmp/.env" <<EOF
ZERO_NVR_DATA_PATH=$tmp/data
EOF

export ZERO_NVR_ENV_FILE="$tmp/.env"
. "$ROOT/scripts/lib.sh"
. "$ROOT/scripts/release-validation-lib.sh"

persist_release_validation_report   benchmark   '{"profile":"8-camera-baseline","passed":true}'

target="$tmp/data/release-validation/latest-benchmark.json"
test -f "$target"
grep -Fq '"profile":"8-camera-baseline"' "$target"

persist_release_validation_report   soak   '{"profile":"8-camera-soak","passed":false}'

test -f "$tmp/data/release-validation/latest-soak.json"

if persist_release_validation_report   invalid   '{}' >/dev/null 2>&1; then
  echo "expected invalid report kind to fail" >&2
  exit 1
fi

echo "release validation report helper: ok"
