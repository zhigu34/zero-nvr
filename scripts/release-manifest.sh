#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/lib.sh"
. "$SCRIPT_DIR/deployment-state.sh"

SOURCE_MANIFEST="$ROOT_DIR/release-manifest.json"

release_manifest_runtime_path() {
  printf '%s/deployment/release-manifest.json' "$(deployment_data_dir)"
}

validate_release_manifest() {
  python3 - "$ROOT_DIR" "$SOURCE_MANIFEST" <<'PY'
from __future__ import annotations

import ast
import json
import sys
import tomllib
from pathlib import Path

root = Path(sys.argv[1])
path = Path(sys.argv[2])
manifest = json.loads(path.read_text(encoding="utf-8"))

if manifest.get("format") != "zero-nvr.release-manifest":
    raise SystemExit("release manifest format is invalid")
if manifest.get("format_version") != 1:
    raise SystemExit("release manifest version is unsupported")

application = manifest.get("application")
if not isinstance(application, dict):
    raise SystemExit("release manifest application metadata is missing")
version = application.get("version")
if not isinstance(version, str) or not version:
    raise SystemExit("release manifest application version is invalid")

backend = tomllib.loads(
    (root / "backend/pyproject.toml").read_text(encoding="utf-8")
)
frontend = json.loads(
    (root / "frontend/package.json").read_text(encoding="utf-8")
)
if backend["project"]["version"] != version:
    raise SystemExit("release manifest/backend version mismatch")
if frontend["version"] != version:
    raise SystemExit("release manifest/frontend version mismatch")

revisions: set[str] = set()
parents: set[str] = set()
for migration in sorted(
    (root / "backend/alembic/versions").glob("*.py")
):
    tree = ast.parse(migration.read_text(encoding="utf-8"))
    revision = None
    down_revision = None
    for node in tree.body:
        target = None
        value = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            target = node.target
            value = node.value
        if not isinstance(target, ast.Name) or value is None:
            continue
        if target.id == "revision":
            revision = ast.literal_eval(value)
        elif target.id == "down_revision":
            down_revision = ast.literal_eval(value)

    if isinstance(revision, str):
        revisions.add(revision)
    if isinstance(down_revision, str):
        parents.add(down_revision)
    elif isinstance(down_revision, (tuple, list)):
        parents.update(
            item
            for item in down_revision
            if isinstance(item, str)
        )

heads = sorted(revisions - parents)
compatibility = manifest.get("compatibility")
if not isinstance(compatibility, dict):
    raise SystemExit("release manifest compatibility metadata is missing")
database = compatibility.get("database_schema")
if not isinstance(database, dict):
    raise SystemExit("database compatibility metadata is missing")
if database.get("accepted_heads") != heads:
    raise SystemExit(
        "release manifest Alembic heads do not match source: "
        + repr(heads)
    )

services = manifest.get("services")
if not isinstance(services, dict):
    raise SystemExit("release manifest service metadata is missing")
if services.get("core") != [
    "zero-nvr",
    "zero-nvr-worker",
    "zlmediakit",
]:
    raise SystemExit("release manifest Core service contract is invalid")

print(
    json.dumps(
        {
            "valid": True,
            "application_version": version,
            "database_schema_heads": heads,
        },
        sort_keys=True,
    )
)
PY
}

