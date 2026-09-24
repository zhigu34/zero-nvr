#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
. "$SCRIPT_DIR/lib.sh"
. "$SCRIPT_DIR/benchmark-lib.sh"
. "$SCRIPT_DIR/release-validation-lib.sh"

usage() {
  cat <<'EOF'
Usage:
  ./deploy.sh resource-baseline [--settle SECONDS] [--samples N] [--interval SECONDS]

Measures Plan 04 R1 on a running no-camera, Core-only deployment.
Default: settle 60 seconds, then collect 5 samples at 2-second intervals.
EOF
}

settle=60
samples=5
interval=2

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --settle)
      shift
      settle="${1:-}"
      [[ -n "$settle" ]] || {
        echo "error: --settle requires a value" >&2
        exit 2
      }
      ;;
    --samples)
      shift
      samples="${1:-}"
      [[ -n "$samples" ]] || {
        echo "error: --samples requires a value" >&2
        exit 2
      }
      ;;
    --interval)
      shift
      interval="${1:-}"
      [[ -n "$interval" ]] || {
        echo "error: --interval requires a value" >&2
        exit 2
      }
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown resource-baseline option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

if [[ ! "$settle" =~ ^[0-9]+$ ]]; then
  echo "error: --settle must be a non-negative integer" >&2
  exit 2
fi
if [[ ! "$samples" =~ ^[1-9][0-9]*$ ]]; then
  echo "error: --samples must be a positive integer" >&2
  exit 2
fi
if [[ ! "$interval" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
  echo "error: --interval must be a non-negative number" >&2
  exit 2
fi

for command in docker python3 du stat getconf awk paste wc tr sed; do
  require_command "$command"
done
docker compose version >/dev/null
docker info >/dev/null

[[ -f "$ENV_FILE" ]] || {
  echo "error: .env is missing" >&2
  exit 1
}

profiles="$(env_get COMPOSE_PROFILES "")"
if [[ -n "$profiles" ]]; then
  echo "error: R1 resource baseline requires Core-only COMPOSE_PROFILES=" >&2
  exit 1
fi

ZERO_NVR_ENV_FILE="$ENV_FILE" "$SCRIPT_DIR/check.sh" >/dev/null

running_services="$(
  compose ps --status running --services |
    sort |
    paste -sd, -
)"
if [[ "$running_services" != "zero-nvr,zero-nvr-worker,zlmediakit" ]]; then
  echo "error: R1 requires exactly the three running Core services" >&2
  echo "running: ${running_services:-none}" >&2
  exit 1
fi

runtime_file="$(mktemp)"
containers_file="$(mktemp)"
samples_file="$(mktemp)"
trap 'rm -f "$runtime_file" "$containers_file" "$samples_file"' EXIT

runtime_rc=0
compose exec -T zero-nvr   python -m app.cli resource-baseline-status   >"$runtime_file" || runtime_rc=$?
if [[ "$runtime_rc" -ne 0 ]]; then
  echo "error: R1 requires a clean database with zero configured cameras" >&2
  cat "$runtime_file" >&2
  exit 1
fi

if (( settle > 0 )); then
  sleep "$settle"
fi

path_bytes() {
  local path="$1"
  if [[ ! -e "$path" ]]; then
    printf '0'
    return 0
  fi
  du -sb "$path" | awk 'NR == 1 {print $1}'
}

file_bytes() {
  local path="$1"
  if [[ ! -f "$path" ]]; then
    printf '0'
    return 0
  fi
  stat -c '%s' "$path"
}

container_metadata() {
  local service="$1"
  local container_id image_id image_size size_rw log_bytes
  local log_config repo_digests

  container_id="$(compose ps -q "$service")"
  [[ -n "$container_id" ]] || {
    echo "error: missing Core container: $service" >&2
    return 1
  }

  image_id="$(docker inspect --format '{{.Image}}' "$container_id")"
  image_size="$(docker image inspect --format '{{.Size}}' "$image_id")"
  size_rw="$(
    docker inspect --size --format '{{.SizeRw}}' "$container_id"
  )"
  [[ "$size_rw" =~ ^[0-9]+$ ]] || size_rw=0

  log_bytes="$(
    docker logs "$container_id" 2>&1 | wc -c | tr -d '[:space:]'
  )"
  [[ "$log_bytes" =~ ^[0-9]+$ ]] || log_bytes=0

  log_config="$(
    docker inspect --format '{{json .HostConfig.LogConfig}}' "$container_id"
  )"
  repo_digests="$(
    docker image inspect --format '{{json .RepoDigests}}' "$image_id"
  )"

  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n'     "$service"     "$container_id"     "$image_id"     "$image_size"     "$size_rw"     "$log_bytes"     "$log_config"     "$repo_digests"     >>"$containers_file"
}

for service in zero-nvr zero-nvr-worker zlmediakit; do
  container_metadata "$service"
done

