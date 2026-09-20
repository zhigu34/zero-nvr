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

# Override the ordinary POC mode for this run.
export POC_ZLM_ENABLE_FMP4=1

collect_evidence() {
  docker compose ps > runtime/fmp4-docker-compose-ps.txt 2>&1 || true
  docker compose logs --no-color > runtime/fmp4-docker-compose.log 2>&1 || true
  ZLM_CID=$(docker compose ps -q zlm 2>/dev/null || true)
  MTX_CID=$(docker compose ps -q mediamtx 2>/dev/null || true)
  if [ -n "$ZLM_CID" ]; then
    docker inspect "$ZLM_CID" > runtime/fmp4-zlm-container-inspect.json 2>&1 || true
  fi
  if [ -n "$MTX_CID" ]; then
    docker inspect "$MTX_CID" > runtime/fmp4-mediamtx-container-inspect.json 2>&1 || true
  fi
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

echo "Preparing normal and in-progress fMP4 samples..."
docker compose exec -T poc-api python /app/fmp4_prepare.py

echo "Sending SIGKILL to ZLMediaKit while fMP4 is open..."
docker compose kill -s KILL zlm
sleep 2

echo "Inspecting interrupted fMP4 before ZLM restart..."
docker compose exec -T poc-api python /app/fmp4_after_crash.py inspect

echo "Restarting ZLMediaKit and verifying VOD..."
docker compose up -d zlm
docker compose exec -T poc-api python /app/fmp4_after_crash.py verify-vod

collect_evidence

echo
echo "fMP4 evidence:"
echo "  $POC_DIR/runtime/fmp4-evidence.json"
echo "  $POC_DIR/runtime/fmp4-docker-compose.log"
