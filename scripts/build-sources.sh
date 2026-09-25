#!/usr/bin/env bash
set -euo pipefail

build_source_interactive() {
  [[ -t 0 && -t 1 ]]
}

configure_build_source_first_install() {
  local answer mode value

  if [[ -n "${ZERO_NVR_BUILD_SOURCE_MODE:-}" ]]; then
    mode="$ZERO_NVR_BUILD_SOURCE_MODE"
    case "$mode" in
      auto|official|cn|custom) ;;
      *)
        echo "error: ZERO_NVR_BUILD_SOURCE_MODE must be auto, official, cn, or custom" >&2
        return 2
        ;;
    esac
    set_env_value ZERO_NVR_BUILD_SOURCE_MODE "$mode"
    if [[ "$mode" == "custom" ]]; then
      for key in DEBIAN_MIRROR DEBIAN_SECURITY_MIRROR PYPI_INDEX_URL NPM_REGISTRY; do
        value="${!key:-}"
        [[ -n "$value" ]] && set_env_value "$key" "$value"
      done
    fi
    echo "首次部署构建依赖源: $mode（来自环境变量）"
    return 0
  fi

  if ! build_source_interactive; then
    set_env_value ZERO_NVR_BUILD_SOURCE_MODE auto
    echo "首次部署构建依赖源: auto（非交互环境）"
    return 0
  fi

  echo
  echo "请选择构建依赖源："
  echo "  1) 自动检测（推荐）"
  echo "  2) 中国大陆加速（清华 Debian/PyPI + npmmirror）"
  echo "  3) 官方源（Debian/PyPI/npm）"
  echo "  4) 自定义"
  while true; do
    printf '请选择 [1]: '
    if ! IFS= read -r answer; then
      answer="1"
    fi
    answer="${answer:-1}"
    case "$answer" in
      1|auto)
        mode="auto"
        ;;
      2|cn)
        mode="cn"
        ;;
      3|official)
        mode="official"
        ;;
      4|custom)
        mode="custom"
        ;;
      *)
        echo "请输入 1、2、3 或 4。"
        continue
        ;;
    esac
    break
  done

  set_env_value ZERO_NVR_BUILD_SOURCE_MODE "$mode"

  if [[ "$mode" == "custom" ]]; then
    echo "请输入自定义构建源；直接回车则该项回退到官方源。"

    printf 'Debian 镜像地址: '
    IFS= read -r value || value=""
    set_env_value DEBIAN_MIRROR "$value"

    printf 'Debian Security 镜像地址: '
    IFS= read -r value || value=""
    set_env_value DEBIAN_SECURITY_MIRROR "$value"

    printf 'PyPI 地址: '
    IFS= read -r value || value=""
    set_env_value PYPI_INDEX_URL "$value"

    printf 'npm registry 地址: '
    IFS= read -r value || value=""
    set_env_value NPM_REGISTRY "$value"
  fi

  echo "已保存构建依赖源模式: $mode"
}

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
