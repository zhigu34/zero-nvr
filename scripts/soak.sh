#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
. "$SCRIPT_DIR/lib.sh"
. "$SCRIPT_DIR/benchmark-lib.sh"
. "$SCRIPT_DIR/release-validation-lib.sh"

usage() {
  cat <<'EOF'
Usage:
  ./deploy.sh soak <2|4|8|16> [--duration SECONDS] [--interval SECONDS]

Runs a release soak against the configured real camera workload.
Default: 600 seconds total, sampled every 30 seconds.
EOF
}

expected="${1:-}"
if [[ "$expected" == "-h" || "$expected" == "--help" ]]; then
  usage
  exit 0
fi
shift || true

if [[ "$expected" != "2" && "$expected" != "4" \
  && "$expected" != "8" && "$expected" != "16" ]]; then
  echo "error: soak target must be 2, 4, 8, or 16 cameras" >&2
  usage >&2
  exit 2
fi

duration=600
interval=30

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --duration)
      shift
      duration="${1:-}"
      if [[ -z "$duration" ]]; then
        echo "error: --duration requires a value" >&2
        exit 2
      fi
      ;;
    --interval)
      shift
      interval="${1:-}"
      if [[ -z "$interval" ]]; then
        echo "error: --interval requires a value" >&2
        exit 2
      fi
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown soak option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

if [[ ! "$duration" =~ ^[1-9][0-9]*$ ]]; then
  echo "error: --duration must be a positive integer" >&2
  exit 2
fi
if [[ ! "$interval" =~ ^[1-9][0-9]*$ ]]; then
  echo "error: --interval must be a positive integer" >&2
  exit 2
fi

small_host=false
if [[ "$expected" == "2" || "$expected" == "4" ]]; then
  small_host=true
fi

require_command docker
docker compose version >/dev/null
docker info >/dev/null

if [[ ! -f "$ENV_FILE" ]]; then
  echo "error: .env is missing" >&2
  exit 1
fi

if [[ "$small_host" == "true" ]]; then
  for command in python3 getconf awk; do
    require_command "$command"
  done
  profiles="$(env_get COMPOSE_PROFILES "")"
  if [[ -n "$profiles" ]]; then
    echo "error: small-host soak requires Core-only COMPOSE_PROFILES=" >&2
    exit 1
  fi
fi

ZERO_NVR_ENV_FILE="$ENV_FILE" \
  "$SCRIPT_DIR/check.sh" >/dev/null

api_id="$(compose ps -q zero-nvr)"
worker_id="$(compose ps -q zero-nvr-worker)"
zlm_id="$(compose ps -q zlmediakit)"

if [[ -z "$api_id" || -z "$worker_id" || -z "$zlm_id" ]]; then
  echo "error: core containers must be running before soak" >&2
  exit 1
fi

if [[ "$small_host" == "true" ]]; then
  initial_api_restarts="$(
    docker inspect --format '{{.RestartCount}}' "$api_id"
  )"
  initial_worker_restarts="$(
    docker inspect --format '{{.RestartCount}}' "$worker_id"
  )"
  initial_zlm_restarts="$(
    docker inspect --format '{{.RestartCount}}' "$zlm_id"
  )"
  host_cpu_count="$(getconf _NPROCESSORS_ONLN)"
  host_memory_total_bytes="$(
    awk '/^MemTotal:/ {printf "%.0f", $2 * 1024}' /proc/meminfo
  )"
fi

started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
samples_file="$(mktemp)"
resources_file="$(mktemp)"
report_file="$(mktemp)"
trap 'rm -f "$samples_file" "$resources_file" "$report_file"' EXIT

sample_count=0
failed_samples=0
elapsed=0

