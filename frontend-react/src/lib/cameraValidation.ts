/**
 * Client-side validation for camera writes.
 *
 * This is not a substitute for server validation — every rule here is also
 * enforced in the backend. It exists because two of the backend's behaviours
 * are **silent rather than loud**, and a silent rejection is the worst kind:
 *
 * 1. `manufacturer` / `model` / `form_factor` are discarded without any error
 *    when the camera has no `device_id` (`cameras/service.py:438`). The save
 *    returns 200 and the values are gone on the next read.
 * 2. `time_sync_mode` other than `ignore` is rejected with a 400 that arrives
 *    *after* the operator has filled in the rest of the form
 *    (`cameras/service.py:405`), because the rule depends on the camera's
 *    adapter type, which is not part of the update payload.
 *
 * Both are better caught before the request than explained after it.
 */
import type { TimeSyncMode } from "../api/cameras"

export interface FieldError {
  field: string
  message: string
}

/**
 * The backend uses `urlsplit` and then requires an `rtsp` scheme plus a host;
 * a port is optional and defaults to 554. Anything else is `invalid_rtsp_url`.
 */
export function validateRtspUrl(raw: string): string | null {
  const value = raw.trim()
  if (!value) return "RTSP 地址不能为空"
  // Credentials in the URL are how this product is deployed; never reject them.
  let parsed: URL
  try {
    parsed = new URL(value)
  } catch {
    return "RTSP 地址格式不正确"
  }
  if (parsed.protocol !== "rtsp:") return "RTSP 地址必须以 rtsp:// 开头"
  if (!parsed.hostname) return "RTSP 地址缺少主机名"
  if (parsed.port && !/^\d+$/.test(parsed.port)) return "端口必须是数字"
  return null
}

export function validateCameraName(raw: string): string | null {
  const value = raw.trim()
  if (!value) return "机位名称不能为空"
  if (value.length > 128) return "机位名称不能超过 128 个字符"
  return null
}

/**
 * Time sync only works for devices the server can actually manage, which today
 * means ONVIF. A manual RTSP camera can only be set to `ignore`.
 */
export function allowedTimeSyncModes(
  adapterType: string | null | undefined,
): TimeSyncMode[] {
  return adapterType === "onvif"
    ? ["manage_ntp", "monitor", "ignore"]
    : ["ignore"]
}

export function validateTimeSyncMode(
  mode: TimeSyncMode,
  adapterType: string | null | undefined,
): string | null {
  if (allowedTimeSyncModes(adapterType).includes(mode)) return null
  return "只有 ONVIF 接入的机位才能托管 NTP；手动 RTSP 接入只能设为「忽略」"
}

/**
 * Whether the device-description fields will be stored at all. A camera
 * without a `device_id` silently drops them, so the form must not offer them.
 */
export function acceptsDeviceFields(deviceId: string | null): boolean {
  return deviceId !== null && deviceId !== ""
}

export interface StreamBindingDraft {
  purpose: string
  streamProfileId: string
}

export type BindingProblem =
  | { kind: "duplicate_purpose"; purpose: string }
  | { kind: "missing_profile"; purpose: string }

/**
 * `PUT /stream-bindings` rejects a repeated purpose with
 * `duplicate_stream_purpose` and the whole batch fails, so a duplicate in the
 * form has to be caught before the request or the operator loses every
 * binding they configured to fix one row.
 */
export function validateBindings(
  drafts: readonly StreamBindingDraft[],
): BindingProblem[] {
  const problems: BindingProblem[] = []
  const seen = new Set<string>()

  for (const draft of drafts) {
    if (seen.has(draft.purpose)) {
      problems.push({ kind: "duplicate_purpose", purpose: draft.purpose })
    }
    seen.add(draft.purpose)
    if (!draft.streamProfileId) {
      problems.push({ kind: "missing_profile", purpose: draft.purpose })
    }
  }
  return problems
}

/** Full pre-flight for the create/update form. */
export function validateCameraForm(input: {
  name: string
  adapterType: string | null | undefined
  timeSyncMode?: TimeSyncMode
  rtspUrl?: string
  isCreate: boolean
}): FieldError[] {
  const errors: FieldError[] = []

  const nameError = validateCameraName(input.name)
  if (nameError) errors.push({ field: "name", message: nameError })

  if (input.isCreate) {
    const rtspError = validateRtspUrl(input.rtspUrl ?? "")
    if (rtspError) errors.push({ field: "rtsp_url", message: rtspError })
  }

  if (input.timeSyncMode) {
    const syncError = validateTimeSyncMode(
      input.timeSyncMode,
      input.adapterType,
    )
    if (syncError) {
      errors.push({ field: "time_sync_mode", message: syncError })
    }
  }

  return errors
}
