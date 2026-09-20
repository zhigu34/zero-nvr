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