collect_small_host_resource_sample() {
  local sample_index="$1"
  local sample_json="$2"
  local api_stats worker_stats zlm_stats
  local api_mem worker_mem zlm_mem
  local api_cpu worker_cpu zlm_cpu
  local api_restart worker_restart zlm_restart
  local host_available wal_bytes record_streams

  api_stats="$(
    docker stats --no-stream \
      --format '{{.MemUsage}}	{{.CPUPerc}}' "$api_id"
  )"
  worker_stats="$(
    docker stats --no-stream \
      --format '{{.MemUsage}}	{{.CPUPerc}}' "$worker_id"
  )"
  zlm_stats="$(
    docker stats --no-stream \
      --format '{{.MemUsage}}	{{.CPUPerc}}' "$zlm_id"
  )"

  api_mem="$(size_to_bytes "${api_stats%% *}")"
  worker_mem="$(size_to_bytes "${worker_stats%% *}")"
  zlm_mem="$(size_to_bytes "${zlm_stats%% *}")"

  api_cpu="${api_stats##*  sample_rc=0
  sample_json="$(
    compose exec -T zero-nvr \
      python -m app.cli soak-status \
      --expected-cameras "$expected" \
      --since "$started_at"
  )" || sample_rc=$?

  if [[ -z "$sample_json" ]]; then
    sample_json='{"passed":false,"failures":["sample_output_missing"]}'
    sample_rc=1
  fi
  printf '%s\n' "$sample_json" >> "$samples_file"

  sample_count=$((sample_count + 1))
  if [[ "$small_host" == "true" ]]; then
    collect_small_host_resource_sample \
      "$sample_count" "$sample_json"
  fi
  if [[ "$sample_rc" -ne 0 ]]; then
    failed_samples=$((failed_samples + 1))
  fi

  remaining=$((duration - elapsed))
  sleep_for="$interval"
  if (( sleep_for > remaining )); then
    sleep_for="$remaining"
  fi
  sleep "$sleep_for"
  elapsed=$((elapsed + sleep_for))
done

final_rc=0
final_json="$(
  compose exec -T zero-nvr \
    python -m app.cli soak-status \
    --expected-cameras "$expected" \
    --since "$started_at" \
    --require-progress
)" || final_rc=$?

if [[ -z "$final_json" ]]; then
  final_json='{"passed":false,"failures":["final_output_missing"]}'
  final_rc=1
fi

if [[ "$small_host" == "true" ]]; then
  collect_small_host_resource_sample \
    "$((sample_count + 1))" "$final_json"
fi

report="$(
  {
    cat "$samples_file"
    printf '%s\n' "$final_json"
  } |
    compose exec -T \
      -e SOAK_EXPECTED="$expected" \
      -e SOAK_STARTED_AT="$started_at" \
      -e SOAK_DURATION="$duration" \
      -e SOAK_INTERVAL="$interval" \
      -e SOAK_SAMPLE_COUNT="$sample_count" \
      -e SOAK_FAILED_SAMPLES="$failed_samples" \
      -e SOAK_FINAL_RC="$final_rc" \
      zero-nvr \
      python -c '
import collections
import json
import os
import sys
from datetime import UTC, datetime

items = [
    json.loads(line)
    for line in sys.stdin
    if line.strip()
]
final = items[-1]
samples = items[:-1]

failure_counts = collections.Counter()
for sample in samples:
    for failure in sample.get("failures", []):
        failure_counts[str(failure)] += 1

passed = (
    int(os.environ["SOAK_FAILED_SAMPLES"]) == 0
    and os.environ["SOAK_FINAL_RC"] == "0"
    and bool(final.get("passed"))
)

