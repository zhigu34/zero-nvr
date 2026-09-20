#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
# shellcheck source=scripts/lib.sh
. "$SCRIPT_DIR/lib.sh"

failures=0

ok() { printf 'OK   %s\n' "$*"; }
warn() { printf 'WARN %s\n' "$*" >&2; }
fail() {
  printf 'FAIL %s\n' "$*" >&2
  failures=$((failures + 1))
}

if require_command docker; then
  ok "docker command"
else
  fail "docker command unavailable"
fi

if docker compose version >/dev/null 2>&1; then
  ok "docker compose"
else
  fail "docker compose plugin unavailable"
fi

if docker info >/dev/null 2>&1; then
  ok "docker daemon"
else
  fail "docker daemon unavailable"
fi

if [[ ! -f "$ENV_FILE" ]]; then
  fail ".env is missing"
else
  ok ".env exists"
fi

for key in   ZERO_NVR_SECRET_KEY   ZERO_NVR_ZLM_API_SECRET   ZERO_NVR_ZLM_HOOK_SECRET
do
  value="$(env_get "$key")"
  if [[ ${#value} -lt 32 ]]; then
    fail "$key is missing or too short"
  else
    ok "$key configured"
  fi
done

for key in   ZERO_NVR_DATA_PATH   ZERO_NVR_CACHE_PATH   ZERO_NVR_RECORDINGS_PATH
do
  value="$(env_get "$key")"
  path="$(host_path "$value")"
  if [[ -d "$path" && -w "$path" ]]; then
    ok "$key writable: $path"
  else
    fail "$key not writable: $path"
  fi
done

zlm_config="$ROOT_DIR/deploy/zlm/config.ini"
if [[ -f "$zlm_config" ]]; then
  if grep -Fxq "apiDebug=0" "$zlm_config" \
    && grep -Fxq "enableFmp4=1" "$zlm_config"; then
    ok "generated ZLM config"
  else
    fail "generated ZLM config is incomplete"
  fi
else
  fail "generated ZLM config is missing"
fi

if compose config --quiet >/dev/null 2>&1; then
  ok "docker compose config"
else
  fail "docker compose config is invalid"
fi

volume="$(
  docker volume ls -q \
    --filter label=com.docker.compose.project=zero-nvr \
    --filter label=com.docker.compose.volume=zero-nvr-prebuffer \
    | head -n 1
)"
if [[ -n "$volume" ]]; then
  volume_type="$(
    docker volume inspect "$volume" \
      --format '{{ index .Options "type" }}' 2>/dev/null || true
  )"
  if [[ "$volume_type" == "tmpfs" ]]; then
    ok "shared prebuffer volume is tmpfs"
  else
    fail "shared prebuffer volume is not tmpfs"
  fi
else
  warn "prebuffer volume is not created yet"
fi

if [[ -n "$(compose ps -q zero-nvr 2>/dev/null || true)" ]]; then
  if compose exec -T zero-nvr \
    curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
    ok "zero-nvr API health"
  else
    fail "zero-nvr API is not healthy"
  fi
fi

if [[ -n "$(compose ps -q zlmediakit 2>/dev/null || true)" ]]; then
  if compose exec -T zlmediakit sh -ec '
    curl -fsS -X POST       --data-urlencode "secret=$ZERO_NVR_ZLM_API_SECRET"       http://127.0.0.1/index/api/version >/dev/null
  ' >/dev/null 2>&1; then
    ok "ZLMediaKit API health"
  else
    fail "ZLMediaKit API is not healthy"
  fi
fi

recordings="$(host_path "$(env_get ZERO_NVR_RECORDINGS_PATH)")"
if [[ -d "$recordings" ]]; then
  available_kb="$(df -Pk "$recordings" | awk 'NR==2 {print $4}')"
  if [[ "${available_kb:-0}" -lt 2097152 ]]; then
    warn "recording filesystem has less than 2 GiB free"
  else
    ok "recording filesystem free space"
  fi
fi

if command -v timedatectl >/dev/null 2>&1; then
  synced="$(timedatectl show -p NTPSynchronized --value 2>/dev/null || true)"
  if [[ "$synced" == "yes" ]]; then
    ok "host time synchronization"
  elif [[ -n "$synced" ]]; then
    warn "host reports NTP not synchronized"
  fi
fi

if [[ "$failures" -ne 0 ]]; then
  echo "doctor: $failures failure(s)" >&2
  exit 1
fi

echo "doctor: healthy"
