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

docker compose down -v --remove-orphans >/dev/null 2>&1 || true

rm -rf runtime
mkdir -p runtime/recordings runtime/vod

docker compose up -d --build

set +e
docker compose exec -T poc-api python /app/verify.py
VERIFY_RC=$?
set -e

docker compose ps > runtime/docker-compose-ps.txt 2>&1 || true
docker compose logs --no-color > runtime/docker-compose.log 2>&1 || true

ZLM_CID=$(docker compose ps -q zlm 2>/dev/null || true)
MTX_CID=$(docker compose ps -q mediamtx 2>/dev/null || true)

if [ -n "$ZLM_CID" ]; then
  docker inspect "$ZLM_CID" > runtime/zlm-container-inspect.json 2>&1 || true
fi
if [ -n "$MTX_CID" ]; then
  docker inspect "$MTX_CID" > runtime/mediamtx-container-inspect.json 2>&1 || true
fi

echo
echo "Evidence:"
echo "  $POC_DIR/runtime/evidence.json"
echo "  $POC_DIR/runtime/docker-compose.log"

if [ "${KEEP_RUNNING:-0}" != "1" ]; then
  docker compose down -v --remove-orphans
else
  echo "KEEP_RUNNING=1: containers left running for inspection."
fi

exit "$VERIFY_RC"