report = {
    "generated_at": datetime.now(UTC).isoformat(),
    "profile": (
        f"{os.environ['"'"'SOAK_EXPECTED'"'"']}-camera-soak"
    ),
    "passed": passed,
    "started_at": os.environ["SOAK_STARTED_AT"],
    "duration_seconds": int(
        os.environ["SOAK_DURATION"]
    ),
    "interval_seconds": int(
        os.environ["SOAK_INTERVAL"]
    ),
    "sample_count": int(
        os.environ["SOAK_SAMPLE_COUNT"]
    ),
    "failed_sample_count": int(
        os.environ["SOAK_FAILED_SAMPLES"]
    ),
    "sample_failure_counts": dict(
        sorted(failure_counts.items())
    ),
    "final": final,
    "methodology": {
        "periodic_gate": (
            "every sample requires camera recorder/stream "
            "runtime and DB/worker/ZLM/storage health"
        ),
        "persistent_progress_gate": (
            "final sample requires every currently persistent "
            "camera to have produced a non-empty RecordingSegment "
            "with an AVAILABLE local recording location since start"
        ),
        "event_only": (
            "EVENT_ONLY prebuffer cameras require runtime health "
            "but no canonical segment when no event occurred"
        ),
    },
}

print(json.dumps(report, sort_keys=True))
'
)"

if [[ "$small_host" == "true" ]]; then
  printf '%s\n' "$report" > "$report_file"
  report="$(
    SMALL_HOST_EXPECTED="$expected" \
    SMALL_HOST_DURATION="$duration" \
    SMALL_HOST_CPU_COUNT="$host_cpu_count" \
    SMALL_HOST_MEMORY_TOTAL="$host_memory_total_bytes" \
    SMALL_HOST_INITIAL_API_RESTARTS="$initial_api_restarts" \
    SMALL_HOST_INITIAL_WORKER_RESTARTS="$initial_worker_restarts" \
    SMALL_HOST_INITIAL_ZLM_RESTARTS="$initial_zlm_restarts" \
    python3 - "$report_file" "$resources_file" <<'PY'
import json
import os
import statistics
import sys
from pathlib import Path

report = json.loads(
    Path(sys.argv[1]).read_text(encoding="utf-8")
)
rows = []
for line in Path(sys.argv[2]).read_text().splitlines():
    values = line.split("\t")
    rows.append(
        {
            "sample": int(values[0]),
            "api_memory_bytes": int(values[1]),
            "worker_memory_bytes": int(values[2]),
            "zlm_memory_bytes": int(values[3]),
            "api_cpu_percent": float(values[4]),
            "worker_cpu_percent": float(values[5]),
            "zlm_cpu_percent": float(values[6]),
            "api_restart_count": int(values[7]),
            "worker_restart_count": int(values[8]),
            "zlm_restart_count": int(values[9]),
            "host_memory_available_bytes": int(values[10]),
            "sqlite_wal_bytes": int(values[11]),
            "record_streams_online": int(values[12]),
        }
    )

expected = int(os.environ["SMALL_HOST_EXPECTED"])
duration = int(os.environ["SMALL_HOST_DURATION"])
host_cpu = int(os.environ["SMALL_HOST_CPU_COUNT"])
host_memory = int(os.environ["SMALL_HOST_MEMORY_TOTAL"])
initial = {
    "zero-nvr": int(
        os.environ["SMALL_HOST_INITIAL_API_RESTARTS"]
    ),
    "zero-nvr-worker": int(
        os.environ["SMALL_HOST_INITIAL_WORKER_RESTARTS"]
    ),
    "zlmediakit": int(
        os.environ["SMALL_HOST_INITIAL_ZLM_RESTARTS"]
    ),
}

core_memory = [
    row["api_memory_bytes"]
    + row["worker_memory_bytes"]
    + row["zlm_memory_bytes"]
    for row in rows
]
core_cpu = [
    row["api_cpu_percent"]
    + row["worker_cpu_percent"]
    + row["zlm_cpu_percent"]
    for row in rows
]
restart_delta = {
    "zero-nvr": max(
        row["api_restart_count"]
        for row in rows
    ) - initial["zero-nvr"],
    "zero-nvr-worker": max(
        row["worker_restart_count"]
        for row in rows
    ) - initial["zero-nvr-worker"],
    "zlmediakit": max(
        row["zlm_restart_count"]
        for row in rows
    ) - initial["zlmediakit"],
}

final = report.get("final") or {}
runtime = final.get("runtime") or {}
database = final.get("database") or {}
progress = final.get("persistent_progress") or []

