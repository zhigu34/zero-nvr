#!/usr/bin/env bash
set -euo pipefail

# Host-published port preflight helpers for deploy.sh.
#
# The caller must provide env_get() and set_env_value(). Docker is expected to
# be available because deploy.sh runs this after its Docker preflight.

declare -a PORT_PREFLIGHT_RESERVED=()
PORT_PREFLIGHT_REASON=""
PORT_PREFLIGHT_SUGGESTED=""

port_preflight_reset() {
  PORT_PREFLIGHT_RESERVED=()
  PORT_PREFLIGHT_REASON=""
  PORT_PREFLIGHT_SUGGESTED=""
}

port_preflight_is_interactive() {
  [[ -t 0 && -t 1 ]]
}

port_preflight_valid_port() {
  local port="${1:-}"
  [[ "$port" =~ ^[0-9]+$ ]] \
    && (( port >= 1 && port <= 65535 ))
}

port_preflight_bind_overlap() {
  local left="${1:-0.0.0.0}"
  local right="${2:-0.0.0.0}"

  case "$left" in
    ""|"*"|"0.0.0.0"|"::"|"[::]")
      return 0
      ;;
  esac
  case "$right" in
    ""|"*"|"0.0.0.0"|"::"|"[::]")
      return 0
      ;;
  esac
  [[ "$left" == "$right" ]]
}

port_preflight_service_ports() {
  local service="$1"
  docker ps \
    --filter "label=com.docker.compose.project=zero-nvr" \
    --filter "label=com.docker.compose.service=$service" \
    --format '{{.Ports}}' \
    2>/dev/null || true
}

port_preflight_service_owns_endpoint() {
  local service="$1"
  local port="$2"
  local protocol="$3"
  local published

  published="$(port_preflight_service_ports "$service")"
  [[ -n "$published" ]] || return 1
  printf '%s\n' "$published" \
    | grep -Eq ":${port}->[0-9]+/${protocol}([, ]|$)"
}

port_preflight_service_owns_range() {
  local service="$1"
  local first="$2"
  local last="$3"
  local protocol="$4"
  local published

  published="$(port_preflight_service_ports "$service")"
  [[ -n "$published" ]] || return 1
  printf '%s\n' "$published" \
    | grep -Eq ":${first}-${last}->[0-9]+-[0-9]+/${protocol}([, ]|$)"
}

port_socket_available() {
  local bind_address="$1"
  local port="$2"
  local protocol="$3"

  if command -v python3 >/dev/null 2>&1; then
    python3 - "$bind_address" "$port" "$protocol" <<'PY'
import socket
import sys

bind_address = sys.argv[1]
port = int(sys.argv[2])
protocol = sys.argv[3]

if bind_address in {"", "*"}:
    bind_address = "0.0.0.0"
if bind_address == "[::]":
    bind_address = "::"

family = socket.AF_INET6 if ":" in bind_address else socket.AF_INET
sock_type = socket.SOCK_STREAM if protocol == "tcp" else socket.SOCK_DGRAM
sock = socket.socket(family, sock_type)
try:
    sock.bind((bind_address, port))
    if protocol == "tcp":
        sock.listen(1)
except OSError:
    sys.exit(1)
finally:
    sock.close()
PY
    return $?
  fi

  if command -v ss >/dev/null 2>&1; then
    local mode
    if [[ "$protocol" == "tcp" ]]; then
      mode="-ltn"
    else
      mode="-lun"
    fi
    if ss -H "$mode" 2>/dev/null \
      | awk -v port="$port" '
          $4 ~ (":" port "$") { found=1 }
          END { exit found ? 0 : 1 }
        '
    then
      return 1
    fi
    return 0
  fi

  echo "error: port preflight requires python3 or ss (iproute2)" >&2
  return 2
}

port_preflight_reservation_conflict() {
  local key="$1"
  local bind_address="$2"
  local port="$3"
  local protocol="$4"
  local entry r_protocol r_bind r_port r_key r_label

  for entry in "${PORT_PREFLIGHT_RESERVED[@]}"; do
    IFS='|' read -r \
      r_protocol r_bind r_port r_key r_label <<< "$entry"
    [[ "$r_protocol" == "$protocol" ]] || continue
    [[ "$r_port" == "$port" ]] || continue
    port_preflight_bind_overlap "$bind_address" "$r_bind" || continue

    PORT_PREFLIGHT_REASON="conflicts with $r_key ($r_label) on $r_bind:$r_port/$r_protocol"
    return 0
  done
  return 1
}

port_preflight_reserve() {
  local key="$1"
  local label="$2"
  local bind_address="$3"
  local port="$4"
  local protocols="$5"
  local protocol
  local -a values

  IFS=',' read -r -a values <<< "$protocols"
  for protocol in "${values[@]}"; do
    PORT_PREFLIGHT_RESERVED+=(
      "$protocol|$bind_address|$port|$key|$label"
    )
  done
}

