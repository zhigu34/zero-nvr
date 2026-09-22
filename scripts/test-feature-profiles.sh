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

managed_url="postgresql+psycopg://zero_nvr:secret@postgres:5432/zero_nvr"
managed_plain_url="postgresql://zero_nvr:secret@postgres/zero_nvr"
external_url="postgresql+psycopg://zero_nvr:secret@db.example.test:5432/zero_nvr"
lookalike_url="postgresql://zero_nvr:secret@postgres.example.test/zero_nvr"
sqlite_url="sqlite:////var/lib/zero-nvr/zero-nvr.db"

database_url_uses_managed_postgres "$managed_url"
database_url_uses_managed_postgres "$managed_plain_url"
if database_url_uses_managed_postgres "$external_url"; then
  echo "external PostgreSQL unexpectedly classified as managed" >&2
  exit 1
fi
if database_url_uses_managed_postgres "$lookalike_url"; then
  echo "lookalike PostgreSQL host unexpectedly classified as managed" >&2
  exit 1
fi
if database_url_uses_managed_postgres "$sqlite_url"; then
  echo "SQLite unexpectedly classified as managed PostgreSQL" >&2
  exit 1
fi

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