api_image="$(awk -F '\t' '$1 == "zero-nvr" {print $3}' "$containers_file")"
worker_image="$(awk -F '\t' '$1 == "zero-nvr-worker" {print $3}' "$containers_file")"
if [[ "$api_image" != "$worker_image" ]]; then
  echo "error: API and worker do not share the same Core image" >&2
  exit 1
fi

for ((sample = 1; sample <= samples; sample++)); do
  for service in zero-nvr zero-nvr-worker zlmediakit; do
    container_id="$(
      awk -F '\t' -v service="$service"         '$1 == service {print $2}' "$containers_file"
    )"
    stats="$(
      docker stats --no-stream         --format '{{.MemUsage}}	{{.CPUPerc}}'         "$container_id"
    )"
    memory_raw="${stats%%$'\t'*}"
    cpu_raw="${stats#*$'\t'}"
    memory_token="${memory_raw%% *}"
    memory_bytes="$(size_to_bytes "$memory_token")"
    cpu_percent="${cpu_raw%\%}"
    printf '%s\t%s\t%s\t%s\n'       "$sample" "$service" "$memory_bytes" "$cpu_percent"       >>"$samples_file"
  done

  if (( sample < samples )); then
    sleep "$interval"
  fi
done

data_path="$(host_path "$(env_get ZERO_NVR_DATA_PATH "./data/zero-nvr")")"
cache_path="$(host_path "$(env_get ZERO_NVR_CACHE_PATH "./data/cache")")"
recordings_path="$(host_path "$(env_get ZERO_NVR_RECORDINGS_PATH "./data/recordings")")"

data_bytes="$(path_bytes "$data_path")"
cache_bytes="$(path_bytes "$cache_path")"
recordings_bytes="$(path_bytes "$recordings_path")"
env_bytes="$(file_bytes "$ENV_FILE")"
zlm_config_bytes="$(file_bytes "$ROOT_DIR/deploy/zlm/config.ini")"

host_cpu_count="$(getconf _NPROCESSORS_ONLN)"
host_memory_total_bytes="$(
  awk '/^MemTotal:/ {printf "%.0f", $2 * 1024}' /proc/meminfo
)"
host_memory_available_bytes="$(
  awk '/^MemAvailable:/ {printf "%.0f", $2 * 1024}' /proc/meminfo
)"

report="$(
  RESOURCE_DATA_BYTES="$data_bytes"   RESOURCE_CACHE_BYTES="$cache_bytes"   RESOURCE_RECORDINGS_BYTES="$recordings_bytes"   RESOURCE_ENV_BYTES="$env_bytes"   RESOURCE_ZLM_CONFIG_BYTES="$zlm_config_bytes"   RESOURCE_HOST_CPU_COUNT="$host_cpu_count"   RESOURCE_HOST_MEMORY_TOTAL="$host_memory_total_bytes"   RESOURCE_HOST_MEMORY_AVAILABLE="$host_memory_available_bytes"   RESOURCE_SETTLE="$settle"   RESOURCE_SAMPLES="$samples"   RESOURCE_INTERVAL="$interval"   RESOURCE_PREBUFFER_SIZE="$(env_get ZERO_NVR_PREBUFFER_SIZE "512m")"   python3 -     "$runtime_file" "$containers_file" "$samples_file" <<'PY'
import json
import os
import statistics
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

runtime = json.loads(Path(sys.argv[1]).read_text())
containers = []
for line in Path(sys.argv[2]).read_text().splitlines():
    (
        service,
        container_id,
        image_id,
        image_size,
        size_rw,
        log_bytes,
        log_config,
        repo_digests,
    ) = line.split("\t", 7)
    containers.append(
        {
            "service": service,
            "container_id": container_id,
            "image_id": image_id,
            "image_virtual_size_bytes": int(image_size),
            "writable_layer_bytes": int(size_rw),
            "current_log_stream_bytes": int(log_bytes),
            "log_config": json.loads(log_config),
            "repo_digests": json.loads(repo_digests or "null") or [],
        }
    )

by_service = defaultdict(list)
by_sample = defaultdict(list)
for line in Path(sys.argv[3]).read_text().splitlines():
    sample, service, memory, cpu = line.split("\t")
    item = (int(memory), float(cpu))
    by_service[service].append(item)
    by_sample[int(sample)].append(item)

service_resources = {}
for service, values in sorted(by_service.items()):
    memories = [item[0] for item in values]
    cpus = [item[1] for item in values]
    service_resources[service] = {
        "memory_avg_bytes": int(statistics.mean(memories)),
        "memory_peak_bytes": max(memories),
        "cpu_avg_percent": round(statistics.mean(cpus), 3),
        "cpu_peak_percent": round(max(cpus), 3),
    }

total_memory_samples = [
    sum(item[0] for item in values)
    for _, values in sorted(by_sample.items())
]
total_cpu_samples = [
    sum(item[1] for item in values)
    for _, values in sorted(by_sample.items())
]

