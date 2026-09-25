#!/usr/bin/env bash
set -euo pipefail

build_source_env_value_or() {
  local value
  value="$(env_get "$1" "")"
  if [[ -n "$value" ]]; then
    printf '%s' "$value"
  else
    printf '%s' "$2"
  fi
}

build_source_probe_ms() {
  local url="$1"
  local elapsed

  if command -v curl >/dev/null 2>&1; then
    elapsed="$(
      curl -L -sS -o /dev/null \
        --connect-timeout 2 \
        --max-time 4 \
        -w '%{time_total}' \
        "$url" 2>/dev/null
    )" || return 1
    awk -v seconds="$elapsed" 'BEGIN { printf "%d", seconds * 1000 }'
    return 0
  fi

  if command -v wget >/dev/null 2>&1; then
    wget -q --spider --timeout=4 "$url" >/dev/null 2>&1 || return 1
    printf '1000'
    return 0
  fi

  return 2
}

build_source_group_score() {
  local total=0 elapsed url
  for url in "$@"; do
    elapsed="$(build_source_probe_ms "$url")" || return $?
    total=$((total + elapsed))
  done
  printf '%s' "$total"
}

select_build_sources() {
  local mode official_score="" cn_score="" selected=""
  local official_debian="http://deb.debian.org/debian"
  local official_security="http://deb.debian.org/debian-security"
  local official_pypi="https://pypi.org/simple"
  local official_npm="https://registry.npmjs.org"
  local cn_debian="https://mirrors.tuna.tsinghua.edu.cn/debian"
  local cn_security="https://mirrors.tuna.tsinghua.edu.cn/debian-security"
  local cn_pypi="https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple"
  local cn_npm="https://registry.npmmirror.com"

  mode="${ZERO_NVR_BUILD_SOURCE_MODE:-$(env_get ZERO_NVR_BUILD_SOURCE_MODE "auto")}"

  case "$mode" in
    official|cn|custom)
      selected="$mode"
      ;;
    auto)
      if official_score="$(
        build_source_group_score \
          "https://deb.debian.org/debian/" \
          "https://pypi.org/simple/pip/" \
          "https://registry.npmjs.org/npm"
      )"; then
        if (( official_score <= 3000 )); then
          selected="official"
        elif cn_score="$(
          build_source_group_score \
            "https://mirrors.tuna.tsinghua.edu.cn/debian/" \
            "https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple/pip/" \
            "https://registry.npmmirror.com/npm"
        )"; then
          if (( cn_score < official_score )); then
            selected="cn"
          else
            selected="official"
          fi
        else
          selected="official"
        fi
      elif cn_score="$(
        build_source_group_score \
          "https://mirrors.tuna.tsinghua.edu.cn/debian/" \
          "https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple/pip/" \
          "https://registry.npmmirror.com/npm"
      )"; then
        selected="cn"
      else
        echo "WARN 构建依赖源自动探测失败，回退到官方源；构建阶段会继续报告具体网络错误" >&2
        selected="official"
      fi
      ;;
    *)
      echo "error: ZERO_NVR_BUILD_SOURCE_MODE must be auto, official, cn, or custom" >&2
      return 2
      ;;
  esac

  case "$selected" in
    official)
      export DEBIAN_MIRROR="$official_debian"
      export DEBIAN_SECURITY_MIRROR="$official_security"
      export PYPI_INDEX_URL="$official_pypi"
      export NPM_REGISTRY="$official_npm"
      ;;
    cn)
      export DEBIAN_MIRROR="$cn_debian"
      export DEBIAN_SECURITY_MIRROR="$cn_security"
      export PYPI_INDEX_URL="$cn_pypi"
      export NPM_REGISTRY="$cn_npm"
      ;;
    custom)
      export DEBIAN_MIRROR="$(build_source_env_value_or DEBIAN_MIRROR "$official_debian")"
      export DEBIAN_SECURITY_MIRROR="$(build_source_env_value_or DEBIAN_SECURITY_MIRROR "$official_security")"
      export PYPI_INDEX_URL="$(build_source_env_value_or PYPI_INDEX_URL "$official_pypi")"
      export NPM_REGISTRY="$(build_source_env_value_or NPM_REGISTRY "$official_npm")"
      ;;
  esac

  if [[ "$mode" == "auto" ]]; then
    if [[ -n "$official_score" && -n "$cn_score" ]]; then
      echo "构建依赖源: auto -> $selected (official=${official_score}ms, cn=${cn_score}ms)"
    elif [[ -n "$official_score" ]]; then
      echo "构建依赖源: auto -> $selected (official=${official_score}ms)"
    elif [[ -n "$cn_score" ]]; then
      echo "构建依赖源: auto -> $selected (cn=${cn_score}ms)"
    else
      echo "构建依赖源: auto -> $selected"
    fi
  else
    echo "构建依赖源: $selected"
  fi
}
