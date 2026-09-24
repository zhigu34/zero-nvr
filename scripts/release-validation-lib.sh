#!/usr/bin/env bash
set -euo pipefail

persist_release_validation_report() {
  local kind="$1"
  local report="$2"
  local data_root report_dir target tmp

  case "$kind" in
    benchmark|soak|resource-baseline)
      ;;
    *)
      echo "error: invalid release validation report kind: $kind" >&2
      return 2
      ;;
  esac

  data_root="$(host_path "$(env_get ZERO_NVR_DATA_PATH)")"
  report_dir="$data_root/release-validation"
  target="$report_dir/latest-$kind.json"

  mkdir -p "$report_dir"
  tmp="$(mktemp "$report_dir/.latest-$kind.XXXXXX")"
  printf '%s\n' "$report" > "$tmp"
  chmod 640 "$tmp"
  mv -f "$tmp" "$target"
}
