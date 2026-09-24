#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

bash "$ROOT_DIR/scripts/camera-acceptance.sh"   --help   >/tmp/zero-nvr-camera-acceptance-help.out

grep -Fq "camera-acceptance prepare"   /tmp/zero-nvr-camera-acceptance-help.out
grep -Fq -- "--live-confirmed"   /tmp/zero-nvr-camera-acceptance-help.out

set +e
bash "$ROOT_DIR/scripts/camera-acceptance.sh"   invalid camera-id   >/tmp/zero-nvr-camera-acceptance-invalid.out 2>&1
rc=$?
set -e
[[ "$rc" -eq 2 ]]
grep -Fq "unsupported camera-acceptance action"   /tmp/zero-nvr-camera-acceptance-invalid.out

echo "camera acceptance arguments: ok"
