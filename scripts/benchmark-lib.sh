#!/usr/bin/env bash
set -euo pipefail

size_to_bytes() {
  local raw="$1"
  local number unit

  number="$(
    printf '%s' "$raw" |
      sed -E 's/^([0-9]+([.][0-9]+)?).*/\1/'
  )"
  unit="$(
    printf '%s' "$raw" |
      sed -E 's/^[0-9]+([.][0-9]+)?[[:space:]]*//'
  )"

  awk -v n="$number" -v u="$unit" '
    BEGIN {
      if (u == "B" || u == "") m = 1;
      else if (u == "kB" || u == "KB") m = 1000;
      else if (u == "MB") m = 1000000;
      else if (u == "GB") m = 1000000000;
      else if (u == "KiB") m = 1024;
      else if (u == "MiB") m = 1048576;
      else if (u == "GiB") m = 1073741824;
      else if (u == "TiB") m = 1099511627776;
      else exit 2;
      printf "%.0f\n", n * m;
    }
  '
}