duration_ok = duration >= 3600
sqlite_ok = database.get("backend") == "sqlite"
exact_workload = (
    int(runtime.get("enabled_cameras") or 0) == expected
    and int(
        runtime.get("recording_expected_cameras")
        or 0
    )
    == expected
)
continuous_recording = (
    len(progress) == expected
    and all(bool(item.get("passed")) for item in progress)
)
host_class_matches = (
    host_cpu <= 2
    and host_memory <= 2684354560
)
no_restarts = all(
    value == 0
    for value in restart_delta.values()
)
functional_passed = bool(report.get("passed"))
acceptance_passed = all(
    (
        functional_passed,
        duration_ok,
        sqlite_ok,
        exact_workload,
        continuous_recording,
        host_class_matches,
        no_restarts,
    )
)

bytes_written = sum(
    int(item.get("bytes_since_start") or 0)
    for item in progress
)
report["functional_passed"] = functional_passed
report["passed"] = acceptance_passed
report["profile"] = (
    f"{expected}-camera-small-host-soak"
)
report["small_host"] = {
    "duration_gate_passed": duration_ok,
    "minimum_duration_seconds": 3600,
    "database_sqlite": sqlite_ok,
    "exact_camera_workload": exact_workload,
    "continuous_recording": continuous_recording,
    "host_class_matches": host_class_matches,
    "target_host_cpu_cores": 2,
    "target_host_memory_bytes_max": 2684354560,
    "host_cpu_count": host_cpu,
    "host_memory_total_bytes": host_memory,
    "host_memory_available_min_bytes": min(
        row["host_memory_available_bytes"]
        for row in rows
    ),
    "core_memory_avg_bytes": int(
        statistics.mean(core_memory)
    ),
    "core_memory_peak_bytes": max(core_memory),
    "core_cpu_avg_percent": round(
        statistics.mean(core_cpu),
        3,
    ),
    "core_cpu_peak_percent": round(
        max(core_cpu),
        3,
    ),
    "sqlite_wal_peak_bytes": max(
        row["sqlite_wal_bytes"]
        for row in rows
    ),
    "record_streams_online_min": min(
        row["record_streams_online"]
        for row in rows
    ),
    "recording_write_bitrate_bps": (
        int(bytes_written * 8 / duration)
        if duration > 0
        else 0
    ),
    "container_restart_delta": restart_delta,
    "no_container_restarts": no_restarts,
    "resource_samples": rows,
}
print(json.dumps(report, sort_keys=True))
PY
  )"
fi

printf '%s\n' "$report"
if [[ "$small_host" == "true" ]]; then
  persist_release_validation_report \
    "small-host-$expected" "$report"
else
  persist_release_validation_report soak "$report"
fi

passed="$(
  printf '%s' "$report" |
    python3 -c 'import json,sys; print("true" if json.load(sys.stdin)["passed"] else "false")'
)"
[[ "$passed" == "true" ]]
\t'}"
  worker_cpu="${worker_stats##*  sample_rc=0
  sample_json="$(
    compose exec -T zero-nvr \
      python -m app.cli soak-status \
      --expected-cameras "$expected" \
      --since "$started_at"
  )" || sample_rc=$?

  if [[ -z "$sample_json" ]]; then
    sample_json='{"passed":false,"failures":["sample_output_missing"]}'
    sample_rc=1
  fi
  printf '%s\n' "$sample_json" >> "$samples_file"

  sample_count=$((sample_count + 1))
  if [[ "$sample_rc" -ne 0 ]]; then
    failed_samples=$((failed_samples + 1))
  fi

  remaining=$((duration - elapsed))
  sleep_for="$interval"
  if (( sleep_for > remaining )); then
    sleep_for="$remaining"
  fi
  sleep "$sleep_for"
  elapsed=$((elapsed + sleep_for))
done

final_rc=0
final_json="$(
  compose exec -T zero-nvr \
    python -m app.cli soak-status \
    --expected-cameras "$expected" \
    --since "$started_at" \
    --require-progress
)" || final_rc=$?

