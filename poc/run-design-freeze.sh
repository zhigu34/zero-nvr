#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

usage() {
  cat <<'EOF'
Usage:
  sh poc/run-design-freeze.sh <poc>

POC selectors:
  01   ZLM recording + API restart + hook reconciliation + POC-08 sharing
  02   fMP4 abnormal termination
  03   EVENT_ONLY pre-roll + POC-04 overlap extension
  04   alias of 03
  05   timeline precision + POC-06 ZLM VOD seek
  06   alias of 05
  07   remote restore playback
  08   alias of 01
  09   SQLite 8/16-camera load
  10   recovery reconciliation
  all  run each unique harness once in design-freeze order
EOF
}

run_01() {
  echo "== POC-01 + POC-08 =="
  (
    cd "$ROOT_DIR/poc/zlm-recording"
    sh ./scripts/run.sh
  )
}

run_02() {
  echo "== POC-02 =="
  (
    cd "$ROOT_DIR/poc/zlm-recording"
    sh ./scripts/run-fmp4-crash.sh
  )
}

run_03() {
  echo "== POC-03 + POC-04 =="
  (
    cd "$ROOT_DIR/poc/zlm-recording"
    sh ./scripts/run-event-preroll.sh
  )
}

run_05() {
  echo "== POC-05 + POC-06 =="
  (
    cd "$ROOT_DIR/poc/zlm-recording"
    sh ./scripts/run-timeline-playback.sh
  )
}

run_07() {
  echo "== POC-07 =="
  (
    cd "$ROOT_DIR/poc/zlm-recording"
    sh ./scripts/run-remote-restore.sh
  )
}

run_09() {
  echo "== POC-09 =="
  (
    cd "$ROOT_DIR/poc/sqlite-load"
    sh ./run.sh
  )
}

run_10() {
  echo "== POC-10 =="
  (
    cd "$ROOT_DIR/poc/zlm-recording"
    sh ./scripts/run-reconciliation.sh
  )
}

selector=${1:-}

case "$selector" in
  01|1|08|8)
    run_01
    ;;
  02|2)
    run_02
    ;;
  03|3|04|4)
    run_03
    ;;
  05|5|06|6)
    run_05
    ;;
  07|7)
    run_07
    ;;
  09|9)
    run_09
    ;;
  10)
    run_10
    ;;
  all)
    run_01
    run_02
    run_03
    run_05
    run_07
    run_09
    run_10
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
