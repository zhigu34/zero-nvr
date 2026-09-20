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

collect_common_evidence() {
  docker compose ps > runtime/fmp4-docker-compose-ps.txt 2>&1 || true
  docker compose logs --no-color > runtime/fmp4-docker-compose.log 2>&1 || true
}

cleanup() {
  collect_common_evidence
  if [ "${KEEP_RUNNING:-0}" != "1" ]; then
    docker compose down -v --remove-orphans >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

docker compose down -v --remove-orphans >/dev/null 2>&1 || true
rm -rf runtime
mkdir -p runtime/recordings runtime/vod runtime/playback-cache

echo "Running ordinary MP4 SIGKILL baseline..."
export POC_ZLM_ENABLE_FMP4=0
docker compose up -d --build
docker compose exec -T poc-api python /app/mp4_crash_baseline.py prepare
echo "SIGKILL ordinary-MP4 ZLMediaKit while file is open..."
docker compose kill -s KILL zlm
sleep 2
docker compose exec -T poc-api python /app/mp4_crash_baseline.py inspect
docker compose up -d zlm
docker compose exec -T poc-api python /app/mp4_crash_baseline.py verify-vod
docker compose logs --no-color > runtime/mp4-baseline-docker-compose.log 2>&1 || true

echo "Recreating ZLM with fMP4 enabled..."
docker compose down -v --remove-orphans
rm -rf runtime/recordings runtime/vod runtime/playback-cache
mkdir -p runtime/recordings runtime/vod runtime/playback-cache
export POC_ZLM_ENABLE_FMP4=1
docker compose up -d --build

echo "Preparing normal and in-progress fMP4 samples..."
docker compose exec -T poc-api python /app/fmp4_prepare.py
echo "SIGKILL fMP4 ZLMediaKit while file is open..."
docker compose kill -s KILL zlm
sleep 2
docker compose exec -T poc-api python /app/fmp4_after_crash.py inspect

echo "Restarting ZLMediaKit and verifying fMP4 VOD..."
docker compose up -d zlm
docker compose exec -T poc-api python /app/fmp4_after_crash.py verify-vod

echo "Comparing ordinary MP4 and fMP4 crash recoverability..."
docker compose exec -T poc-api python /app/crash_compare.py

collect_common_evidence

ZLM_CID=$(docker compose ps -q zlm 2>/dev/null || true)
MTX_CID=$(docker compose ps -q mediamtx 2>/dev/null || true)
if [ -n "$ZLM_CID" ]; then
  docker inspect "$ZLM_CID" > runtime/fmp4-zlm-container-inspect.json 2>&1 || true
fi
if [ -n "$MTX_CID" ]; then
  docker inspect "$MTX_CID" > runtime/fmp4-mediamtx-container-inspect.json 2>&1 || true
fi

echo
echo "Crash-recovery evidence:"
echo "  $POC_DIR/runtime/mp4-baseline-evidence.json"
echo "  $POC_DIR/runtime/fmp4-evidence.json"
echo "  $POC_DIR/runtime/mp4-vs-fmp4-comparison.json"
echo "  $POC_DIR/runtime/fmp4-docker-compose.log"
