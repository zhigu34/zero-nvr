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

echo "Running rolling tmpfs EVENT_ONLY test with ~5s GOP..."
docker compose exec -T poc-api python /app/event_preroll.py \
  --stream event-gop5 \
  --source cam_gop5 \
  --label gop5 \
  --gop-seconds 5

collect_evidence

echo
echo "EVENT_ONLY evidence:"
echo "  $POC_DIR/runtime/event-preroll-gop2.json"
echo "  $POC_DIR/runtime/event-preroll-gop5.json"
echo "  $POC_DIR/runtime/event-docker-compose.log"
