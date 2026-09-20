#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
POC_DIR=$SCRIPT_DIR
cd "$POC_DIR"

rm -rf runtime
mkdir -p runtime

docker run --rm \
  -e POC_SQLITE_RUN_SECONDS="${POC_SQLITE_RUN_SECONDS:-30}" \
  -e POC_SQLITE_PRELOAD_DAYS="${POC_SQLITE_PRELOAD_DAYS:-30}" \
  -e POC_SQLITE_EVENTS_PER_CAMERA_DAY="${POC_SQLITE_EVENTS_PER_CAMERA_DAY:-100}" \
  -v "$POC_DIR:/poc:ro" \
  -v "$POC_DIR/runtime:/runtime" \
  python:3.13-slim \
  python /poc/run.py --all

echo
echo "SQLite load evidence:"
echo "  $POC_DIR/runtime/sqlite-load-evidence.json"
