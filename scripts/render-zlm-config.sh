#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
# shellcheck source=scripts/lib.sh
. "$SCRIPT_DIR/lib.sh"

require_command docker

api_secret="$(protected_env_get ZERO_NVR_ZLM_API_SECRET)"
hook_secret="$(protected_env_get ZERO_NVR_ZLM_HOOK_SECRET)"
image="$(env_get ZERO_NVR_ZLM_IMAGE "zlmediakit/zlmediakit:master")"
webrtc_port="$(env_get ZERO_NVR_ZLM_WEBRTC_PORT "8001")"
webrtc_extern_ip="$(env_get ZERO_NVR_ZLM_WEBRTC_EXTERN_IP "")"

if [[ ! "$webrtc_port" =~ ^[1-9][0-9]*$ ]] \
  || (( webrtc_port > 65535 )); then
  echo "error: ZERO_NVR_ZLM_WEBRTC_PORT must be between 1 and 65535" >&2
  exit 1
fi

if [[ ${#api_secret} -lt 32 || ${#hook_secret} -lt 32 ]]; then
  echo "error: ZLM API/hook secrets must be generated before rendering config" >&2
  exit 1
fi

output_dir="$ROOT_DIR/deploy/zlm"
output="$output_dir/config.ini"
mkdir -p "$output_dir"

base="$(mktemp "$output_dir/.config.base.XXXXXX")"
rendered="$(mktemp "$output_dir/.config.rendered.XXXXXX")"
trap 'rm -f "$base" "$rendered"' EXIT

docker run --rm --entrypoint /bin/cat "$image" \
  /opt/media/conf/config.ini > "$base"

export ZERO_NVR_ZLM_API_SECRET="$api_secret"
export ZERO_NVR_ZLM_HOOK_SECRET="$hook_secret"
export ZERO_NVR_ZLM_HOOK_BASE_URL="http://zero-nvr:8000/internal/hooks/zlm"
export ZERO_NVR_ZLM_WEBRTC_PORT="$webrtc_port"
export ZERO_NVR_ZLM_WEBRTC_EXTERN_IP="$webrtc_extern_ip"

awk '
  /^\[[^]]+\]$/ {
    section=substr($0, 2, length($0)-2)
    print
    next
  }
  section=="api" && /^apiDebug=/ {
    print "apiDebug=0"; next
  }
  section=="api" && /^secret=/ {
    print "secret=" ENVIRON["ZERO_NVR_ZLM_API_SECRET"]; next
  }
  section=="general" && /^mediaServerId=/ {
    print "mediaServerId=" ENVIRON["ZERO_NVR_ZLM_HOOK_SECRET"]; next
  }
  section=="hook" && /^enable=/ {
    print "enable=1"; next
  }
  section=="hook" && /^on_play=/ {
    print "on_play=" ENVIRON["ZERO_NVR_ZLM_HOOK_BASE_URL"] "/play"; next
  }
  section=="hook" && /^on_record_mp4=/ {
    print "on_record_mp4=" ENVIRON["ZERO_NVR_ZLM_HOOK_BASE_URL"] "/record-mp4"; next
  }
  section=="hook" && /^on_server_started=/ {
    print "on_server_started=" ENVIRON["ZERO_NVR_ZLM_HOOK_BASE_URL"] "/server-started"; next
  }
  section=="hook" && /^on_stream_changed=/ {
    print "on_stream_changed=" ENVIRON["ZERO_NVR_ZLM_HOOK_BASE_URL"] "/stream-changed"; next
  }
  section=="hook" && /^stream_changed_schemas=/ {
    print "stream_changed_schemas=rtsp"; next
  }
  section=="record" && /^enableFmp4=/ {
    print "enableFmp4=1"; next
  }
  section=="rtc" && /^externIP=/ {
    print "externIP=" ENVIRON["ZERO_NVR_ZLM_WEBRTC_EXTERN_IP"]; next
  }
  section=="rtc" && /^port=/ {
    print "port=" ENVIRON["ZERO_NVR_ZLM_WEBRTC_PORT"]; next
  }
  section=="rtc" && /^tcpPort=/ {
    print "tcpPort=" ENVIRON["ZERO_NVR_ZLM_WEBRTC_PORT"]; next
  }
  { print }
' "$base" > "$rendered"

grep -Fxq "apiDebug=0" "$rendered"
grep -Fxq "secret=$api_secret" "$rendered"
grep -Fxq "mediaServerId=$hook_secret" "$rendered"
grep -Fxq "enableFmp4=1" "$rendered"
grep -Fxq "externIP=$webrtc_extern_ip" "$rendered"
grep -Fxq "port=$webrtc_port" "$rendered"
grep -Fxq "tcpPort=$webrtc_port" "$rendered"
grep -Fxq "on_play=http://zero-nvr:8000/internal/hooks/zlm/play" "$rendered"
grep -Fxq "on_record_mp4=http://zero-nvr:8000/internal/hooks/zlm/record-mp4" "$rendered"
grep -Fxq "on_server_started=http://zero-nvr:8000/internal/hooks/zlm/server-started" "$rendered"
grep -Fxq "on_stream_changed=http://zero-nvr:8000/internal/hooks/zlm/stream-changed" "$rendered"

chmod 600 "$rendered"
mv -f "$rendered" "$output"
echo "rendered: $output"