if [[ -z "$final_json" ]]; then
  final_json='{"passed":false,"failures":["final_output_missing"]}'
  final_rc=1
fi

report="$(
  {
    cat "$samples_file"
    printf '%s\n' "$final_json"
  } |
    compose exec -T \
      -e SOAK_EXPECTED="$expected" \
      -e SOAK_STARTED_AT="$started_at" \
      -e SOAK_DURATION="$duration" \
      -e SOAK_INTERVAL="$interval" \
      -e SOAK_SAMPLE_COUNT="$sample_count" \
      -e SOAK_FAILED_SAMPLES="$failed_samples" \
      -e SOAK_FINAL_RC="$final_rc" \
      zero-nvr \
      python -c '
import collections
import json
import os
import sys
from datetime import UTC, datetime

items = [
    json.loads(line)
    for line in sys.stdin
    if line.strip()
]
final = items[-1]
samples = items[:-1]

failure_counts = collections.Counter()
for sample in samples:
    for failure in sample.get("failures", []):
        failure_counts[str(failure)] += 1

passed = (
    int(os.environ["SOAK_FAILED_SAMPLES"]) == 0
    and os.environ["SOAK_FINAL_RC"] == "0"
    and bool(final.get("passed"))
)

report = {
    "generated_at": datetime.now(UTC).isoformat(),
    "profile": (
        f"{os.environ['"'"'SOAK_EXPECTED'"'"']}-camera-soak"
    ),
    "passed": passed,
    "started_at": os.environ["SOAK_STARTED_AT"],
    "duration_seconds": int(
        os.environ["SOAK_DURATION"]
    ),
    "interval_seconds": int(
        os.environ["SOAK_INTERVAL"]
    ),
    "sample_count": int(
        os.environ["SOAK_SAMPLE_COUNT"]
    ),
    "failed_sample_count": int(
        os.environ["SOAK_FAILED_SAMPLES"]
    ),
    "sample_failure_counts": dict(
        sorted(failure_counts.items())
    ),
    "final": final,
    "methodology": {
        "periodic_gate": (
            "every sample requires camera recorder/stream "
            "runtime and DB/worker/ZLM/storage health"
        ),
        "persistent_progress_gate": (
            "final sample requires every currently persistent "
            "camera to have produced a non-empty RecordingSegment "
            "with an AVAILABLE local recording location since start"
        ),
        "event_only": (
            "EVENT_ONLY prebuffer cameras require runtime health "
            "but no canonical segment when no event occurred"
        ),
    },
}

print(json.dumps(report, sort_keys=True))
'
)"

printf '%s\n' "$report"
persist_release_validation_report soak "$report"

if [[ "$failed_samples" -ne 0 || "$final_rc" -ne 0 ]]; then
  exit 1
fi
\t'}"
  zlm_cpu="${zlm_stats##*  sample_rc=0
  sample_json="$(
    compose exec -T zero-nvr \
      python -m app.cli soak-status \
      --expected-cameras "$expected" \
      --since "$started_at"
  )" || sample_rc=$?

  if [[ -z "$sample_json" ]]; then
    sample_json='{"passed":false,"failures":["sample_output_missing"]}'
    sample_rc=1
  fi
  printf '%s\n' "$sample_json" >> "$samples_file"

  sample_count=$((sample_count + 1))
  if [[ "$sample_rc" -ne 0 ]]; then
    failed_samples=$((failed_samples + 1))
  fi

  remaining=$((duration - elapsed))
  sleep_for="$interval"
  if (( sleep_for > remaining )); then
    sleep_for="$remaining"
  fi
  sleep "$sleep_for"
  elapsed=$((elapsed + sleep_for))
done

final_rc=0
final_json="$(
  compose exec -T zero-nvr \
    python -m app.cli soak-status \
    --expected-cameras "$expected" \
    --since "$started_at" \
    --require-progress
)" || final_rc=$?

