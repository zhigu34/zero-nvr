/**
 * Turning a policy's observed runtime into something an operator can act on.
 *
 * The whole point of this module is that a 200 response does not mean the
 * camera is recording. `PUT /cameras/{id}/recording-policy` swallows
 * `recording_stream_offline` and ZLM's start-timeout and reports the outcome
 * only here. A page that renders the HTTP status and nothing else will tell
 * an operator that continuous recording is active on a camera that is
 * writing nothing.
 *
 * The second thing it gets right is that `runtime.recording` is tri-state.
 * `null` means the media runtime cannot be observed — a different problem
 * from "not recording", and one that must not be drawn as "未录制", because
 * that sends the operator looking for a fault that may not exist.
 */
import type {
  BaselineMode,
  RecordingRuntime,
} from "../api/recordingPolicies"

export type RecordingHealth =
  /** Confirmed writing. */
  | "recording"
  /** Confirmed not writing, with a reason the operator can chase. */
  | "not_recording"
  /** We genuinely cannot tell — the runtime is not observable. */
  | "unobservable"
  /** The policy itself would not record even if everything worked. */
  | "not_configured_to_record"
  /** No runtime has been observed yet. */
  | "unknown"

export interface RuntimeVerdict {
  health: RecordingHealth
  /** Short, plain-language explanation. Never empty for a non-healthy state. */
  message: string
  /** Backend error codes, kept verbatim so they stay searchable. */
  blockers: string[]
}

/**
 * Backend blocker codes, explained. Anything unrecognised falls through as
 * the raw code rather than being swallowed — an unfamiliar code is a signal
 * that the backend gained a failure mode this table has not caught up with.
 */
const BLOCKER_LABEL: Record<string, string> = {
  recording_storage_capacity_critical: "存储容量已到临界水位",
  recording_storage_unavailable: "存储目标不可用",
  recording_stream_offline: "摄像机码流离线",
  recording_stream_binding_missing: "未绑定录制用的码流",
  recording_policy_disabled: "录制计划已停用",
  recording_camera_disabled: "机位已停用",
  camera_retired: "机位已退役",
}

export function describeBlocker(code: string): string {
  return BLOCKER_LABEL[code] ?? `录制被阻塞：${code}`
}

export function judgeRuntime(
  runtime: RecordingRuntime | null | undefined,
  baselineMode: BaselineMode,
  enabled: boolean,
): RuntimeVerdict {
  const blockers = Array.isArray(runtime?.blockers) ? runtime.blockers : []

  if (!enabled || baselineMode === "disabled") {
    return {
      health: "not_configured_to_record",
      message: !enabled ? "录制计划已停用" : "当前模式为「不录制」",
      blockers,
    }
  }

  if (runtime === null || runtime === undefined) {
    return {
      health: "unknown",
      message: "尚未观测到录制状态",
      blockers,
    }
  }

  // A blocker is a stronger statement than either recording flag, and it is
  // the only place the reason for a stopped camera is actually given.
  if (blockers.length > 0) {
    return {
      health: "not_recording",
      message: blockers.map(describeBlocker).join("；"),
      blockers,
    }
  }

  if (runtime.recording === null) {
    return {
      health: "unobservable",
      message: "媒体运行时不可观测，无法确认是否在录制（机位离线或服务未上报）",
      blockers,
    }
  }

  if (runtime.recording) {
    return { health: "recording", message: "正在录制", blockers }
  }

  // Not recording and not unobservable and no blocker: the camera is up and
  // the policy wants recording, so it is either still starting or something
  // outside the reported blockers is stopping it.
  return {
    health: "not_recording",
    message: runtime.stream_online
      ? "码流在线但未在录制，可能仍在启动或刚被停止"
      : "码流不在线，无法开始录制",
    blockers,
  }
}

/** Tone for the status dot. `unobservable` is neither good nor bad. */
export function runtimeTone(health: RecordingHealth) {
  switch (health) {
    case "recording":
      return "online" as const
    case "unobservable":
    case "unknown":
      return "unknown" as const
    default:
      return "offline" as const
  }
}

/* -------------------------------------------------------------------------- */
/* Duration formatting                                                        */
/* -------------------------------------------------------------------------- */

/**
 * Policy durations are seconds; stored segments are milliseconds. Both appear
 * on this page, so each gets a helper that names its unit rather than a
 * formatter that guesses.
 */
export function formatSeconds(value: number): string {
  if (!Number.isFinite(value)) return "—"
  if (value >= 3600) {
    const hours = value / 3600
    return `${Number.isInteger(hours) ? hours : hours.toFixed(1)} 小时`
  }
  if (value >= 60) {
    const minutes = value / 60
    return `${Number.isInteger(minutes) ? minutes : minutes.toFixed(1)} 分钟`
  }
  return `${value} 秒`
}

export function formatMilliseconds(value: number): string {
  if (!Number.isFinite(value)) return "—"
  return formatSeconds(value / 1000)
}

export const BASELINE_MODE_LABEL: Record<BaselineMode, string> = {
  continuous: "连续录制",
  schedule: "按计划录制",
  disabled: "不录制",
}

export const DESIRED_MODE_LABEL: Record<string, string> = {
  persistent: "持续写入",
  prebuffer: "预缓冲（事件触发）",
  off: "停止",
}
