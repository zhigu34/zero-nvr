#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
export ZERO_NVR_ENV_FILE="$TMP_DIR/.env"

cp "$ROOT_DIR/.env.example" "$ZERO_NVR_ENV_FILE"

# shellcheck source=scripts/lib.sh
. "$ROOT_DIR/scripts/lib.sh"
# shellcheck source=scripts/port-preflight.sh
. "$ROOT_DIR/scripts/port-preflight.sh"

set_env_value() {
  local key="$1"
  local value="$2"
  local tmp="$TMP_DIR/env.tmp"
  awk -v key="$key" -v value="$value" '
    BEGIN { found=0 }
    index($0, key "=") == 1 {
      print key "=" value
      found=1
      next
    }
    { print }
    END {
      if (!found) print key "=" value
    }
  ' "$ENV_FILE" > "$tmp"
  mv "$tmp" "$ENV_FILE"
}

port_preflight_service_owns_endpoint() {
  return 1
}

port_preflight_service_owns_range() {
  return 1
}

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

# Shipped Core defaults must not collide with one another.
port_socket_available() {
  return 0
}
port_preflight_reset
ensure_port_setting   ZERO_NVR_API_PORT 8000 0.0.0.0 tcp zero-nvr "Web/API"
ensure_port_setting   ZERO_NVR_ZLM_WEBRTC_PORT 8001 0.0.0.0 tcp,udp zlmediakit "ZLM WebRTC"

# Configured collisions are rejected even when the host itself is empty.
port_preflight_reset
port_preflight_reserve   ZERO_NVR_API_PORT "Web/API" 0.0.0.0 8000 tcp
if port_preflight_candidate_available   ZERO_NVR_ZLM_WEBRTC_PORT 0.0.0.0 8000 tcp,udp zlmediakit
then
  fail "configured TCP collision was accepted"
fi

# Non-interactive conflicts fail rather than waiting for input.
port_preflight_is_interactive() {
  return 1
}
port_socket_available() {
  [[ "$2" != "8000" ]]
}
port_preflight_reset
if ensure_port_setting   ZERO_NVR_API_PORT 8000 0.0.0.0 tcp zero-nvr "Web/API"   >/dev/null 2>&1
then
  fail "non-interactive occupied port was accepted"
fi

# Interactive conflicts accept the suggested free port and persist it.
port_preflight_is_interactive() {
  return 0
}
port_preflight_reset
set_env_value ZERO_NVR_API_PORT 8000
ensure_port_setting   ZERO_NVR_API_PORT 8000 0.0.0.0 tcp zero-nvr "Web/API"   <<< "" >/dev/null
[[ "$(env_get ZERO_NVR_API_PORT)" == "8001" ]]   || fail "interactive suggestion was not persisted"

# A UDP conflict also makes a dual-protocol port unavailable.
port_preflight_reset
port_socket_available() {
  if [[ "$2" == "9000" && "$3" == "udp" ]]; then
    return 1
  fi
  return 0
}
if port_preflight_candidate_available   TEST_DUAL 0.0.0.0 9000 tcp,udp test-service
then
  fail "UDP half of a dual-protocol port was ignored"
fi

# TURN relay ranges reject any occupied UDP member.
port_preflight_is_interactive() {
  return 1
}
port_preflight_reset
port_socket_available() {
  [[ "$2" != "49170" ]]
}
set_env_value ZERO_NVR_TURN_RELAY_MIN_PORT 49160
set_env_value ZERO_NVR_TURN_RELAY_MAX_PORT 49200
if ensure_udp_range_setting   ZERO_NVR_TURN_RELAY_MIN_PORT ZERO_NVR_TURN_RELAY_MAX_PORT   49160 49200 0.0.0.0 coturn "TURN relay range"   >/dev/null 2>&1
then
  fail "occupied TURN relay range was accepted"
fi

echo "port preflight tests passed"
