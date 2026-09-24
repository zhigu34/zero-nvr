#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

"$ROOT_DIR/scripts/release-manifest.sh" validate   >/tmp/zero-nvr-release-manifest-validation.json

python3 - "$ROOT_DIR" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
manifest = json.loads(
    (root / "release-manifest.json").read_text()
)
assert manifest["format"] == "zero-nvr.release-manifest"
assert manifest["format_version"] == 1
assert manifest["application"]["version"] == "0.1.0"
assert manifest["compatibility"]["database_schema"]["accepted_heads"] == [
    "0017_camera_maintenance"
]
assert manifest["compatibility"]["backup_manifest"] == {
    "format": "zero-nvr.backup-manifest",
    "versions": [1],
}
assert manifest["services"]["core"] == [
    "zero-nvr",
    "zero-nvr-worker",
    "zlmediakit",
]
PY

echo "release-manifest: ok"
