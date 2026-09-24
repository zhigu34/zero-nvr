#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

set +e
bash "$ROOT_DIR/scripts/soak.sh" >/tmp/zero-nvr-soak-no-args.out 2>&1
rc=$?
set -e
[[ "$rc" -eq 2 ]]
grep -Fq "soak target must be 2, 4, 8, or 16 cameras" /tmp/zero-nvr-soak-no-args.out

set +e
bash "$ROOT_DIR/scripts/soak.sh" 8 --duration >/tmp/zero-nvr-soak-missing-duration.out 2>&1
rc=$?
set -e
[[ "$rc" -eq 2 ]]
grep -Fq -- "--duration requires a value" /tmp/zero-nvr-soak-missing-duration.out

set +e
bash "$ROOT_DIR/scripts/soak.sh" 8 --interval 0 >/tmp/zero-nvr-soak-zero-interval.out 2>&1
rc=$?
set -e
[[ "$rc" -eq 2 ]]
grep -Fq -- "--interval must be a positive integer" /tmp/zero-nvr-soak-zero-interval.out

bash "$ROOT_DIR/scripts/soak.sh" --help >/tmp/zero-nvr-soak-help.out
grep -Fq "soak <2|4|8|16>" /tmp/zero-nvr-soak-help.out

echo "soak arguments: ok"
