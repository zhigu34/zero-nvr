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
  docker compose ps > runtime/reconcile-docker-compose-ps.txt 2>&1 || true
  docker compose logs --no-color > runtime/reconcile-docker-compose.log 2>&1 || true
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
mkdir -p runtime/recordings runtime/vod runtime/playback-cache runtime/remote

docker compose up -d --build

echo "Preparing reconciliation stream and deliberate lost hook..."
docker compose exec -T poc-api python /app/reconciliation_faults.py prepare

echo "Stopping API while ZLM continues recording..."
docker compose stop poc-api
sleep 18
docker compose start poc-api

echo "Waiting for API health after restart..."
i=0
until docker compose exec -T poc-api python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).read()" >/dev/null 2>&1; do
  i=$((i+1))
  if [ "$i" -ge 30 ]; then
    echo "POC API did not recover after restart" >&2
    exit 1
  fi
  sleep 1
done

echo "Holding SQLite write lock long enough to make hook writes fail/retry..."
rm -f runtime/db-lock-started.json runtime/db-lock-finished.json
docker compose exec -d poc-api python /app/reconciliation_faults.py hold-lock --seconds 22

i=0
while [ ! -f runtime/db-lock-started.json ]; do
  i=$((i+1))
  if [ "$i" -ge 30 ]; then
    echo "SQLite lock process did not acquire its write lock" >&2
    exit 1
  fi
  sleep 1
done

sleep 24

echo "Creating stale/missing/proven-orphan/ambiguous-orphan fixtures..."
docker compose exec -T poc-api python /app/reconciliation_faults.py create-fixtures

echo "Simulating reconciliation worker/process death after one committed mutation..."
set +e
docker compose exec -T poc-api python /app/reconciliation_faults.py reconcile --crash-after 1
CRASH_RC=$?
set -e
if [ "$CRASH_RC" -eq 0 ]; then
  echo "Expected simulated reconciliation crash did not happen" >&2
  exit 1
fi

echo "Restarting reconciliation and verifying convergence/idempotency..."
docker compose exec -T poc-api python /app/reconciliation_faults.py verify

collect_evidence

echo
echo "Reconciliation evidence:"
echo "  $POC_DIR/runtime/reconciliation-evidence.json"
echo "  $POC_DIR/runtime/reconciliation-runs.json"
echo "  $POC_DIR/runtime/reconcile-docker-compose.log"
