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
  docker compose ps > runtime/timeline-docker-compose-ps.txt 2>&1 || true
  docker compose logs --no-color > runtime/timeline-docker-compose.log 2>&1 || true
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
mkdir -p runtime/recordings runtime/vod

docker compose up -d --build

echo "Preparing timeline stream and pre-outage segments..."
docker compose exec -T poc-api python /app/timeline_playback.py prepare

OUTAGE_START=$(docker compose exec -T poc-api python -c 'import time; print(time.time())')
echo "Killing MediaMTX to create a real source outage..."
docker compose kill -s KILL mediamtx
sleep 8

echo "Restarting MediaMTX synthetic camera source..."
docker compose up -d mediamtx
OUTAGE_END=$(docker compose exec -T poc-api python -c 'import time; print(time.time())')

echo "Verifying post-outage timeline and ZLM VOD seek..."
docker compose exec -T poc-api python /app/timeline_playback.py verify \
  --outage-start "$OUTAGE_START" \
  --outage-end "$OUTAGE_END"

collect_evidence

echo
echo "Timeline / VOD evidence:"
echo "  $POC_DIR/runtime/timeline-playback-evidence.json"
echo "  $POC_DIR/runtime/timeline-docker-compose.log"