if [[ -z "$final_json" ]]; then
  final_json='{"passed":false,"failures":["final_output_missing"]}'
  final_rc=1
fi

report="$(
  {
    cat "$samples_file"
    printf '%s\n' "$final_json"
  } |
    compose exec -T \
      -e SOAK_EXPECTED="$expected" \
      -e SOAK_STARTED_AT="$started_at" \
      -e SOAK_DURATION="$duration" \
      -e SOAK_INTERVAL="$interval" \
      -e SOAK_SAMPLE_COUNT="$sample_count" \
      -e SOAK_FAILED_SAMPLES="$failed_samples" \
      -e SOAK_FINAL_RC="$final_rc" \
      zero-nvr \
      python -c '
import collections
import json
import os
import sys
from datetime import UTC, datetime

items = [
    json.loads(line)
    for line in sys.stdin
    if line.strip()
]
final = items[-1]
samples = items[:-1]

failure_counts = collections.Counter()
for sample in samples:
    for failure in sample.get("failures", []):
        failure_counts[str(failure)] += 1

passed = (
    int(os.environ["SOAK_FAILED_SAMPLES"]) == 0
    and os.environ["SOAK_FINAL_RC"] == "0"
    and bool(final.get("passed"))
)

report = {
    "generated_at": datetime.now(UTC).isoformat(),
    "profile": (
        f"{os.environ['"'"'SOAK_EXPECTED'"'"']}-camera-soak"
    ),
    "passed": passed,
    "started_at": os.environ["SOAK_STARTED_AT"],
    "duration_seconds": int(
        os.environ["SOAK_DURATION"]
    ),
    "interval_seconds": int(
        os.environ["SOAK_INTERVAL"]
    ),
    "sample_count": int(
        os.environ["SOAK_SAMPLE_COUNT"]
    ),
    "failed_sample_count": int(
        os.environ["SOAK_FAILED_SAMPLES"]
    ),
    "sample_failure_counts": dict(
        sorted(failure_counts.items())
    ),
    "final": final,
    "methodology": {
        "periodic_gate": (
            "every sample requires camera recorder/stream "
            "runtime and DB/worker/ZLM/storage health"
        ),
        "persistent_progress_gate": (
            "final sample requires every currently persistent "
            "camera to have produced a non-empty RecordingSegment "
            "with an AVAILABLE local recording location since start"
        ),
        "event_only": (
            "EVENT_ONLY prebuffer cameras require runtime health "
            "but no canonical segment when no event occurred"
        ),
    },
}

print(json.dumps(report, sort_keys=True))
'
)"

printf '%s\n' "$report"
persist_release_validation_report soak "$report"

if [[ "$failed_samples" -ne 0 || "$final_rc" -ne 0 ]]; then
  exit 1
fi
\t'}"
  api_cpu="${api_cpu%\%}"
  worker_cpu="${worker_cpu%\%}"
  zlm_cpu="${zlm_cpu%\%}"

  api_restart="$(docker inspect --format '{{.RestartCount}}' "$api_id")"
  worker_restart="$(docker inspect --format '{{.RestartCount}}' "$worker_id")"
  zlm_restart="$(docker inspect --format '{{.RestartCount}}' "$zlm_id")"
  host_available="$(
    awk '/^MemAvailable:/ {printf "%.0f", $2 * 1024}' /proc/meminfo
  )"

  read -r wal_bytes record_streams < <(
    printf '%s' "$sample_json" |
      python3 -c '
import json
import sys
value = json.load(sys.stdin)
database = value.get("database") or {}
runtime = value.get("runtime") or {}
print(
    int(database.get("sqlite_wal_bytes") or 0),
    int(runtime.get("record_streams_online") or 0),
)
'
  )

  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$sample_index" \
    "$api_mem" "$worker_mem" "$zlm_mem" \
    "$api_cpu" "$worker_cpu" "$zlm_cpu" \
    "$api_restart" "$worker_restart" "$zlm_restart" \
    "$host_available" "$wal_bytes" "$record_streams" \
    >>"$resources_file"
}

