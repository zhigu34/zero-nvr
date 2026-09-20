#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
. "$ROOT_DIR/scripts/benchmark-lib.sh"

[[ "$(size_to_bytes 1B)" == "1" ]]
[[ "$(size_to_bytes 1KiB)" == "1024" ]]
[[ "$(size_to_bytes 1.5MiB)" == "1572864" ]]
[[ "$(size_to_bytes 2GiB)" == "2147483648" ]]
[[ "$(size_to_bytes 1GB)" == "1000000000" ]]

echo "benchmark helpers: ok"


set +e
bash "$ROOT_DIR/scripts/benchmark.sh" >/tmp/zero-nvr-benchmark-no-args.out 2>&1
rc=$?
set -e
[[ "$rc" -eq 2 ]]
grep -Fq "benchmark target must be 8 or 16 cameras" /tmp/zero-nvr-benchmark-no-args.out

set +e
bash "$ROOT_DIR/scripts/benchmark.sh" 8 --samples >/tmp/zero-nvr-benchmark-missing-samples.out 2>&1
rc=$?
set -e
[[ "$rc" -eq 2 ]]
grep -Fq -- "--samples requires a value" /tmp/zero-nvr-benchmark-missing-samples.out

bash "$ROOT_DIR/scripts/benchmark.sh" --help >/tmp/zero-nvr-benchmark-help.out
grep -Fq "benchmark <8|16>" /tmp/zero-nvr-benchmark-help.out
