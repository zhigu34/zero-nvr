#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

bash "$ROOT_DIR/scripts/resource-baseline.sh" --help   >/tmp/zero-nvr-resource-baseline-help.out
grep -Fq "resource-baseline"   /tmp/zero-nvr-resource-baseline-help.out
grep -Fq "settle 60 seconds"   /tmp/zero-nvr-resource-baseline-help.out

set +e
bash "$ROOT_DIR/scripts/resource-baseline.sh"   --samples 0   >/tmp/zero-nvr-resource-baseline-zero-samples.out 2>&1
rc=$?
set -e
[[ "$rc" -eq 2 ]]
grep -Fq -- "--samples must be a positive integer"   /tmp/zero-nvr-resource-baseline-zero-samples.out

set +e
bash "$ROOT_DIR/scripts/resource-baseline.sh"   --settle nope   >/tmp/zero-nvr-resource-baseline-bad-settle.out 2>&1
rc=$?
set -e
[[ "$rc" -eq 2 ]]
grep -Fq -- "--settle must be a non-negative integer"   /tmp/zero-nvr-resource-baseline-bad-settle.out

echo "resource baseline arguments: ok"
