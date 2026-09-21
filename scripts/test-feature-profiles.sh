#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
. "$ROOT_DIR/scripts/feature-profiles.sh"

[[ "$(feature_profile_name ai)" == "frigate" ]]
[[ "$(feature_profile_name mosquitto)" == "mqtt" ]]
[[ "$(feature_profile_name postgresql)" == "postgres" ]]
[[ "$(feature_profile_name coturn)" == "turn" ]]
[[ "$(feature_service_name turn)" == "coturn" ]]
[[ "$(feature_service_name mqtt)" == "mosquitto" ]]
[[ "$(feature_service_name openlist)" == "openlist" ]]

enabled="$(profiles_enable "frigate,mqtt" openlist)"
[[ "$enabled" == "frigate,mqtt,openlist" ]]
[[ "$(profiles_enable "$enabled" mqtt)" == "$enabled" ]]
[[ "$(profiles_disable "$enabled" mqtt)" == "frigate,openlist" ]]
[[ "$(profiles_disable "mqtt" mqtt)" == "" ]]

if feature_profile_name unknown >/dev/null 2>&1; then
  echo "unknown feature unexpectedly resolved" >&2
  exit 1
fi

echo "feature-profiles: ok"
