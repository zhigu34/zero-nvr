/**
 * Field metadata and validation for the runtime tuning group.
 *
 * The limits live here rather than inline in the form so that the validation
 * rules and the rendered inputs cannot drift apart, and so a change of limit
 * is one edit rather than two. Every range mirrors
 * `RuntimeTuningSettingsPatch` in `backend/app/modules/system/schemas.py`.
 *
 * Units are declared per field because this group mixes them freely: seconds,
 * bytes, kilobits per second, threads, and one float. A form that labelled
 * them all "duration" or all "size" would make `playback_cache_max_bytes`
 * look like a number of seconds.
 */
import type { RuntimeTuning, SystemSettings } from "../api/systemSettings"

export type FieldUnit = "seconds" | "bytes" | "kbps" | "count"

export interface RuntimeFieldSpec {
  key: keyof RuntimeTuning
  label: string
  unit: FieldUnit
  min: number
  max: number
  step: number
  integer: boolean
  hint: string
}

const MIB = 1024 * 1024
const GIB = 1024 * MIB
const TIB = 1024 * GIB

/**
 * `playback_cache_max_bytes` is capped at 1 TiB, not 1 GiB — the Pydantic
 * bound is `1024 * 1024 * 1024 * 1024` (`system/schemas.py:146`).
 */
export const RUNTIME_FIELDS: readonly RuntimeFieldSpec[] = [
  {
    key: "prebuffer_fragment_seconds",
    label: "预缓冲分片时长",
    unit: "seconds",
    min: 2,
    max: 30,
    step: 1,
    integer: true,
    hint: "预缓冲模式下的分片时长；此时取代录制计划的目标分段时长。",
  },
  {
    key: "prebuffer_buffer_seconds",
    label: "预缓冲缓存时长",
    unit: "seconds",
    min: 10,
    max: 600,
    step: 1,
    integer: true,
    hint: "事件触发前保留多少秒的画面。",
  },
  {
    key: "turn_credential_ttl_seconds",
    label: "TURN 凭据有效期",
    unit: "seconds",
    min: 60,
    max: 3600,
    step: 1,
    integer: true,
    hint: "WebRTC 中转凭据的签发时长。",
  },
  {
    key: "playback_cache_max_bytes",
    label: "回放缓存上限",
    unit: "bytes",
    min: 64 * MIB,
    max: TIB,
    step: MIB,
    integer: true,
    hint: "远端录像回源后的本地缓存上限。",
  },
  {
    key: "playback_cache_ttl_seconds",
    label: "回放缓存有效期",
    unit: "seconds",
    min: 60,
    max: 7 * 24 * 60 * 60,
    step: 60,
    integer: true,
    hint: "缓存文件在无人引用后多久被清理。",
  },
  {
    key: "playback_restore_lock_ttl_seconds",
    label: "回源锁有效期",
    unit: "seconds",
    min: 60,
    max: 7 * 24 * 60 * 60,
    step: 60,
    integer: true,
    hint: "同一片段的并发回源请求会共用一把锁。",
  },
  {
    key: "live_transcode_max_derivatives",
    label: "转码路数上限",
    unit: "count",
    min: 1,
    max: 8,
    step: 1,
    integer: true,
    hint: "同时进行的兼容转码路数。",
  },
  {
    key: "live_transcode_idle_ttl_seconds",
    label: "转码空闲回收",
    unit: "seconds",
    min: 5,
    max: 300,
    step: 1,
    integer: true,
    hint: "无人观看后多久释放转码资源。",
  },
  {
    key: "live_transcode_lease_ttl_seconds",
    label: "转码租约时长",
    unit: "seconds",
    min: 15,
    max: 300,
    step: 1,
    integer: true,
    hint: "客户端需在此期间续期，否则转码被回收。",
  },
  {
    key: "live_transcode_startup_timeout_seconds",
    label: "转码启动超时",
    unit: "seconds",
    min: 1,
    max: 30,
    step: 0.5,
    integer: false,
    hint: "本组唯一的浮点字段。",
  },
  {
    key: "live_transcode_cpu_threads",
    label: "转码 CPU 线程",
    unit: "count",
    min: 1,
    max: 8,
    step: 1,
    integer: true,
    hint: "软转码占用的 CPU 线程数。",
  },
  {
    key: "live_transcode_video_bitrate_kbps",
    label: "转码视频码率",
    unit: "kbps",
    min: 512,
    max: 20_000,
    step: 256,
    integer: true,
    hint: "兼容转码输出码率。",
  },
] as const