port_preflight_candidate_available() {
  local key="$1"
  local bind_address="$2"
  local port="$3"
  local protocols="$4"
  local service="$5"
  local protocol status
  local -a values

  PORT_PREFLIGHT_REASON=""

  if ! port_preflight_valid_port "$port"; then
    PORT_PREFLIGHT_REASON="must be an integer between 1 and 65535"
    return 1
  fi

  IFS=',' read -r -a values <<< "$protocols"
  for protocol in "${values[@]}"; do
    if port_preflight_reservation_conflict \
      "$key" "$bind_address" "$port" "$protocol"
    then
      return 1
    fi

    if port_preflight_service_owns_endpoint \
      "$service" "$port" "$protocol"
    then
      continue
    fi

    if port_socket_available "$bind_address" "$port" "$protocol"; then
      continue
    else
      status=$?
      if (( status == 2 )); then
        PORT_PREFLIGHT_REASON="cannot probe $bind_address:$port/$protocol; install python3 or iproute2"
      else
        PORT_PREFLIGHT_REASON="$bind_address:$port/$protocol is already in use"
      fi
      return 1
    fi
  done
  return 0
}

port_preflight_find_port() {
  local key="$1"
  local bind_address="$2"
  local current="$3"
  local protocols="$4"
  local service="$5"
  local candidate offset

  PORT_PREFLIGHT_SUGGESTED=""
  if port_preflight_valid_port "$current"; then
    candidate=$(( current + 1 ))
  else
    candidate=1024
  fi
  if (( candidate > 65535 )); then
    candidate=1024
  fi

  for (( offset=0; offset<1024; offset++ )); do
    if (( candidate > 65535 )); then
      candidate=1024
    fi
    if port_preflight_candidate_available \
      "$key" "$bind_address" "$candidate" "$protocols" "$service"
    then
      PORT_PREFLIGHT_SUGGESTED="$candidate"
      return 0
    fi
    candidate=$(( candidate + 1 ))
  done
  return 1
}

ensure_port_setting() {
  local key="$1"
  local fallback="$2"
  local bind_address="$3"
  local protocols="$4"
  local service="$5"
  local label="$6"
  local value suggestion answer

  value="$(env_get "$key" "$fallback")"
  if port_preflight_candidate_available \
    "$key" "$bind_address" "$value" "$protocols" "$service"
  then
    port_preflight_reserve \
      "$key" "$label" "$bind_address" "$value" "$protocols"
    return 0
  fi

  local initial_reason="$PORT_PREFLIGHT_REASON"
  suggestion=""
  if port_preflight_find_port \
    "$key" "$bind_address" "$value" "$protocols" "$service"
  then
    suggestion="$PORT_PREFLIGHT_SUGGESTED"
  fi

  if ! port_preflight_is_interactive; then
    echo "error: $key=$value cannot be used: $initial_reason" >&2
    if [[ -n "$suggestion" ]]; then
      echo "suggestion: set $key=$suggestion in $ENV_FILE and retry" >&2
    fi
    return 1
  fi

  echo "Port conflict for $label:"
  echo "  $key=$value"
  echo "  $initial_reason"

  while true; do
    if [[ -n "$suggestion" ]]; then
      printf 'Enter another port [%s]: ' "$suggestion"
    else
      printf 'Enter another port: '
    fi
    if ! IFS= read -r answer; then
      echo "error: no port was provided" >&2
      return 1
    fi
    if [[ -z "$answer" ]]; then
      answer="$suggestion"
    fi
    if [[ -z "$answer" ]]; then
      echo "No available suggestion was found; enter a port explicitly." >&2
      continue
    fi

    if port_preflight_candidate_available \
      "$key" "$bind_address" "$answer" "$protocols" "$service"
    then
      set_env_value "$key" "$answer"
      port_preflight_reserve \
        "$key" "$label" "$bind_address" "$answer" "$protocols"
      echo "saved: $key=$answer"
      return 0
    fi
    echo "Port $answer cannot be used: $PORT_PREFLIGHT_REASON" >&2
  done
}

port_preflight_range_available() {
  local min_key="$1"
  local max_key="$2"
  local bind_address="$3"
  local first="$4"
  local last="$5"
  local service="$6"
  local port status

  PORT_PREFLIGHT_REASON=""

  if ! port_preflight_valid_port "$first" \
    || ! port_preflight_valid_port "$last" \
    || (( first > last ))
  then
    PORT_PREFLIGHT_REASON="range must be between 1 and 65535 with min <= max"
    return 1
  fi

  for (( port=first; port<=last; port++ )); do
    if port_preflight_reservation_conflict \
      "$min_key/$max_key" "$bind_address" "$port" "udp"
    then
      return 1
    fi
  done

  if port_preflight_service_owns_range \
    "$service" "$first" "$last" "udp"
  then
    return 0
  fi

  for (( port=first; port<=last; port++ )); do
    if port_socket_available "$bind_address" "$port" "udp"; then
      continue
    else
      status=$?
      if (( status == 2 )); then
        PORT_PREFLIGHT_REASON="cannot probe $bind_address:$port/udp; install python3 or iproute2"
      else
        PORT_PREFLIGHT_REASON="$bind_address:$port/udp is already in use"
      fi
      return 1
    fi
  done
  return 0
}

