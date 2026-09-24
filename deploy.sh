#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
SCRIPT_DIR="$ROOT_DIR/scripts"
. "$SCRIPT_DIR/lib.sh"
. "$SCRIPT_DIR/deployment-state.sh"
. "$SCRIPT_DIR/feature-profiles.sh"
. "$SCRIPT_DIR/port-preflight.sh"

cd "$ROOT_DIR"

usage() {
  cat <<'EOF'
Usage:
  ./deploy.sh [install]
  ./deploy.sh update [version] [--backup-policy <id-or-name>]
  ./deploy.sh update-preflight [version] [--backup-policy <id-or-name>]
  ./deploy.sh rollback [version]
  ./deploy.sh status
  ./deploy.sh doctor
  ./deploy.sh benchmark <8|16> [--samples N] [--interval SECONDS]
  ./deploy.sh soak <8|16> [--duration SECONDS] [--interval SECONDS]
  ./deploy.sh release-check <8|16> [--max-age-hours HOURS]
  ./deploy.sh release-manifest <validate|show|record> [revision]
  ./deploy.sh migrate
  ./deploy.sh database migrate <postgres|sqlite> [--managed] [--target-url-env NAME] [--backup-policy <id-or-name>] [--confirm-sqlite-workload]
  ./deploy.sh backup [reason] [policy-id-or-name]
  ./deploy.sh restore list
  ./deploy.sh restore [snapshot-id|latest] --force
  ./deploy.sh recovery-kit export [directory] [policy-id-or-name]
  ./deploy.sh recovery-kit decrypt <kit.znrk> [directory]
  ./deploy.sh admin reset-password <username>
  ./deploy.sh secret rotate
  ./deploy.sh feature list
  ./deploy.sh feature enable <frigate|mqtt|openlist|postgres|turn>
  ./deploy.sh feature disable <frigate|mqtt|openlist|postgres|turn>
  ./deploy.sh feature restart <frigate|mqtt|openlist|postgres|turn>

Core deployment is intentionally three containers:
  zero-nvr API + zero-nvr worker + ZLMediaKit
EOF
}

random_hex_32() {
  od -An -N32 -tx1 /dev/urandom | tr -d ' \n'
}

set_env_value() {
  local key="$1"
  local value="$2"
  local tmp
  tmp="$(mktemp "$ROOT_DIR/.env.tmp.XXXXXX")"
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
  chmod 600 "$tmp"
  mv -f "$tmp" "$ENV_FILE"
}

