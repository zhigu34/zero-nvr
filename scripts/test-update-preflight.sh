#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
. "$ROOT_DIR/scripts/update-preflight.sh"

assert_version_not_older "0.1.0" "0.1.0"
assert_version_not_older "0.1.0" "0.2.0"
assert_version_not_older "1.2.3" "2.0.0"

if assert_version_not_older "2.0.0" "1.9.9" >/dev/null 2>&1; then
  echo "FAIL: version downgrade was accepted" >&2
  exit 1
fi

free_bytes="$(filesystem_free_bytes "$ROOT_DIR")"
[[ "$free_bytes" =~ ^[0-9]+$ ]]
(( free_bytes > 0 ))

echo "update-preflight helpers: ok"
