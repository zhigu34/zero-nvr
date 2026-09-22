#!/usr/bin/env bash
set -euo pipefail

feature_profile_name() {
  case "${1:-}" in
    ai|frigate)
      printf 'frigate'
      ;;
    mqtt|mosquitto)
      printf 'mqtt'
      ;;
    openlist)
      printf 'openlist'
      ;;
    postgres|postgresql)
      printf 'postgres'
      ;;
    turn|coturn)
      printf 'turn'
      ;;
    *)
      return 1
      ;;
  esac
}

feature_service_name() {
  case "$(feature_profile_name "${1:-}" 2>/dev/null || true)" in
    frigate)
      printf 'frigate'
      ;;
    mqtt)
      printf 'mosquitto'
      ;;
    openlist)
      printf 'openlist'
      ;;
    postgres)
      printf 'postgres'
      ;;
    turn)
      printf 'coturn'
      ;;
    *)
      return 1
      ;;
  esac
}


database_url_uses_managed_postgres() {
  local url="${1:-}"
  local authority host

  case "$url" in
    postgres://*|postgresql://*|postgresql+psycopg://*)
      ;;
    *)
      return 1
      ;;
  esac

  authority="${url#*://}"
  authority="${authority%%/*}"
  authority="${authority##*@}"
  host="${authority%%:*}"
  [[ "$host" == "postgres" ]]
}

profile_is_enabled() {
  local current="${1:-}"
  local wanted="${2:-}"
  local item
  IFS=',' read -r -a items <<< "$current"
  for item in "${items[@]}"; do
    item="${item//[[:space:]]/}"
    if [[ "$item" == "$wanted" ]]; then
      return 0
    fi
  done
  return 1
}

profiles_enable() {
  local current="${1:-}"
  local wanted="${2:-}"
  local item joined=""
  local -a result=()

  IFS=',' read -r -a items <<< "$current"
  for item in "${items[@]}"; do
    item="${item//[[:space:]]/}"
    [[ -n "$item" ]] || continue
    if ! profile_is_enabled "$(IFS=,; printf '%s' "${result[*]-}")" "$item"; then
      result+=("$item")
    fi
  done
  if ! profile_is_enabled "$(IFS=,; printf '%s' "${result[*]-}")" "$wanted"; then
    result+=("$wanted")
  fi
  joined="$(IFS=,; printf '%s' "${result[*]-}")"
  printf '%s' "$joined"
}

profiles_disable() {
  local current="${1:-}"
  local unwanted="${2:-}"
  local item joined=""
  local -a result=()

  IFS=',' read -r -a items <<< "$current"
  for item in "${items[@]}"; do
    item="${item//[[:space:]]/}"
    [[ -n "$item" ]] || continue
    [[ "$item" == "$unwanted" ]] && continue
    if ! profile_is_enabled "$(IFS=,; printf '%s' "${result[*]-}")" "$item"; then
      result+=("$item")
    fi
  done
  joined="$(IFS=,; printf '%s' "${result[*]-}")"
  printf '%s' "$joined"
}