ensure_env() {
  if [[ ! -f "$ENV_FILE" ]]; then
    cp "$ROOT_DIR/.env.example" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    echo "created: $ENV_FILE"
  fi

  local key value secret_key
  secret_key="$(protected_env_get ZERO_NVR_SECRET_KEY "")"
  if [[ -z "$secret_key" ]]; then
    secret_key="$(random_hex_32)"
    set_env_value ZERO_NVR_SECRET_KEY "$secret_key"
    echo "generated: ZERO_NVR_SECRET_KEY"
  elif [[ ${#secret_key} -lt 32 ]]; then
    echo "error: ZERO_NVR_SECRET_KEY must be at least 32 characters" >&2
    exit 1
  fi

  for key in \
    ZERO_NVR_ZLM_API_SECRET \
    ZERO_NVR_ZLM_HOOK_SECRET
  do
    value="$(protected_env_get "$key" "")"
    if [[ -z "$value" ]]; then
      value="$(random_hex_32)"
      set_env_value "$key" "$value"
      echo "generated: $key"
    elif [[ ${#value} -lt 32 ]]; then
      echo "error: $key must be at least 32 characters" >&2
      exit 1
    fi
  done
}

ensure_host_dirs() {
  local key value path
  for key in \
    ZERO_NVR_DATA_PATH \
    ZERO_NVR_CACHE_PATH \
    ZERO_NVR_RECORDINGS_PATH
  do
    value="$(env_get "$key")"
    if [[ -z "$value" ]]; then
      echo "error: $key is empty" >&2
      exit 1
    fi
    path="$(host_path "$value")"
    mkdir -p "$path"
  done
}

preflight() {
  require_command docker
  docker compose version >/dev/null
  docker info >/dev/null
}

validate_compose_model() {
  compose config --quiet
}

core_port_preflight() {
  local old_http new_http public_base profile profiles

  port_preflight_reset
  ensure_port_setting     ZERO_NVR_API_PORT 8000     0.0.0.0 tcp zero-nvr "zero-nvr Web/API"

  old_http="$(env_get ZERO_NVR_ZLM_HTTP_PORT "8080")"
  ensure_port_setting     ZERO_NVR_ZLM_HTTP_PORT 8080     "$(env_get ZERO_NVR_ZLM_HTTP_BIND "0.0.0.0")"     tcp zlmediakit "ZLMediaKit HTTP"
  new_http="$(env_get ZERO_NVR_ZLM_HTTP_PORT "8080")"
  if [[ "$new_http" != "$old_http" ]]; then
    public_base="$(env_get ZERO_NVR_ZLM_PUBLIC_BASE_URL "")"
    case "$public_base" in
      "http://localhost:$old_http")
        set_env_value           ZERO_NVR_ZLM_PUBLIC_BASE_URL           "http://localhost:$new_http"
        echo "saved: ZERO_NVR_ZLM_PUBLIC_BASE_URL=http://localhost:$new_http"
        ;;
      "http://127.0.0.1:$old_http")
        set_env_value           ZERO_NVR_ZLM_PUBLIC_BASE_URL           "http://127.0.0.1:$new_http"
        echo "saved: ZERO_NVR_ZLM_PUBLIC_BASE_URL=http://127.0.0.1:$new_http"
        ;;
    esac
  fi

  ensure_port_setting     ZERO_NVR_ZLM_RTSP_PORT 8554     "$(env_get ZERO_NVR_ZLM_RTSP_BIND "127.0.0.1")"     tcp zlmediakit "ZLMediaKit RTSP"
  ensure_port_setting     ZERO_NVR_ZLM_WEBRTC_PORT 8001     0.0.0.0 tcp,udp zlmediakit "ZLMediaKit WebRTC"

  profiles="$(env_get COMPOSE_PROFILES "")"
  for profile in frigate mqtt openlist turn; do
    if profile_is_enabled "$profiles" "$profile"; then
      feature_port_preflight "$profile"
    fi
  done
}

feature_port_preflight() {
  local profile="$1"
  case "$profile" in
    frigate)
      ensure_port_setting         ZERO_NVR_FRIGATE_PORT 8971         "$(env_get ZERO_NVR_FRIGATE_BIND "127.0.0.1")"         tcp frigate "Frigate management"
      ;;
    mqtt)
      ensure_port_setting         ZERO_NVR_MQTT_PORT 1883         "$(env_get ZERO_NVR_MQTT_BIND "127.0.0.1")"         tcp mosquitto "MQTT broker"
      ;;
    openlist)
      ensure_port_setting         ZERO_NVR_OPENLIST_PORT 5244         "$(env_get ZERO_NVR_OPENLIST_BIND "127.0.0.1")"         tcp openlist "OpenList management"
      ;;
    turn)
      ensure_port_setting         ZERO_NVR_TURN_PORT 3478         "$(env_get ZERO_NVR_TURN_BIND "0.0.0.0")"         tcp,udp coturn "TURN listener"
      ensure_udp_range_setting         ZERO_NVR_TURN_RELAY_MIN_PORT         ZERO_NVR_TURN_RELAY_MAX_PORT         49160 49200         "$(env_get ZERO_NVR_TURN_BIND "0.0.0.0")"         coturn "TURN relay range"
      ;;
    postgres)
      ;;
    *)
      echo "error: unsupported feature profile for port preflight: $profile" >&2
      return 2
      ;;
  esac
}

print_install_summary() {
  echo
  echo "zero-nvr installed successfully"
  echo
  echo "Web UI:"
  echo "  http://localhost:$(env_get ZERO_NVR_API_PORT "8000")"
  echo
  echo "Published media ports:"
  echo "  ZLM HTTP:   $(env_get ZERO_NVR_ZLM_HTTP_BIND "0.0.0.0"):$(env_get ZERO_NVR_ZLM_HTTP_PORT "8080")/tcp"
  echo "  ZLM RTSP:   $(env_get ZERO_NVR_ZLM_RTSP_BIND "127.0.0.1"):$(env_get ZERO_NVR_ZLM_RTSP_PORT "8554")/tcp"
  echo "  ZLM WebRTC: 0.0.0.0:$(env_get ZERO_NVR_ZLM_WEBRTC_PORT "8001")/tcp+udp"
  echo
  echo "Open the Web UI to complete first-run administrator setup."
}

prepare_zlm() {
  local image
  image="$(env_get ZERO_NVR_ZLM_IMAGE "zlmediakit/zlmediakit:master")"
  docker pull "$image"
  ZERO_NVR_ENV_FILE="$ENV_FILE" \
    "$SCRIPT_DIR/render-zlm-config.sh"
}

build_backend() {
  compose build zero-nvr
}

install_stack() {
  preflight
  ensure_env
  ensure_host_dirs
  core_port_preflight
  validate_compose_model
  prepare_zlm
  build_backend
  "$SCRIPT_DIR/migrate.sh"
  compose up -d --wait --wait-timeout 180
  ZERO_NVR_ENV_FILE="$ENV_FILE" "$SCRIPT_DIR/check.sh"
  "$SCRIPT_DIR/release-manifest.sh" record "$(git_revision || true)"
  record_installed_revision
  print_install_summary
}

