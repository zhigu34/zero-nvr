#!/bin/sh
set -u

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

STAMP=$(date -u +"%Y%m%dT%H%M%SZ")
ARCHIVE_ROOT="$SCRIPT_DIR/runtime-results/$STAMP"
SUMMARY="$ARCHIVE_ROOT/summary.tsv"

mkdir -p "$ARCHIVE_ROOT"
printf "group\trunner\texit_code\n" > "$SUMMARY"

FAILED=0

archive_runtime() {
  group="$1"
  source_dir="$2"
  destination="$ARCHIVE_ROOT/$group"

  mkdir -p "$destination"

  if [ ! -d "$source_dir" ]; then
    return
  fi

  # Preserve compact evidence/log/config outputs. Large generated media stays
  # in the disposable per-harness runtime directory unless explicitly copied
  # by the operator.
  for pattern in '*.json' '*.log' '*.txt' '*.sqlite3' '*.db'; do
    for file in "$source_dir"/$pattern; do
      [ -f "$file" ] || continue
      cp -p "$file" "$destination/" 2>/dev/null || true
    done
  done

  # Keep a deterministic manifest of generated media/cache files without
  # duplicating potentially large MP4 payloads into the aggregate archive.
  (
    cd "$source_dir" 2>/dev/null || exit 0
    find . -type f \( -name '*.mp4' -o -name '*.partial' \) -print 2>/dev/null |
      while IFS= read -r file; do
        size=$(wc -c < "$file" 2>/dev/null || echo 0)
        printf '%s\t%s bytes\n' "$file" "$size"
      done |
      sort
  ) > "$destination/media-manifest.tsv" || true
}

run_group() {
  group="$1"
  runner="$2"
  runtime_dir="$3"

  echo
  echo "============================================================"
  echo "POC group: $group"
  echo "Runner:    $runner"
  echo "============================================================"

  set +e
  (
    cd "$ROOT_DIR"
    sh "$runner"
  )
  rc=$?
  set -e

  archive_runtime "$group" "$runtime_dir"
  printf "%s\t%s\t%s\n" "$group" "$runner" "$rc" >> "$SUMMARY"

  if [ "$rc" -ne 0 ]; then
    FAILED=1
    echo "Group $group FAILED with exit code $rc" >&2
  else
    echo "Group $group runner completed successfully."
  fi
}

# Do not let one failed architecture experiment prevent later independent
# experiments from producing evidence.
set -e

run_group \
  "01-08-recording-stream-sharing" \
  "poc/zlm-recording/scripts/run.sh" \
  "$ROOT_DIR/poc/zlm-recording/runtime"

run_group \
  "02-fmp4-crash" \
  "poc/zlm-recording/scripts/run-fmp4-crash.sh" \
  "$ROOT_DIR/poc/zlm-recording/runtime"

run_group \
  "03-04-event-preroll" \
  "poc/zlm-recording/scripts/run-event-preroll.sh" \
  "$ROOT_DIR/poc/zlm-recording/runtime"

run_group \
  "05-06-timeline-vod" \
  "poc/zlm-recording/scripts/run-timeline-playback.sh" \
  "$ROOT_DIR/poc/zlm-recording/runtime"

run_group \
  "07-remote-restore" \
  "poc/zlm-recording/scripts/run-remote-restore.sh" \
  "$ROOT_DIR/poc/zlm-recording/runtime"

run_group \
  "09-sqlite-load" \
  "poc/sqlite-load/run.sh" \
  "$ROOT_DIR/poc/sqlite-load/runtime"

run_group \
  "10-reconciliation" \
  "poc/zlm-recording/scripts/run-reconciliation.sh" \
  "$ROOT_DIR/poc/zlm-recording/runtime"

echo
echo "Aggregate evidence:"
echo "  $ARCHIVE_ROOT"
echo "Summary:"
cat "$SUMMARY"

if [ "$FAILED" -ne 0 ]; then
  echo
  echo "One or more POC runners failed. Result documents must remain NOT RUN/FAIL"
  echo "until the evidence is reviewed and recorded."
  exit 1
fi

echo
echo "All runner-level assertions completed successfully."
echo "This does NOT automatically change docs/poc-results/* to PASS."
