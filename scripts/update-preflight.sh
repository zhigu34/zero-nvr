#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/lib.sh"
. "$SCRIPT_DIR/deployment-state.sh"
. "$SCRIPT_DIR/release-manifest.sh"

UPDATE_PREFLIGHT_MARGIN_BYTES=$((512 * 1024 * 1024))

release_version_from_file() {
  python3 - "$1" <<'PY'
import json
import sys
from pathlib import Path

value = json.loads(
    Path(sys.argv[1]).read_text(encoding="utf-8")
)
version = value.get("application", {}).get("version")
if not isinstance(version, str) or not version:
    raise SystemExit("release version is missing")
print(version)
PY
}

assert_version_not_older() {
  python3 - "$1" "$2" <<'PY'
import re
import sys

def core(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(
        r"(\d+)\.(\d+)\.(\d+)(?:[-+].*)?",
        value,
    )
    if match is None:
        raise SystemExit(
            f"unsupported release version syntax: {value}"
        )
    return tuple(int(item) for item in match.groups())

current = sys.argv[1]
target = sys.argv[2]
if core(target) < core(current):
    raise SystemExit(
        f"target release {target} is older than deployed release {current}"
    )
PY
}

filesystem_free_bytes() {
  local path="$1"
  local available_kb
  available_kb="$(
    df -Pk "$path" | awk 'NR == 2 {print $4}'
  )"
  [[ "$available_kb" =~ ^[0-9]+$ ]] || {
    echo "error: could not determine free space for $path" >&2
    return 1
  }
  printf '%s' "$((available_kb * 1024))"
}

require_free_bytes() {
  local label="$1"
  local path="$2"
  local required="$3"
  local available
  available="$(filesystem_free_bytes "$path")"
  if (( available < required )); then
    echo "error: update preflight free-space check failed for $label" >&2
    echo "required: $required bytes" >&2
    echo "available: $available bytes" >&2
    return 1
  fi
  printf '[PASS] free-space %s required=%s available=%s\n'     "$label" "$required" "$available"
}

update_preflight_main() {
  local target_root="${1:-$ROOT_DIR}"
  local target_revision="${2:-}"
  local backup_policy="${3:-}"
  local target_manifest current_manifest
  local target_version current_version
  local profiles expected_services running_services service
  local backend_json database_size keyring_status backup_ready backup_name
  local container_id image_id image_size
  local data_path docker_root data_device docker_device
  local data_required docker_required combined_required

  require_command docker
  require_command python3
  require_command df
  require_command stat

  [[ -f "$target_root/release-manifest.json" ]] || {
    echo "error: target release manifest is missing" >&2
    return 1
  }
  [[ -x "$target_root/scripts/release-manifest.sh" ]] || {
    echo "error: target release manifest validator is missing" >&2
    return 1
  }

  "$target_root/scripts/release-manifest.sh" validate >/dev/null
  target_manifest="$target_root/release-manifest.json"
  target_version="$(release_version_from_file "$target_manifest")"

  current_manifest="$(release_manifest_runtime_path 2>/dev/null || true)"
  if [[ -z "$current_manifest" || ! -f "$current_manifest" ]]; then
    current_manifest="$ROOT_DIR/release-manifest.json"
  fi
  current_version="$(release_version_from_file "$current_manifest")"
  assert_version_not_older "$current_version" "$target_version"
  printf '[PASS] version deployed=%s target=%s revision=%s\n'     "$current_version" "$target_version" "${target_revision:-unknown}"

  profiles="$(env_get COMPOSE_PROFILES "")"
  COMPOSE_PROFILES="$profiles" docker compose     --env-file "$ENV_FILE"     -f "$target_root/docker-compose.yml"     config --quiet
  printf '[PASS] target release/schema/component contract validated\n'

  expected_services="$(compose config --services)"
  running_services="$(compose ps --status running --services)"
  while IFS= read -r service; do
    [[ -z "$service" ]] && continue
    if ! printf '%s\n' "$running_services" | grep -Fxq "$service"; then
      echo "error: update preflight component is not running: $service" >&2
      return 1
    fi
  done <<< "$expected_services"
  ZERO_NVR_ENV_FILE="$ENV_FILE" "$SCRIPT_DIR/check.sh" >/dev/null
  printf '[PASS] active components healthy: %s\n'     "$(printf '%s' "$expected_services" | tr '\n' ' ')"

  backend_args=(
    python -m app.cli update-preflight
  )
  if [[ -n "$backup_policy" ]]; then
    backend_args+=(--policy "$backup_policy")
  fi
  backend_json="$(
    compose run --rm --no-deps zero-nvr       "${backend_args[@]}"
  )"

  readarray -t backend_values < <(
    python3 - "$backend_json" <<'PY'
import json
import sys

value = json.loads(sys.argv[1])
database = value["database"]
keyring = value["keyring"]
backup = value["backup"]
print(int(database["size_bytes"]))
print(str(database["backend"]))
print(str(keyring["status"]))
print("true" if backup["ready"] else "false")
print(str(backup.get("policy_name") or "not-required"))
PY
  )
  database_size="${backend_values[0]}"
  database_backend="${backend_values[1]}"
  keyring_status="${backend_values[2]}"
  backup_ready="${backend_values[3]}"
  backup_name="${backend_values[4]}"

  printf '[PASS] database reachable backend=%s size_bytes=%s schema=current\n'     "$database_backend" "$database_size"
  printf '[PASS] keyring readable status=%s\n' "$keyring_status"
  [[ "$backup_ready" == "true" ]] || {
    echo "error: update preflight backup policy is not ready" >&2
    return 1
  }
  printf '[PASS] backup readiness policy=%s\n' "$backup_name"

  container_id="$(compose ps -q zero-nvr | head -n 1)"
  [[ -n "$container_id" ]] || {
    echo "error: update preflight could not locate zero-nvr container" >&2
    return 1
  }
  image_id="$(
    docker container inspect "$container_id"       --format '{{.Image}}'
  )"
  image_size="$(
    docker image inspect "$image_id"       --format '{{.Size}}'
  )"
  [[ "$image_size" =~ ^[0-9]+$ ]] || {
    echo "error: update preflight could not determine Core image size" >&2
    return 1
  }

  data_path="$(host_path "$(env_get ZERO_NVR_DATA_PATH "./data/zero-nvr")")"
  docker_root="$(docker info --format '{{.DockerRootDir}}')"
  [[ -d "$data_path" ]] || {
    echo "error: update preflight data path is unavailable: $data_path" >&2
    return 1
  }
  [[ -d "$docker_root" ]] || {
    echo "error: Docker root directory is unavailable: $docker_root" >&2
    return 1
  }

  data_required="$((database_size + UPDATE_PREFLIGHT_MARGIN_BYTES))"
  docker_required="$((image_size + UPDATE_PREFLIGHT_MARGIN_BYTES))"
  data_device="$(stat -c '%d' "$data_path")"
  docker_device="$(stat -c '%d' "$docker_root")"

  if [[ "$data_device" == "$docker_device" ]]; then
    combined_required="$((data_required + docker_required))"
    require_free_bytes       "data+docker" "$data_path" "$combined_required"
  else
    require_free_bytes       "data" "$data_path" "$data_required"
    require_free_bytes       "docker" "$docker_root" "$docker_required"
  fi

  echo "update preflight: passed"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  update_preflight_main "$@"
fi