update_stack() {
  local backup_policy="${1:-}"
  local requested_ref="${2:-}"
  local target_revision previous_revision
  local previous_rollback_revision previous_rollback_snapshot
  local pending_target environment current_source
  local rollback_revision="" rollback_snapshot=""
  local stage_dir="" stage_image="" configured_image=""

  preflight
  ensure_env
  ensure_host_dirs

  current_source="$(git_revision || true)"
  previous_revision="$(deployment_state_get DEPLOYED_REVISION)"
  previous_rollback_revision="$(deployment_state_get ROLLBACK_REVISION)"
  previous_rollback_snapshot="$(deployment_state_get ROLLBACK_SNAPSHOT_REL)"
  pending_target="$(deployment_state_get PENDING_TARGET_REVISION)"

  if valid_revision "$pending_target"; then
    echo "error: a previous update is still marked pending: $pending_target" >&2
    echo "run ./deploy.sh rollback before retrying update" >&2
    return 1
  fi

  if [[ -n "$requested_ref" ]]; then
    require_command git
    if ! git -C "$ROOT_DIR" diff --quiet --ignore-submodules -- \
        || ! git -C "$ROOT_DIR" diff --cached --quiet --ignore-submodules --; then
      echo "error: version-pinned update requires a clean tracked Git worktree" >&2
      echo "commit or stash source changes first; untracked runtime files are ignored" >&2
      return 1
    fi

    target_revision="$(resolve_git_revision "$requested_ref" || true)"
    if ! valid_revision "$target_revision"; then
      echo "error: update version/ref is not available in this Git clone: $requested_ref" >&2
      echo "fetch the desired release/ref first, then retry" >&2
      return 1
    fi

    if valid_revision "$previous_revision" \
      && [[ "$previous_revision" != "$target_revision" ]] \
      && ! git -C "$ROOT_DIR" merge-base --is-ancestor \
        "$previous_revision" "$target_revision"; then
      echo "error: pinned update target is not a descendant of the deployed revision" >&2
      echo "deployed: $previous_revision" >&2
      echo "target:   $target_revision" >&2
      echo "use ./deploy.sh rollback for the recorded downgrade path" >&2
      return 1
    fi

    stage_dir="$(mktemp -d "${TMPDIR:-/tmp}/zero-nvr-update.XXXXXX")"
    rmdir "$stage_dir"
    stage_image="zero-nvr:update-stage-$(printf '%s' "$target_revision" | cut -c1-12)"

    cleanup_update_stage() {
      if [[ -n "${stage_dir:-}" ]]; then
        git -C "$ROOT_DIR" worktree remove --force "$stage_dir" >/dev/null 2>&1 || true
        rm -rf "$stage_dir" >/dev/null 2>&1 || true
      fi
      if [[ -n "${stage_image:-}" ]]; then
        docker image rm "$stage_image" >/dev/null 2>&1 || true
      fi
    }
    trap cleanup_update_stage EXIT

    echo "Staging update revision $target_revision..."
    git -C "$ROOT_DIR" worktree add --detach "$stage_dir" "$target_revision" >/dev/null
    cp "$ENV_FILE" "$stage_dir/.env"
    chmod 600 "$stage_dir/.env"

    "$SCRIPT_DIR/update-preflight.sh" \
      "$stage_dir" \
      "$target_revision" \
      "$backup_policy"

    docker build --pull \
      --file "$stage_dir/backend/Dockerfile" \
      --tag "$stage_image" \
      "$stage_dir"
  else
    target_revision="$current_source"
    "$SCRIPT_DIR/update-preflight.sh" \
      "$ROOT_DIR" \
      "$target_revision" \
      "$backup_policy"
  fi
  SAFETY_SNAPSHOT_REL=""
  if [[ -n "$(compose ps -q zero-nvr 2>/dev/null || true)" ]]; then
    echo "Creating pre-upgrade database safety snapshot..."
    create_local_safety_snapshot

    environment="$(env_get ZERO_NVR_ENVIRONMENT "production")"
    if [[ "$environment" == "production" ]]; then
      echo "Creating verified pre-upgrade restic backup..."
      backup_args=(
        python -m app.cli pre-upgrade-backup
      )
      if [[ -n "$backup_policy" ]]; then
        backup_args+=(--policy "$backup_policy")
      fi
      compose run --rm --no-deps zero-nvr         "${backup_args[@]}"
    else
      echo "WARN ZERO_NVR_ENVIRONMENT=$environment; verified restic pre-upgrade backup is not required" >&2
    fi
  else
    echo "WARN zero-nvr image is not installed; no pre-upgrade safety snapshot created" >&2
  fi

  if valid_revision "$target_revision" \
    && valid_revision "$previous_revision" \
    && [[ "$previous_revision" != "$target_revision" ]] \
    && [[ -n "$SAFETY_SNAPSHOT_REL" ]]; then
    write_deployment_state \
      "$previous_revision" \
      "$previous_rollback_revision" \
      "$previous_rollback_snapshot" \
      "$target_revision" \
      "$previous_revision" \
      "$SAFETY_SNAPSHOT_REL"
  fi

  if [[ -n "$requested_ref" ]]; then
    echo "Switching source checkout to pinned revision $target_revision..."
    git -C "$ROOT_DIR" checkout --detach "$target_revision"
    configured_image="$(env_get ZERO_NVR_IMAGE "zero-nvr:local")"
    docker tag "$stage_image" "$configured_image"
  fi

  prepare_zlm
  if [[ -z "$requested_ref" ]]; then
    compose build --pull zero-nvr
  fi

  echo "Stopping zero-nvr control plane for explicit schema migration; ZLMediaKit remains running..."
  compose stop zero-nvr-worker zero-nvr >/dev/null 2>&1 || true

  if ! "$SCRIPT_DIR/migrate.sh"; then
    echo "error: database migration failed; deployment remains pending" >&2
    echo "run ./deploy.sh rollback to restore the recorded pre-upgrade safety point" >&2
    return 1
  fi

  compose up -d --wait --wait-timeout 180
  ZERO_NVR_ENV_FILE="$ENV_FILE" "$SCRIPT_DIR/check.sh"
  "$SCRIPT_DIR/release-manifest.sh" record "$target_revision"

  if valid_revision "$target_revision"; then
    if valid_revision "$previous_revision" \
      && [[ "$previous_revision" != "$target_revision" ]] \
      && [[ -n "$SAFETY_SNAPSHOT_REL" ]]; then
      rollback_revision="$previous_revision"
      rollback_snapshot="$SAFETY_SNAPSHOT_REL"
    elif [[ "$previous_revision" == "$target_revision" ]]; then
      rollback_revision="$previous_rollback_revision"
      rollback_snapshot="$previous_rollback_snapshot"
    else
      echo "WARN previous deployment revision is unknown; this update cannot be automatically rolled back by version" >&2
    fi

    write_deployment_state \
      "$target_revision" \
      "$rollback_revision" \
      "$rollback_snapshot"
  else
    echo "WARN target Git revision unavailable; deployment state was not advanced" >&2
  fi
}