export interface SettingsError {
  field: string
  message: string
}

export function validateRuntime(
  values: Partial<RuntimeTuning>,
): SettingsError[] {
  const errors: SettingsError[] = []
  for (const spec of RUNTIME_FIELDS) {
    const value = values[spec.key]
    if (value === undefined || value === null) continue

    if (!Number.isFinite(value)) {
      errors.push({ field: spec.key, message: `${spec.label}必须是数字` })
      continue
    }
    if (spec.integer && !Number.isInteger(value)) {
      errors.push({ field: spec.key, message: `${spec.label}必须是整数` })
      continue
    }
    if (value < spec.min || value > spec.max) {
      errors.push({
        field: spec.key,
        message: `${spec.label}需在 ${formatByUnit(spec.min, spec.unit)} – ${formatByUnit(
          spec.max,
          spec.unit,
        )} 之间`,
      })
    }
  }
  return errors
}

/* -------------------------------------------------------------------------- */
/* Formatting                                                                 */
/* -------------------------------------------------------------------------- */

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes)) return "—"
  if (bytes >= TIB) return `${round(bytes / TIB)} TiB`
  if (bytes >= GIB) return `${round(bytes / GIB)} GiB`
  if (bytes >= MIB) return `${round(bytes / MIB)} MiB`
  if (bytes >= 1024) return `${round(bytes / 1024)} KiB`
  return `${bytes} B`
}

function round(value: number): string {
  const rounded = Math.round(value * 10) / 10
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1)
}

export function formatByUnit(value: number, unit: FieldUnit): string {
  switch (unit) {
    case "bytes":
      return formatBytes(value)
    case "seconds":
      if (value >= 86400 && value % 86400 === 0) return `${value / 86400} 天`
      if (value >= 3600 && value % 3600 === 0) return `${value / 3600} 小时`
      if (value >= 60 && value % 60 === 0) return `${value / 60} 分钟`
      return `${round(value)} 秒`
    case "kbps":
      return `${round(value)} kbps`
    case "count":
      return String(value)
  }
}

/** Renders a value the way its own unit requires, never as a bare number. */
export function formatRuntimeValue(value: number, unit: FieldUnit): string {
  return formatByUnit(value, unit)
}

/* -------------------------------------------------------------------------- */
/* Alias handling                                                             */
/* -------------------------------------------------------------------------- */

export function parseServerList(raw: string): string[] {
  return raw
    .split(/[,\n]/)
    .map((entry) => entry.trim())
    .filter((entry) => entry.length > 0)
}

/**
 * The `general` group mirrors `time` rather than holding its own values, and
 * writing `general.camera_ntp_servers` also flips the mode
 * (`system/api.py:1086`). This is the single place that decides what a change
 * to the NTP list does to the mode, so the form does not have to know.
 */
export function ntpModeForServers(servers: readonly string[]): {
  managed_camera_ntp_mode: "manual" | "dhcp"
  managed_camera_ntp_servers: string[]
} {
  return {
    managed_camera_ntp_mode: servers.length > 0 ? "manual" : "dhcp",
    managed_camera_ntp_servers: [...servers],
  }
}

/**
 * Only the fields that actually changed are sent.
 *
 * `PATCH` applies `exclude_unset` per group, so resending unchanged values
 * would be harmless in isolation — except for the NTP list, where a
 * non-empty list rewrites the mode whether or not the operator touched it.
 */
export function diffRuntime(
  current: RuntimeTuning,
  next: Partial<RuntimeTuning>,
): Partial<RuntimeTuning> {
  const changed: Partial<RuntimeTuning> = {}
  for (const spec of RUNTIME_FIELDS) {
    const before = current[spec.key]
    const after = next[spec.key]
    if (after !== undefined && after !== before) {
      // Narrowed per key so the object stays assignable.
      ;(changed as Record<string, number>)[spec.key] = after
    }
  }
  return changed
}

export function describeSystemName(settings: SystemSettings): string {
  return settings.general.system_name || "zero-nvr"
}
