#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
POC_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
cd "$POC_DIR"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

set -a
. ./.env
set +a

collect_evidence() {
  docker compose ps > runtime/event-docker-compose-ps.txt 2>&1 || true
  docker compose logs --no-color > runtime/event-docker-compose.log 2>&1 || true
}

cleanup() {
  collect_evidence
  if [ "${KEEP_RUNNING:-0}" != "1" ]; then
    docker compose down -v --remove-orphans >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

docker compose down -v --remove-orphans >/dev/null 2>&1 || true
rm -rf runtime
mkdir -p runtime/recordings runtime/vod runtime/event-recordings

docker compose up -d --build

echo "Running rolling tmpfs EVENT_ONLY test with ~2s GOP..."
docker compose exec -T poc-api python /app/event_preroll.py \
  --stream event-gop2 \
  --source cam_main \
  --label gop2 \
  --gop-seconds 2

# The first proxy has been removed by the verifier. Give ZLM time to close
# its last fragment, then reset only the ephemeral tmpfs buffer so the second
# GOP test measures its own memory/file footprint.
docker compose exec -T poc-api sh -c 'sleep 2; find /prebuffer -mindepth 1 -maxdepth 1 -exec rm -rf {} +'

echo "Running rolling tmpfs EVENT_ONLY test with ~5s GOP..."
docker compose exec -T poc-api python /app/event_preroll.py \
  --stream event-gop5 \
  --source cam_gop5 \
  --label gop5 \
  --gop-seconds 5

# Reset ephemeral buffer once more so H.265 gets an independent footprint.
docker compose exec -T poc-api sh -c 'sleep 2; find /prebuffer -mindepth 1 -maxdepth 1 -exec rm -rf {} +'

echo "Running rolling tmpfs EVENT_ONLY test with H.265 / ~2s GOP..."
docker compose exec -T poc-api python /app/event_preroll.py \
  --stream event-h265 \
  --source cam_h265 \
  --label h265 \
  --gop-seconds 2

# Reset ephemeral buffer before the restart/reconstruction check.
docker compose exec -T poc-api sh -c 'sleep 2; find /prebuffer -mindepth 1 -maxdepth 1 -exec rm -rf {} +'

echo "Preparing EVENT_ONLY trigger before FastAPI restart..."
docker compose exec -T poc-api python /app/prebuffer_recovery.py prepare

echo "Stopping FastAPI while ZLM continues rolling tmpfs recording..."
docker compose stop poc-api
sleep 14
docker compose start poc-api

echo "Waiting for FastAPI health after EVENT_ONLY restart..."
i=0
until docker compose exec -T poc-api python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).read()" >/dev/null 2>&1; do
  i=$((i+1))
  if [ "$i" -ge 30 ]; then
    echo "POC API did not recover during EVENT_ONLY reconstruction test" >&2
    exit 1
  fi
  sleep 1
done

echo "Recovering trigger coverage from persisted trigger + tmpfs scan only..."
docker compose exec -T poc-api python /app/prebuffer_recovery.py recover

echo "Recording comparison evidence for startRecordTask and GOP-ring startRecord..."
docker compose exec -T poc-api python /app/record_task_compare.py

collect_evidence

echo
echo "EVENT_ONLY evidence:"
echo "  $POC_DIR/runtime/event-preroll-gop2.json"
echo "  $POC_DIR/runtime/event-preroll-gop5.json"
echo "  $POC_DIR/runtime/event-preroll-h265.json"
echo "  $POC_DIR/runtime/event-preroll-recovery.json"
echo "  $POC_DIR/runtime/pre-roll-candidate-comparison.json"
echo "  $POC_DIR/runtime/event-docker-compose.log"
