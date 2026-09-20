#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
. "$SCRIPT_DIR/lib.sh"
. "$SCRIPT_DIR/benchmark-lib.sh"

usage() {
  cat <<'EOF'
Usage:
  ./deploy.sh benchmark <8|16> [--samples N] [--interval SECONDS]

Validates configured real cameras. No synthetic RTSP sources are created.
EOF
}

expected="$1"
shift || true

if [[ "$expected" != "8" && "$expected" != "16" ]]; then
  echo "error: benchmark target must be 8 or 16 cameras" >&2
  usage >&2
  exit 2
fi

samples=5
interval=2

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --samples)
      shift
      samples="$1"
      ;;
    --interval)
      shift
      interval="$1"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown benchmark option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

if [[ ! "$samples" =~ ^[1-9][0-9]*$ ]]; then
  echo "error: --samples must be a positive integer" >&2
  exit 2
fi
if [[ ! "$interval" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
  echo "error: --interval must be a non-negative number" >&2
  exit 2
fi

require_command docker
docker compose version >/dev/null
docker info >/dev/null

if [[ ! -f "$ENV_FILE" ]]; then
  echo "error: .env is missing" >&2
  exit 1
fi

ZERO_NVR_ENV_FILE="$ENV_FILE"   "$SCRIPT_DIR/check.sh" >/dev/null

api_id="$(compose ps -q zero-nvr)"
worker_id="$(compose ps -q zero-nvr-worker)"
zlm_id="$(compose ps -q zlmediakit)"

if [[ -z "$api_id" || -z "$worker_id" || -z "$zlm_id" ]]; then
  echo "error: core containers must be running before benchmark" >&2
  exit 1
fi

runtime_rc=0
runtime_json="$(
  compose exec -T zero-nvr     python -m app.cli benchmark-status     --expected-cameras "$expected"
)" || runtime_rc=$?

if [[ -z "$runtime_json" ]]; then
  echo "error: benchmark runtime status was not returned" >&2
  exit 1
fi

container_memory_bytes() {
  local container_id="$1"
  local usage
  usage="$(
    docker stats       --no-stream       --format '{{.MemUsage}}'       "$container_id" |
      awk 'NR == 1 {print $1}'
  )"
  if [[ -z "$usage" ]]; then
    echo "error: no memory usage for $container_id" >&2
    return 1
  fi
  size_to_bytes "$usage"
}

image_size_bytes() {
  docker image inspect     --format '{{.Size}}'     "$1"
}

api_image="$(docker inspect --format '{{.Image}}' "$api_id")"
worker_image="$(docker inspect --format '{{.Image}}' "$worker_id")"
zlm_image="$(docker inspect --format '{{.Image}}' "$zlm_id")"

image_bytes="$(image_size_bytes "$api_image")"
if [[ "$worker_image" != "$api_image" ]]; then
  worker_image_bytes="$(image_size_bytes "$worker_image")"
  image_bytes=$((image_bytes + worker_image_bytes))
fi
if [[ "$zlm_image" != "$api_image" && "$zlm_image" != "$worker_image" ]]; then
  zlm_image_bytes="$(image_size_bytes "$zlm_image")"
  image_bytes=$((image_bytes + zlm_image_bytes))
fi

control_sum=0
zlm_sum=0
total_sum=0
control_peak=0
zlm_peak=0
total_peak=0

for ((sample = 1; sample <= samples; sample++)); do
  api_mem="$(container_memory_bytes "$api_id")"
  worker_mem="$(container_memory_bytes "$worker_id")"
  zlm_mem="$(container_memory_bytes "$zlm_id")"

  control_mem=$((api_mem + worker_mem))
  total_mem=$((control_mem + zlm_mem))

  control_sum=$((control_sum + control_mem))
  zlm_sum=$((zlm_sum + zlm_mem))
  total_sum=$((total_sum + total_mem))

  if (( control_mem > control_peak )); then
    control_peak="$control_mem"
  fi
  if (( zlm_mem > zlm_peak )); then
    zlm_peak="$zlm_mem"
  fi
  if (( total_mem > total_peak )); then
    total_peak="$total_mem"
  fi

  if (( sample < samples )); then
    sleep "$interval"
  fi
done