unique_images = {}
for item in containers:
    unique_images.setdefault(
        item["image_id"],
        item["image_virtual_size_bytes"],
    )

image_bytes = sum(unique_images.values())
writable_bytes = sum(
    item["writable_layer_bytes"]
    for item in containers
)
log_bytes = sum(
    item["current_log_stream_bytes"]
    for item in containers
)
data_bytes = int(os.environ["RESOURCE_DATA_BYTES"])
env_bytes = int(os.environ["RESOURCE_ENV_BYTES"])
zlm_config_bytes = int(
    os.environ["RESOURCE_ZLM_CONFIG_BYTES"]
)
initial_state_bytes = (
    data_bytes + env_bytes + zlm_config_bytes
)
static_bytes = (
    image_bytes
    + writable_bytes
    + log_bytes
    + initial_state_bytes
)
static_limit = 2 * 1024 * 1024 * 1024
idle_memory_limit = 1024 * 1024 * 1024
memory_peak = max(total_memory_samples)
passed = (
    bool(runtime.get("passed"))
    and static_bytes < static_limit
    and memory_peak < idle_memory_limit
)

report = {
    "format": "zero-nvr.resource-baseline",
    "format_version": 1,
    "profile": "r1-clean-core-idle",
    "generated_at": datetime.now(UTC).isoformat(),
    "application_version": runtime.get("application_version"),
    "passed": passed,
    "clean_core": {
        "configured_cameras": runtime.get("configured_cameras"),
        "enabled_cameras": runtime.get("enabled_cameras"),
        "database_backend": runtime.get("database_backend"),
        "optional_compose_profiles": [],
    },
    "static_footprint": {
        "passed": static_bytes < static_limit,
        "total_bytes": static_bytes,
        "limit_bytes": static_limit,
        "image_virtual_bytes_conservative": image_bytes,
        "container_writable_bytes": writable_bytes,
        "initial_product_state_bytes": initial_state_bytes,
        "data_bytes": data_bytes,
        "env_bytes": env_bytes,
        "generated_zlm_config_bytes": zlm_config_bytes,
        "current_log_stream_bytes": log_bytes,
        "recording_bytes_excluded": int(
            os.environ["RESOURCE_RECORDINGS_BYTES"]
        ),
        "cache_bytes_excluded": int(
            os.environ["RESOURCE_CACHE_BYTES"]
        ),
    },
    "idle_runtime": {
        "passed": memory_peak < idle_memory_limit,
        "settle_seconds": int(os.environ["RESOURCE_SETTLE"]),
        "samples": int(os.environ["RESOURCE_SAMPLES"]),
        "interval_seconds": float(
            os.environ["RESOURCE_INTERVAL"]
        ),
        "core_memory_avg_bytes": int(
            statistics.mean(total_memory_samples)
        ),
        "core_memory_peak_bytes": memory_peak,
        "core_memory_limit_bytes": idle_memory_limit,
        "core_cpu_avg_percent": round(
            statistics.mean(total_cpu_samples),
            3,
        ),
        "core_cpu_peak_percent": round(
            max(total_cpu_samples),
            3,
        ),
        "services": service_resources,
    },
    "host": {
        "cpu_count": int(
            os.environ["RESOURCE_HOST_CPU_COUNT"]
        ),
        "memory_total_bytes": int(
            os.environ["RESOURCE_HOST_MEMORY_TOTAL"]
        ),
        "memory_available_bytes": int(
            os.environ["RESOURCE_HOST_MEMORY_AVAILABLE"]
        ),
    },
    "containers": containers,
    "cache": {
        "usage_bytes": int(
            os.environ["RESOURCE_CACHE_BYTES"]
        ),
        "playback_quota_bytes": runtime.get(
            "playback_cache_max_bytes"
        ),
    },
    "prebuffer": {
        "configured_size": os.environ[
            "RESOURCE_PREBUFFER_SIZE"
        ],
    },
    "methodology": {
        "static_footprint": (
            "conservative sum of unique running Core image virtual sizes, "
            "container writable layers, initial data/env/generated ZLM "
            "configuration, and current Docker log streams; recording and "
            "cache bytes are reported but excluded"
        ),
        "idle_memory": (
            "sum of Docker/cgroup memory for API, worker, and ZLMediaKit "
            "after the settle window"
        ),
        "image_accounting": (
            "API and worker shared image is counted once; cross-image layer "
            "sharing is not subtracted, so the image figure is conservative"
        ),
    },
}
print(json.dumps(report, sort_keys=True))
PY
)"

printf '%s\n' "$report"
persist_release_validation_report resource-baseline "$report"

passed="$(
  printf '%s' "$report" |
    python3 -c 'import json,sys; print("true" if json.load(sys.stdin)["passed"] else "false")'
)"
[[ "$passed" == "true" ]]