while (( elapsed < duration )); do
  sample_rc=0
  sample_json="$(
    compose exec -T zero-nvr \
      python -m app.cli soak-status \
      --expected-cameras "$expected" \
      --since "$started_at"
  )" || sample_rc=$?

  if [[ -z "$sample_json" ]]; then
    sample_json='{"passed":false,"failures":["sample_output_missing"]}'
    sample_rc=1
  fi
  printf '%s\n' "$sample_json" >> "$samples_file"

  sample_count=$((sample_count + 1))
  if [[ "$sample_rc" -ne 0 ]]; then
    failed_samples=$((failed_samples + 1))
  fi

  remaining=$((duration - elapsed))
  sleep_for="$interval"
  if (( sleep_for > remaining )); then
    sleep_for="$remaining"
  fi
  sleep "$sleep_for"
  elapsed=$((elapsed + sleep_for))
done

final_rc=0
final_json="$(
  compose exec -T zero-nvr \
    python -m app.cli soak-status \
    --expected-cameras "$expected" \
    --since "$started_at" \
    --require-progress
)" || final_rc=$?

if [[ -z "$final_json" ]]; then
  final_json='{"passed":false,"failures":["final_output_missing"]}'
  final_rc=1
fi

report="$(
  {
    cat "$samples_file"
    printf '%s\n' "$final_json"
  } |
    compose exec -T \
      -e SOAK_EXPECTED="$expected" \
      -e SOAK_STARTED_AT="$started_at" \
      -e SOAK_DURATION="$duration" \
      -e SOAK_INTERVAL="$interval" \
      -e SOAK_SAMPLE_COUNT="$sample_count" \
      -e SOAK_FAILED_SAMPLES="$failed_samples" \
      -e SOAK_FINAL_RC="$final_rc" \
      zero-nvr \
      python -c '
import collections
import json
import os
import sys
from datetime import UTC, datetime

items = [
    json.loads(line)
    for line in sys.stdin
    if line.strip()
]
final = items[-1]
samples = items[:-1]

failure_counts = collections.Counter()
for sample in samples:
    for failure in sample.get("failures", []):
        failure_counts[str(failure)] += 1

passed = (
    int(os.environ["SOAK_FAILED_SAMPLES"]) == 0
    and os.environ["SOAK_FINAL_RC"] == "0"
    and bool(final.get("passed"))
)

report = {
    "generated_at": datetime.now(UTC).isoformat(),
    "profile": (
        f"{os.environ['"'"'SOAK_EXPECTED'"'"']}-camera-soak"
    ),
    "passed": passed,
    "started_at": os.environ["SOAK_STARTED_AT"],
    "duration_seconds": int(
        os.environ["SOAK_DURATION"]
    ),
    "interval_seconds": int(
        os.environ["SOAK_INTERVAL"]
    ),
    "sample_count": int(
        os.environ["SOAK_SAMPLE_COUNT"]
    ),
    "failed_sample_count": int(
        os.environ["SOAK_FAILED_SAMPLES"]
    ),
    "sample_failure_counts": dict(
        sorted(failure_counts.items())
    ),
    "final": final,
    "methodology": {
        "periodic_gate": (
            "every sample requires camera recorder/stream "
            "runtime and DB/worker/ZLM/storage health"
        ),
        "persistent_progress_gate": (
            "final sample requires every currently persistent "
            "camera to have produced a non-empty RecordingSegment "
            "with an AVAILABLE local recording location since start"
        ),
        "event_only": (
            "EVENT_ONLY prebuffer cameras require runtime health "
            "but no canonical segment when no event occurred"
        ),
    },
}

print(json.dumps(report, sort_keys=True))
'
)"

printf '%s\n' "$report"
persist_release_validation_report soak "$report"

if [[ "$failed_samples" -ne 0 || "$final_rc" -ne 0 ]]; then
  exit 1
fi