record_release_manifest() {
  local revision="${1:-}"
  local runtime_path runtime_dir model_file profiles status

  validate_release_manifest >/dev/null

  if [[ -z "$revision" ]]; then
    revision="$(git_revision || true)"
  fi
  if [[ -n "$revision" ]] && ! valid_revision "$revision"; then
    echo "error: release source revision is invalid: $revision" >&2
    return 1
  fi

  require_command docker
  require_command python3
  docker compose version >/dev/null
  docker info >/dev/null

  runtime_path="$(release_manifest_runtime_path)"
  runtime_dir="$(dirname -- "$runtime_path")"
  mkdir -p "$runtime_dir"
  model_file="$(mktemp "${TMPDIR:-/tmp}/zero-nvr-release-model.XXXXXX")"

  profiles="$(env_get COMPOSE_PROFILES "")"
  compose config --format json > "$model_file"

  if python3 -     "$SOURCE_MANIFEST"     "$runtime_path"     "$revision"     "$model_file"     "$ENV_FILE"     "$COMPOSE_FILE"     "$profiles" <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

source_path = Path(sys.argv[1])
runtime_path = Path(sys.argv[2])
revision = sys.argv[3] or None
model_path = Path(sys.argv[4])
env_file = sys.argv[5]
compose_file = sys.argv[6]
profiles = sys.argv[7]

source_bytes = source_path.read_bytes()
source = json.loads(source_bytes)
model = json.loads(model_path.read_text(encoding="utf-8"))

compose_env = os.environ.copy()
compose_env["COMPOSE_PROFILES"] = profiles

components: dict[str, object] = {}
for service, config in sorted(model.get("services", {}).items()):
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            env_file,
            "-f",
            compose_file,
            "images",
            "-q",
            service,
        ],
        check=False,
        capture_output=True,
        text=True,
        env=compose_env,
    )
    image_id = (
        result.stdout.splitlines()[0].strip()
        if result.returncode == 0 and result.stdout.strip()
        else None
    )
    repo_digests: list[str] = []
    if image_id:
        inspected = subprocess.run(
            [
                "docker",
                "image",
                "inspect",
                image_id,
                "--format",
                "{{json .RepoDigests}}",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if inspected.returncode == 0 and inspected.stdout.strip():
            parsed = json.loads(inspected.stdout)
            if isinstance(parsed, list):
                repo_digests = sorted(
                    str(item)
                    for item in parsed
                    if isinstance(item, str)
                )

    components[service] = {
        "image_ref": config.get("image"),
        "image_id": image_id,
        "repo_digests": repo_digests,
    }

for service in source["services"]["core"]:
    value = components.get(service)
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("image_id"), str)
        or not value["image_id"].startswith("sha256:")
    ):
        raise SystemExit(
            f"core release image identity unavailable: {service}"
        )

for group in source["services"].get("shared_image_groups", []):
    identities = {
        components[service]["image_id"]
        for service in group
        if service in components
    }
    if len(identities) != 1:
        raise SystemExit(
            "shared-image service identities diverged: "
            + ", ".join(group)
        )

identity = {
    "application_version": source["application"]["version"],
    "source_revision": revision,
    "components": components,
}
identity_sha256 = hashlib.sha256(
    json.dumps(
        identity,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
).hexdigest()

payload = {
    "format": "zero-nvr.deployed-release",
    "format_version": 1,
    "recorded_at": datetime.now(UTC).isoformat(),
    "application": source["application"],
    "source_revision": revision,
    "source_manifest_sha256": hashlib.sha256(
        source_bytes
    ).hexdigest(),
    "identity_sha256": identity_sha256,
    "compatibility": source["compatibility"],
    "components": components,
}

runtime_path.parent.mkdir(parents=True, exist_ok=True)
fd, temporary = tempfile.mkstemp(
    dir=runtime_path.parent,
    prefix=".release-manifest.",
)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, runtime_path)
finally:
    try:
        os.unlink(temporary)
    except FileNotFoundError:
        pass

print(
    json.dumps(
        {
            "recorded": True,
            "path": str(runtime_path),
            "application_version": source["application"]["version"],
            "source_revision": revision,
            "identity_sha256": identity_sha256,
        },
        sort_keys=True,
    )
)
PY
  then
    rm -f "$model_file"
  else
    status=$?
    rm -f "$model_file"
    return "$status"
  fi
}

show_release_manifest() {
  local runtime
  runtime="$(release_manifest_runtime_path)"
  if [[ ! -f "$runtime" ]]; then
    echo "error: deployed release manifest is unavailable: $runtime" >&2
    return 1
  fi
  cat "$runtime"
}

release_manifest_main() {
  local command="${1:-show}"
  shift || true
  case "$command" in
    validate)
      [[ "$#" -eq 0 ]] || {
        echo "error: release-manifest validate accepts no arguments" >&2
        return 2
      }
      validate_release_manifest
      ;;
    record)
      [[ "$#" -le 1 ]] || {
        echo "error: release-manifest record accepts at most one revision" >&2
        return 2
      }
      record_release_manifest "${1:-}"
      ;;
    show)
      [[ "$#" -eq 0 ]] || {
        echo "error: release-manifest show accepts no arguments" >&2
        return 2
      }
      show_release_manifest
      ;;
    *)
      echo "error: unsupported release-manifest command: $command" >&2
      return 2
      ;;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  release_manifest_main "$@"
fi
