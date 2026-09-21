#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
. "$SCRIPT_DIR/lib.sh"
. "$SCRIPT_DIR/release-validation-lib.sh"

usage() {
  cat <<'EOF'
Usage:
  ./deploy.sh soak <8|16> [--duration SECONDS] [--interval SECONDS]

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

if [[ "$expected" != "8" && "$expected" != "16" ]]; then
  echo "error: soak target must be 8 or 16 cameras" >&2
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

require_command docker
docker compose version >/dev/null
docker info >/dev/null

if [[ ! -f "$ENV_FILE" ]]; then
  echo "error: .env is missing" >&2
  exit 1
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

started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
samples_file="$(mktemp)"
trap 'rm -f "$samples_file"' EXIT

sample_count=0
failed_samples=0
elapsed=0

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