update_preflight_only() {
  local backup_policy="${1:-}"
  local requested_ref="${2:-}"
  local target_revision current_source
  local stage_dir=""

  preflight
  ensure_env
  ensure_host_dirs

  current_source="$(git_revision || true)"
  if [[ -n "$requested_ref" ]]; then
    require_command git
    target_revision="$(
      resolve_git_revision "$requested_ref" || true
    )"
    if ! valid_revision "$target_revision"; then
      echo "error: update version/ref is not available in this Git clone: $requested_ref" >&2
      return 1
    fi

    stage_dir="$(
      mktemp -d "${TMPDIR:-/tmp}/zero-nvr-update-preflight.XXXXXX"
    )"
    rmdir "$stage_dir"
    cleanup_update_preflight() {
      git -C "$ROOT_DIR" worktree remove --force         "$stage_dir" >/dev/null 2>&1 || true
      rm -rf "$stage_dir" >/dev/null 2>&1 || true
    }

    git -C "$ROOT_DIR" worktree add --detach       "$stage_dir" "$target_revision" >/dev/null

    local preflight_status=0
    if "$SCRIPT_DIR/update-preflight.sh"       "$stage_dir"       "$target_revision"       "$backup_policy"
    then
      preflight_status=0
    else
      preflight_status=$?
    fi
    cleanup_update_preflight
    return "$preflight_status"
  else
    target_revision="$current_source"
    "$SCRIPT_DIR/update-preflight.sh"       "$ROOT_DIR"       "$target_revision"       "$backup_policy"
  fi
}


feature_set_profile() {
  local action="$1"
  local profile="$2"
  local current next

  current="$(env_get COMPOSE_PROFILES "")"
  case "$action" in
    enable)
      next="$(profiles_enable "$current" "$profile")"
      ;;
    disable)
      next="$(profiles_disable "$current" "$profile")"
      ;;
    *)
      echo "error: invalid profile action: $action" >&2
      return 2
      ;;
  esac
  set_env_value COMPOSE_PROFILES "$next"
}

feature_prepare() {
  local profile="$1"
  local data_root cache_root
  data_root="$(host_path "$(env_get ZERO_NVR_DATA_PATH)")"
  cache_root="$(host_path "$(env_get ZERO_NVR_CACHE_PATH)")"

  case "$profile" in
    frigate)
      mkdir -p         "$data_root/managed/frigate"         "$cache_root/frigate"
      if [[ ! -f "$data_root/managed/frigate/config.yml" ]]; then
        cat > "$data_root/managed/frigate/config.yml" <<'EOF'
