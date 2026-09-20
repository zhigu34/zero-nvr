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
  docker compose ps > runtime/remote-docker-compose-ps.txt 2>&1 || true
  docker compose logs --no-color > runtime/remote-docker-compose.log 2>&1 || true
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
mkdir -p runtime/recordings runtime/vod runtime/playback-cache runtime/remote runtime/remote-staging

docker compose up -d --build

echo "Creating local segments and archiving two samples through rclone/WebDAV..."
docker compose exec -T poc-api python /app/remote_restore.py prepare

echo "Testing interrupted restore, retry, ZLM VOD, prefetch, and cache eviction..."
docker compose exec -T poc-api python /app/remote_restore.py restore

echo "Taking the remote offline while local recording remains active..."
docker compose kill -s KILL rclone-remote
sleep 10

docker compose exec -T poc-api python /app/remote_restore.py failure-check

collect_evidence

echo
echo "Remote restore evidence:"
echo "  $POC_DIR/runtime/remote-restore-evidence.json"
echo "  $POC_DIR/runtime/remote-docker-compose.log"
