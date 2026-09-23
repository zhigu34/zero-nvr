#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

STAGE="$TMP_DIR/zero-nvr"
FAKE_BIN="$TMP_DIR/bin"
DOCKER_LOG="$TMP_DIR/docker.log"
OUTPUT="$TMP_DIR/install.out"

mkdir -p "$STAGE/scripts" "$STAGE/deploy/zlm" "$FAKE_BIN"
cp "$ROOT_DIR/deploy.sh" "$STAGE/deploy.sh"
cp "$ROOT_DIR/.env.example" "$STAGE/.env.example"
cp "$ROOT_DIR/docker-compose.yml" "$STAGE/docker-compose.yml"
cp "$ROOT_DIR/scripts/lib.sh" "$STAGE/scripts/lib.sh"
cp "$ROOT_DIR/scripts/deployment-state.sh" "$STAGE/scripts/deployment-state.sh"
cp "$ROOT_DIR/scripts/feature-profiles.sh" "$STAGE/scripts/feature-profiles.sh"
cp "$ROOT_DIR/scripts/port-preflight.sh" "$STAGE/scripts/port-preflight.sh"
cp "$ROOT_DIR/scripts/render-zlm-config.sh" "$STAGE/scripts/render-zlm-config.sh"
cp "$ROOT_DIR/scripts/migrate.sh" "$STAGE/scripts/migrate.sh"
cp "$ROOT_DIR/scripts/check.sh" "$STAGE/scripts/check.sh"
chmod +x "$STAGE/deploy.sh" "$STAGE/scripts/"*.sh

cat > "$FAKE_BIN/docker" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

: "${FAKE_DOCKER_LOG:?}"
printf '%s\n' "$*" >> "$FAKE_DOCKER_LOG"

args="$*"

case "$args" in
  "compose version"|"info")
    exit 0
    ;;
  "ps --filter label=com.docker.compose.project=zero-nvr"*)
    exit 0
    ;;
  "pull "*)
    exit 0
    ;;
  "run --rm --entrypoint /bin/cat "*)
    cat <<'CONFIG'
[api]
apiDebug=1
secret=original-secret

[general]
mediaServerId=original-media-server

[hook]
enable=0
on_play=
on_record_mp4=
on_server_started=
on_stream_changed=
stream_changed_schemas=

[record]
enableFmp4=0

[rtc]
externIP=
port=8000
tcpPort=8000
CONFIG
    exit 0
    ;;
  "volume ls -q "*)
    printf '%s\n' "zero-nvr_zero-nvr-prebuffer"
    exit 0
    ;;
  "volume inspect zero-nvr_zero-nvr-prebuffer "*)
    printf '%s\n' "tmpfs"
    exit 0
    ;;
esac

if [[ "$args" == *" compose "* ]] || [[ "$1" == "compose" ]]; then
  case "$args" in
    *" config --quiet")
      exit 0
      ;;
    *" build zero-nvr")
      exit 0
      ;;
    *" run --rm --no-deps zero-nvr alembic upgrade head")
      exit 0
      ;;
    *" up -d --wait --wait-timeout 180")
      exit 0
      ;;
    *" ps -q zero-nvr")
      printf '%s\n' "fake-zero-nvr"
      exit 0
      ;;
    *" ps -q zlmediakit")
      printf '%s\n' "fake-zlmediakit"
      exit 0
      ;;
    *" exec -T zero-nvr curl "*)
      exit 0
      ;;
    *" exec -T zlmediakit sh -ec "*)
      exit 0
      ;;
  esac
fi

echo "unexpected fake docker invocation: $args" >&2
exit 1
EOF
chmod +x "$FAKE_BIN/docker"

# Port probe behavior is covered independently by test-port-preflight.sh.
# Keep this orchestration smoke deterministic by making host bind probes pass.
cat > "$FAKE_BIN/python3" <<'EOF'
#!/usr/bin/env bash
cat >/dev/null
exit 0
EOF
chmod +x "$FAKE_BIN/python3"

(
  cd "$STAGE"
  PATH="$FAKE_BIN:$PATH" \
  FAKE_DOCKER_LOG="$DOCKER_LOG" \
  ./deploy.sh install
) >"$OUTPUT" 2>&1

fail() {
  echo "FAIL: $*" >&2
  echo "--- install output ---" >&2
  cat "$OUTPUT" >&2
  echo "--- docker log ---" >&2
  cat "$DOCKER_LOG" >&2
  exit 1
}

[[ -f "$STAGE/.env" ]] || fail ".env was not created"
[[ "$(stat -c '%a' "$STAGE/.env")" == "600" ]] || fail ".env permissions are not 0600"

for key in \
  ZERO_NVR_SECRET_KEY \
  ZERO_NVR_ZLM_API_SECRET \
  ZERO_NVR_ZLM_HOOK_SECRET
do
  value="$(grep -E "^${key}=" "$STAGE/.env" | tail -n 1 | cut -d= -f2-)"
  [[ ${#value} -ge 32 ]] || fail "$key was not generated"
done

grep -Fxq "ZERO_NVR_ZLM_WEBRTC_PORT=8001" "$STAGE/.env" || fail "WebRTC default port was not preserved"

for path in \
  "$STAGE/data/zero-nvr" \
  "$STAGE/data/cache" \
  "$STAGE/data/recordings"
do
  [[ -d "$path" ]] || fail "host directory missing: $path"
done

zlm_config="$STAGE/deploy/zlm/config.ini"
[[ -f "$zlm_config" ]] || fail "ZLM config was not rendered"
grep -Fxq "apiDebug=0" "$zlm_config" || fail "ZLM apiDebug was not hardened"
grep -Fxq "enableFmp4=1" "$zlm_config" || fail "ZLM fMP4 recording was not enabled"
grep -Fxq "port=8001" "$zlm_config" || fail "ZLM WebRTC UDP port was not rendered"
grep -Fxq "tcpPort=8001" "$zlm_config" || fail "ZLM WebRTC TCP port was not rendered"

grep -Fq "created: $STAGE/.env" "$OUTPUT" || fail "install did not report .env creation"
grep -Fq "generated: ZERO_NVR_SECRET_KEY" "$OUTPUT" || fail "install did not report secret generation"
grep -Fq "zero-nvr installed successfully" "$OUTPUT" || fail "install summary was not printed"
grep -Fq "http://localhost:8000" "$OUTPUT" || fail "Web UI address was not printed"
grep -Fq "ZLM WebRTC: 0.0.0.0:8001/tcp+udp" "$OUTPUT" || fail "effective WebRTC port was not printed"
grep -Fq "doctor: healthy" "$OUTPUT" || fail "post-install health check did not pass"

grep -Fq "compose --env-file $STAGE/.env -f $STAGE/docker-compose.yml config --quiet" "$DOCKER_LOG" || fail "Compose model was not validated"
grep -Fq "pull zlmediakit/zlmediakit:master" "$DOCKER_LOG" || fail "ZLMediaKit image was not pulled"
grep -Fq "run --rm --no-deps zero-nvr alembic upgrade head" "$DOCKER_LOG" || fail "database migration was not executed"
grep -Fq "up -d --wait --wait-timeout 180" "$DOCKER_LOG" || fail "Core stack start was not executed"

echo "clean install smoke passed"