mqtt:
  enabled: false
record:
  enabled: false
cameras: {}
EOF
        chmod 640 "$data_root/managed/frigate/config.yml"
      fi
      if [[ ! -f "$data_root/managed/frigate/runtime.env" ]]; then
        : > "$data_root/managed/frigate/runtime.env"
        chmod 600 "$data_root/managed/frigate/runtime.env"
      fi
      ;;
    mqtt)
      local image username password config_dir
      image="$(env_get ZERO_NVR_MQTT_IMAGE "eclipse-mosquitto:2.1.2-alpine")"
      username="$(env_get ZERO_NVR_MQTT_USERNAME "zero-nvr")"
      password="$(protected_env_get ZERO_NVR_MQTT_PASSWORD "")"
      if [[ -z "$password" ]]; then
        password="$(random_hex_32)"
        set_env_value ZERO_NVR_MQTT_PASSWORD "$password"
        echo "generated: ZERO_NVR_MQTT_PASSWORD"
      fi
      config_dir="$data_root/managed/mosquitto/config"
      mkdir -p "$config_dir"
      cat > "$config_dir/mosquitto.conf" <<'EOF'
listener 1883 0.0.0.0
allow_anonymous false
password_file /mosquitto/config/password
persistence true
persistence_location /mosquitto/data/
log_dest stdout
EOF
      chmod 644 "$config_dir/mosquitto.conf"
      docker pull "$image"
      docker run --rm         --user 0:0         --entrypoint sh         -e MQTT_USERNAME="$username"         -e MQTT_PASSWORD="$password"         -v "$config_dir:/work"         "$image"         -ec 'mosquitto_passwd -b -c /work/password "$MQTT_USERNAME" "$MQTT_PASSWORD"; chmod 644 /work/password'
      ;;
    openlist)
      :
      ;;
    turn)
      local turn_secret turn_realm turn_external_ip
      local relay_min relay_max turn_config_dir
      turn_secret="$(protected_env_get ZERO_NVR_TURN_SHARED_SECRET "")"
      if [[ -z "$turn_secret" ]]; then
        turn_secret="$(random_hex_32)"
        set_env_value ZERO_NVR_TURN_SHARED_SECRET "$turn_secret"
        echo "generated: ZERO_NVR_TURN_SHARED_SECRET"
      elif [[ ${#turn_secret} -lt 32 ]]; then
        echo "error: ZERO_NVR_TURN_SHARED_SECRET must be at least 32 characters" >&2
        return 1
      fi

      turn_realm="$(env_get ZERO_NVR_TURN_REALM "zero-nvr")"
      turn_external_ip="$(env_get ZERO_NVR_TURN_EXTERNAL_IP "")"
      relay_min="$(env_get ZERO_NVR_TURN_RELAY_MIN_PORT "49160")"
      relay_max="$(env_get ZERO_NVR_TURN_RELAY_MAX_PORT "49200")"

      if [[ ! "$relay_min" =~ ^[0-9]+$ ]] \
        || [[ ! "$relay_max" =~ ^[0-9]+$ ]] \
        || (( relay_min < 1024 || relay_min > 65535 )) \
        || (( relay_max < 1024 || relay_max > 65535 )) \
        || (( relay_min > relay_max )); then
        echo "error: TURN relay port range is invalid" >&2
        return 1
      fi
      if [[ -z "$turn_realm" ]] \
        || [[ "$turn_realm" =~ [[:space:]] ]]; then
        echo "error: ZERO_NVR_TURN_REALM must be non-empty and contain no spaces" >&2
        return 1
      fi
      if [[ -n "$turn_external_ip" ]] \
        && [[ "$turn_external_ip" =~ [[:space:]/] ]]; then
        echo "error: ZERO_NVR_TURN_EXTERNAL_IP must be an IP address" >&2
        return 1
      fi

      turn_config_dir="$data_root/managed/coturn"
      mkdir -p "$turn_config_dir"
      {
        printf '%s\n' \
          'no-cli' \
          'no-tls' \
          'no-dtls' \
          'log-file=stdout' \
          'simple-log' \
          'fingerprint' \
          'use-auth-secret' \
          "static-auth-secret=$turn_secret" \
          "realm=$turn_realm" \
          'listening-port=3478' \
          "min-port=$relay_min" \
          "max-port=$relay_max" \
          'user-quota=12' \
          'total-quota=200' \
          'no-multicast-peers' \
          'no-loopback-peers'
        if [[ -n "$turn_external_ip" ]]; then
          printf 'external-ip=%s\n' "$turn_external_ip"
        fi
      } > "$turn_config_dir/turnserver.conf"
      chmod 600 "$turn_config_dir/turnserver.conf"
      ;;
    postgres)
      local pg_password pg_password_file
      pg_password_file="$(env_get ZERO_NVR_POSTGRES_PASSWORD_FILE "")"
      if [[ -n "$pg_password_file" ]] \
        && [[ "$pg_password_file" != /var/lib/zero-nvr/bootstrap-secrets/* ]]; then
        echo "error: ZERO_NVR_POSTGRES_PASSWORD_FILE must be under /var/lib/zero-nvr/bootstrap-secrets" >&2
        return 1
      fi
      pg_password="$(protected_env_get ZERO_NVR_POSTGRES_PASSWORD "")"
      if [[ -z "$pg_password" ]]; then
        pg_password="$(random_hex_32)"
        set_env_value ZERO_NVR_POSTGRES_PASSWORD "$pg_password"
        echo "generated: ZERO_NVR_POSTGRES_PASSWORD"
      fi
      mkdir -p "$data_root/bootstrap-secrets"
      chmod 700 "$data_root/bootstrap-secrets"
      ;;
    *)
      echo "error: unsupported feature profile: $profile" >&2
      return 2
      ;;
  esac
}

feature_enable() {
  local name="$1"
  local profile service original_profiles
  profile="$(feature_profile_name "$name" 2>/dev/null || true)"
  service="$(feature_service_name "$name" 2>/dev/null || true)"
  if [[ -z "$profile" || -z "$service" ]]; then
    echo "error: unsupported feature: $name" >&2
    return 2
  fi

  preflight
  ensure_env
  ensure_host_dirs
  original_profiles="$(env_get COMPOSE_PROFILES "")"
  core_port_preflight
  if ! profile_is_enabled "$original_profiles" "$profile"; then
    feature_port_preflight "$profile"
  fi
  feature_prepare "$profile"
  feature_set_profile enable "$profile"
  if ! validate_compose_model; then
    set_env_value COMPOSE_PROFILES "$original_profiles"
    return 1
  fi

  if ! compose pull "$service"; then
    set_env_value COMPOSE_PROFILES "$original_profiles"
    return 1
  fi
  if ! compose up -d --wait --wait-timeout 180 "$service"; then
    compose rm -sf "$service" >/dev/null 2>&1 || true
    set_env_value COMPOSE_PROFILES "$original_profiles"
    return 1
  fi

  if [[ "$profile" == "turn" ]]; then
    set_env_value ZERO_NVR_TURN_ENABLED "true"
    if ! compose up -d --force-recreate --wait --wait-timeout 180 zero-nvr; then
      set_env_value ZERO_NVR_TURN_ENABLED "false"
      compose rm -sf "$service" >/dev/null 2>&1 || true
      set_env_value COMPOSE_PROFILES "$original_profiles"
      compose up -d --force-recreate --wait --wait-timeout 180 zero-nvr >/dev/null 2>&1 || true
      return 1
    fi
  fi

  echo "feature enabled: $profile"
  case "$profile" in
    frigate)
      echo "managed Frigate API: http://frigate:5000 (inside zero-nvr network)"
      echo "configure zero-nvr System > Integrations > Frigate with mode=managed"
      ;;
    mqtt)
      echo "managed MQTT username: $(env_get ZERO_NVR_MQTT_USERNAME "zero-nvr")"
      if [[ -n "$(env_get ZERO_NVR_MQTT_PASSWORD_FILE "")" ]]; then
        echo "managed MQTT password source: ZERO_NVR_MQTT_PASSWORD_FILE"
      else
        echo "managed MQTT password is stored in .env as ZERO_NVR_MQTT_PASSWORD"
      fi
      ;;
    postgres)
      echo "managed PostgreSQL is running but the active zero-nvr database was not changed"
      echo "database-engine migration remains an explicit operation"
      ;;
    turn)
      echo "managed TURN is enabled for authorized WebRTC sessions"
      echo "set ZERO_NVR_TURN_PUBLIC_HOST and ZERO_NVR_TURN_EXTERNAL_IP when clients connect through NAT"
      ;;
  esac
}

feature_disable() {
  local name="$1"
  local profile service
  profile="$(feature_profile_name "$name" 2>/dev/null || true)"
  service="$(feature_service_name "$name" 2>/dev/null || true)"
  if [[ -z "$profile" || -z "$service" ]]; then
    echo "error: unsupported feature: $name" >&2
    return 2
  fi

  preflight
  ensure_env
  if [[ "$profile" == "postgres" ]] \
    && database_url_uses_managed_postgres \
      "$(env_get ZERO_NVR_DATABASE_URL "")"; then
    echo "error: managed PostgreSQL is the active zero-nvr database" >&2
    echo "switch the active database away from the managed postgres service before disabling it" >&2
    return 1
  fi
  if [[ "$profile" == "turn" ]]; then
    set_env_value ZERO_NVR_TURN_ENABLED "false"
  fi
  compose stop "$service" >/dev/null 2>&1 || true
  compose rm -f "$service" >/dev/null 2>&1 || true
  feature_set_profile disable "$profile"
  if [[ "$profile" == "turn" ]]; then
    compose up -d --force-recreate --wait --wait-timeout 180 zero-nvr
  fi
  echo "feature disabled: $profile"
  echo "persistent feature data was retained"
}

feature_restart() {
  local name="$1"
  local profile service
  profile="$(feature_profile_name "$name" 2>/dev/null || true)"
  service="$(feature_service_name "$name" 2>/dev/null || true)"
  if [[ -z "$profile" || -z "$service" ]]; then
    echo "error: unsupported feature: $name" >&2
    return 2
  fi

  ensure_env
  if ! profile_is_enabled "$(env_get COMPOSE_PROFILES "")" "$profile"; then
    echo "error: feature is not enabled: $profile" >&2
    return 1
  fi

  preflight
  ensure_host_dirs
  core_port_preflight
  feature_prepare "$profile"
  validate_compose_model
  compose up -d --force-recreate --wait --wait-timeout 180 "$service"
  if [[ "$profile" == "turn" ]]; then
    set_env_value ZERO_NVR_TURN_ENABLED "true"
    compose up -d --force-recreate --wait --wait-timeout 180 zero-nvr
  fi
  echo "feature restarted: $profile"
}

feature_list() {
  local current profile
  ensure_env
  current="$(env_get COMPOSE_PROFILES "")"
  for profile in frigate mqtt openlist postgres turn; do
    if profile_is_enabled "$current" "$profile"; then
      printf '%-10s enabled\n' "$profile"
    else
      printf '%-10s disabled\n' "$profile"
    fi
  done
}

command="${1:-install}"
shift || true

case "$command" in
  install)
    install_stack
    ;;
  update)
    backup_policy=""
    target_ref=""
    while [[ "$#" -gt 0 ]]; do
      case "$1" in
        --backup-policy)
          shift
          backup_policy="${1:-}"
          if [[ -z "$backup_policy" ]]; then
            echo "error: --backup-policy requires an id or name" >&2
            exit 2
          fi
          ;;
        -*)
          echo "error: unknown update option: $1" >&2
          exit 2
          ;;
        *)
          if [[ -n "$target_ref" ]]; then
            echo "error: update accepts at most one version/ref" >&2
            exit 2
          fi
          target_ref="$1"
          ;;
      esac
      shift
    done
    update_stack "$backup_policy" "$target_ref"
    ;;
  update-preflight)
    backup_policy=""
    target_ref=""
    while [[ "$#" -gt 0 ]]; do
      case "$1" in
        --backup-policy)
          shift
          backup_policy="${1:-}"
          if [[ -z "$backup_policy" ]]; then
            echo "error: --backup-policy requires an id or name" >&2
            exit 2
          fi
          ;;
        -*)
          echo "error: unknown update-preflight option: $1" >&2
          exit 2
          ;;
        *)
          if [[ -n "$target_ref" ]]; then
            echo "error: update-preflight accepts at most one version/ref" >&2
            exit 2
          fi
          target_ref="$1"
          ;;
      esac
      shift
    done
    update_preflight_only "$backup_policy" "$target_ref"
    ;;
  rollback)
    bash "$SCRIPT_DIR/rollback.sh" "$@"
    ;;
  status)
    ensure_env
    compose ps
    if [[ -f "$(deployment_state_file)" ]]; then
      echo
      echo "Deployment state:"
      echo "  deployed: $(deployment_state_get DEPLOYED_REVISION)"
      echo "  rollback: $(deployment_state_get ROLLBACK_REVISION)"
      pending="$(deployment_state_get PENDING_TARGET_REVISION)"
      if [[ -n "$pending" ]]; then
        echo "  pending:  $pending"
      fi
    fi
    ;;
  doctor|check)
    ensure_env
    ensure_host_dirs
    ZERO_NVR_ENV_FILE="$ENV_FILE" "$SCRIPT_DIR/check.sh"
    ;;
  benchmark)
    ensure_env
    ensure_host_dirs
    "$SCRIPT_DIR/benchmark.sh" "$@"
    ;;
  soak)
    ensure_env
    ensure_host_dirs
    "$SCRIPT_DIR/soak.sh" "$@"
    ;;
  release-check)
    ensure_env
    ensure_host_dirs
    "$SCRIPT_DIR/release-check.sh" "$@"
    ;;
  release-manifest)
    subcommand="${1:-show}"
    shift || true
    if [[ "$subcommand" != "validate" ]]; then
      ensure_env
      ensure_host_dirs
    fi
    "$SCRIPT_DIR/release-manifest.sh" "$subcommand" "$@"
    ;;
  migrate)
    ensure_env
    "$SCRIPT_DIR/migrate.sh"
    ;;
  database)
    subcommand="${1:-}"
    shift || true
    case "$subcommand" in
      migrate)
        "$SCRIPT_DIR/database-migrate.sh" "$@"
        ;;
      *)
        echo "error: unsupported database command: $subcommand" >&2
        usage >&2
        exit 2
        ;;
    esac
    ;;
  backup)
    ensure_env
    reason="${1:-manual}"
    policy="${2:-}"
    "$SCRIPT_DIR/backup.sh" "$reason" "$policy"
    ;;
  restore)
    preflight
    if [[ ! -f "$ENV_FILE" ]]; then
      echo "error: restore requires the original RecoveryKit .env; refusing to generate a new master key" >&2
      exit 1
    fi
    secret_key="$(protected_env_get ZERO_NVR_SECRET_KEY "")"
    if [[ ${#secret_key} -lt 32 ]]; then
      echo "error: RecoveryKit master secret bootstrap is missing or invalid" >&2
      exit 1
    fi
    ensure_host_dirs
    build_backend
    if [[ "${1:-}" != "list" ]]; then
      for key in ZERO_NVR_ZLM_API_SECRET ZERO_NVR_ZLM_HOOK_SECRET; do
        value="$(protected_env_get "$key" "")"
        if [[ ${#value} -lt 32 ]]; then
          echo "error: RecoveryKit bootstrap is missing $key or ${key}_FILE" >&2
          exit 1
        fi
      done
      prepare_zlm
    fi
    "$SCRIPT_DIR/restore.sh" "$@"
    ;;
  recovery-kit)
    subcommand="${1:-}"
    shift || true
    case "$subcommand" in
      export)
        ensure_env
        output="${1:-$ROOT_DIR/recovery-kit}"
        policy="${2:-}"
        "$SCRIPT_DIR/recovery-kit.sh" "$output" "$policy"
        ;;
      decrypt)
        "$SCRIPT_DIR/recovery-kit-decrypt.sh" "$@"
        ;;
      *)
        echo "error: unsupported recovery-kit command: $subcommand" >&2
        usage >&2
        exit 2
        ;;
    esac
    ;;
  secret)
    subcommand="${1:-}"
    shift || true
    case "$subcommand" in
      rotate)
        if [[ "$#" -ne 0 ]]; then
          echo "error: secret rotate accepts no arguments" >&2
          exit 2
        fi
        ensure_env
        rotation_failed=false
        compose stop zero-nvr-worker zero-nvr
        if ! compose run --rm --no-deps zero-nvr \
          python -m app.cli secret-rotate
        then
          rotation_failed=true
        fi
        if ! compose up -d --force-recreate --wait \
          zero-nvr zero-nvr-worker
        then
          echo "error: failed to restart zero-nvr after secret rotation attempt" >&2
          exit 1
        fi
        if ! ZERO_NVR_ENV_FILE="$ENV_FILE" "$SCRIPT_DIR/check.sh"; then
          echo "error: zero-nvr health check failed after secret rotation attempt" >&2
          exit 1
        fi
        if [[ "$rotation_failed" == true ]]; then
          echo "error: secret rotation failed; configured keyring was retained and services were restarted" >&2
          exit 1
        fi
        echo "SecretRecord key rotation completed and services were restarted."
        ;;
      *)
        echo "error: unsupported secret command: $subcommand" >&2
        usage >&2
        exit 2
        ;;
    esac
    ;;
  admin)
    subcommand="${1:-}"
    shift || true
    case "$subcommand" in
      reset-password)
        username="${1:-}"
        if [[ -z "$username" ]]; then
          echo "error: username is required" >&2
          exit 2
        fi
        ensure_env
        compose run --rm --no-deps zero-nvr \
          python -m app.cli admin-reset-password \
          --username "$username"
        ;;
      *)
        echo "error: unsupported admin command: $subcommand" >&2
        usage >&2
        exit 2
        ;;
    esac
    ;;
  feature)
    subcommand="${1:-list}"
    shift || true
    case "$subcommand" in
      list|status)
        if [[ "$#" -ne 0 ]]; then
          echo "error: feature list accepts no arguments" >&2
          exit 2
        fi
        feature_list
        ;;
      enable|disable|restart)
        feature_name="${1:-}"
        if [[ -z "$feature_name" || "$#" -ne 1 ]]; then
          echo "error: feature $subcommand requires exactly one feature name" >&2
          exit 2
        fi
        "feature_$subcommand" "$feature_name"
        ;;
      *)
        echo "error: unsupported feature command: $subcommand" >&2
        usage >&2
        exit 2
        ;;
    esac
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    echo "error: unknown command: $command" >&2
    usage >&2
    exit 2
    ;;
esac