port_preflight_reserve_range() {
  local min_key="$1"
  local max_key="$2"
  local label="$3"
  local bind_address="$4"
  local first="$5"
  local last="$6"
  local port

  for (( port=first; port<=last; port++ )); do
    PORT_PREFLIGHT_RESERVED+=(
      "udp|$bind_address|$port|$min_key/$max_key|$label"
    )
  done
}

port_preflight_find_range() {
  local min_key="$1"
  local max_key="$2"
  local bind_address="$3"
  local first="$4"
  local last="$5"
  local service="$6"
  local width candidate candidate_last attempt

  PORT_PREFLIGHT_SUGGESTED=""
  if ! port_preflight_valid_port "$first" \
    || ! port_preflight_valid_port "$last" \
    || (( first > last ))
  then
    width=40
    candidate=49160
  else
    width=$(( last - first ))
    candidate=$(( last + 1 ))
  fi

  for (( attempt=0; attempt<128; attempt++ )); do
    candidate_last=$(( candidate + width ))
    if (( candidate_last > 65535 )); then
      candidate=49160
      candidate_last=$(( candidate + width ))
    fi
    if port_preflight_range_available \
      "$min_key" "$max_key" "$bind_address" \
      "$candidate" "$candidate_last" "$service"
    then
      PORT_PREFLIGHT_SUGGESTED="$candidate"
      return 0
    fi
    candidate=$(( candidate + width + 1 ))
  done
  return 1
}

ensure_udp_range_setting() {
  local min_key="$1"
  local max_key="$2"
  local min_fallback="$3"
  local max_fallback="$4"
  local bind_address="$5"
  local service="$6"
  local label="$7"
  local first last width suggestion answer candidate_last

  first="$(env_get "$min_key" "$min_fallback")"
  last="$(env_get "$max_key" "$max_fallback")"

  if port_preflight_range_available \
    "$min_key" "$max_key" "$bind_address" "$first" "$last" "$service"
  then
    port_preflight_reserve_range \
      "$min_key" "$max_key" "$label" "$bind_address" "$first" "$last"
    return 0
  fi

  local initial_reason="$PORT_PREFLIGHT_REASON"
  suggestion=""
  if port_preflight_find_range \
    "$min_key" "$max_key" "$bind_address" "$first" "$last" "$service"
  then
    suggestion="$PORT_PREFLIGHT_SUGGESTED"
  fi

  if port_preflight_valid_port "$first" \
    && port_preflight_valid_port "$last" \
    && (( first <= last ))
  then
    width=$(( last - first ))
  else
    width=40
  fi

  if ! port_preflight_is_interactive; then
    echo "error: $min_key=$first $max_key=$last cannot be used: $initial_reason" >&2
    if [[ -n "$suggestion" ]]; then
      echo "suggestion: move the relay range start to $suggestion in $ENV_FILE" >&2
    fi
    return 1
  fi

  echo "Port conflict for $label:"
  echo "  $min_key=$first"
  echo "  $max_key=$last"
  echo "  $initial_reason"

  while true; do
    if [[ -n "$suggestion" ]]; then
      printf 'Enter a new relay range start [%s]: ' "$suggestion"
    else
      printf 'Enter a new relay range start: '
    fi
    if ! IFS= read -r answer; then
      echo "error: no relay range start was provided" >&2
      return 1
    fi
    if [[ -z "$answer" ]]; then
      answer="$suggestion"
    fi
    if ! port_preflight_valid_port "$answer"; then
      echo "Relay range start must be between 1 and 65535." >&2
      continue
    fi
    candidate_last=$(( answer + width ))
    if (( candidate_last > 65535 )); then
      echo "Relay range would exceed port 65535." >&2
      continue
    fi

    if port_preflight_range_available \
      "$min_key" "$max_key" "$bind_address" \
      "$answer" "$candidate_last" "$service"
    then
      set_env_value "$min_key" "$answer"
      set_env_value "$max_key" "$candidate_last"
      port_preflight_reserve_range \
        "$min_key" "$max_key" "$label" "$bind_address" \
        "$answer" "$candidate_last"
      echo "saved: $min_key=$answer"
      echo "saved: $max_key=$candidate_last"
      return 0
    fi
    echo "Relay range cannot be used: $PORT_PREFLIGHT_REASON" >&2
  done
}