control_avg=$((control_sum / samples))
zlm_avg=$((zlm_sum / samples))
total_avg=$((total_sum / samples))

image_limit=$((2 * 1024 * 1024 * 1024))
control_memory_limit=$((1024 * 1024 * 1024))
image_pass=false
memory_pass=false

if (( image_bytes < image_limit )); then
  image_pass=true
fi
if (( control_peak < control_memory_limit )); then
  memory_pass=true
fi

if [[ "$expected" == "8" ]]; then
  profile="8-camera-baseline"
else
  profile="16-camera-extended"
fi

report="$(
  printf '%s' "$runtime_json" |
    compose exec -T       -e BENCH_PROFILE="$profile"       -e BENCH_SAMPLES="$samples"       -e BENCH_INTERVAL="$interval"       -e BENCH_RUNTIME_RC="$runtime_rc"       -e BENCH_IMAGE_BYTES="$image_bytes"       -e BENCH_IMAGE_LIMIT="$image_limit"       -e BENCH_IMAGE_PASS="$image_pass"       -e BENCH_CONTROL_AVG="$control_avg"       -e BENCH_CONTROL_PEAK="$control_peak"       -e BENCH_CONTROL_LIMIT="$control_memory_limit"       -e BENCH_CONTROL_PASS="$memory_pass"       -e BENCH_ZLM_AVG="$zlm_avg"       -e BENCH_ZLM_PEAK="$zlm_peak"       -e BENCH_TOTAL_AVG="$total_avg"       -e BENCH_TOTAL_PEAK="$total_peak"       zero-nvr       python -c '
import json
import os
import sys

runtime = json.load(sys.stdin)
resource_pass = (
    os.environ["BENCH_IMAGE_PASS"] == "true"
    and os.environ["BENCH_CONTROL_PASS"] == "true"
)
runtime_pass = (
    os.environ["BENCH_RUNTIME_RC"] == "0"
    and bool(runtime.get("passed"))
)

report = {
    "profile": os.environ["BENCH_PROFILE"],
    "passed": resource_pass and runtime_pass,
    "runtime": runtime,
    "resources": {
        "samples": int(os.environ["BENCH_SAMPLES"]),
        "interval_seconds": float(os.environ["BENCH_INTERVAL"]),
        "core_image_virtual_size_bytes": int(
            os.environ["BENCH_IMAGE_BYTES"]
        ),
        "core_image_limit_bytes": int(
            os.environ["BENCH_IMAGE_LIMIT"]
        ),
        "core_image_passed": (
            os.environ["BENCH_IMAGE_PASS"] == "true"
        ),
        "control_plane_memory_avg_bytes": int(
            os.environ["BENCH_CONTROL_AVG"]
        ),
        "control_plane_memory_peak_bytes": int(
            os.environ["BENCH_CONTROL_PEAK"]
        ),
        "control_plane_memory_limit_bytes": int(
            os.environ["BENCH_CONTROL_LIMIT"]
        ),
        "control_plane_memory_passed": (
            os.environ["BENCH_CONTROL_PASS"] == "true"
        ),
        "zlmediakit_memory_avg_bytes": int(
            os.environ["BENCH_ZLM_AVG"]
        ),
        "zlmediakit_memory_peak_bytes": int(
            os.environ["BENCH_ZLM_PEAK"]
        ),
        "core_total_memory_avg_bytes": int(
            os.environ["BENCH_TOTAL_AVG"]
        ),
        "core_total_memory_peak_bytes": int(
            os.environ["BENCH_TOTAL_PEAK"]
        ),
    },
    "methodology": {
        "image_size": (
            "sum of unique zero-nvr and ZLMediaKit Docker "
            "image virtual sizes; shared cross-image layers "
            "are not deduplicated"
        ),
        "memory_gate": (
            "API + worker Docker memory usage; ZLMediaKit "
            "is reported separately because media buffers "
            "and page cache vary with workload"
        ),
        "camera_workload": (
            "configured real cameras only; no synthetic "
            "source is generated"
        ),
    },
}

print(json.dumps(report, sort_keys=True))
'
)"

printf '%s\n' "$report"

if [[ "$runtime_rc" -ne 0 || "$image_pass" != true || "$memory_pass" != true ]]; then
  exit 1
fi
