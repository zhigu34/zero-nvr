/**
 * Read-side camera contract.
 *
 * Mirrors `backend/app/modules/cameras/schemas.py`. Two things this module
 * deliberately does NOT pretend to have:
 *
 * 1. `GET /cameras` returns `CameraSummary`, which has no clock skew and no
 *    stream bindings — those live on `GET /cameras/{id}` (CameraDetail) and
 *    `GET /cameras/{id}/clock`. A list screen that shows either column is
 *    doing N+1 requests; that is a product decision, not an accident, so
 *    this module exposes them as separate calls rather than faking them.
 * 2. `connectivity_status` is a plain `str` on the backend, not a Literal.
 *    It is typed as a union with a fallback here so an unexpected value
 *    degrades to "unknown" instead of rendering blank.
 */
import { api } from "./client"

export type ConnectivityStatus = "online" | "offline" | "degraded" | "unknown"

export type CameraSummary = {
  id: string
  name: string
  enabled: boolean
  maintenance: boolean
  retired_at: string | null
  location: string | null
  storage_label: string | null
  adapter_type: string | null
  time_sync_mode: "monitor" | "manage_ntp" | "ignore"
  ptz_capable: boolean
  manufacturer: string | null
  model: string | null
  form_factor: string
  ip: string | null
  port: number | null
  rtsp_path: string | null
  sub_rtsp_path: string | null
  video_codec: string | null
  width: number | null
  height: number | null
  fps: number | null
  audio_codec: string | null
  connectivity_status: string
  last_probe_at: string | null
  last_online_at: string | null
}

export type StreamPurpose =
  | "RECORD"
  | "LIVE_HIGH"
  | "LIVE_LOW"
  | "AI_DETECT"
  | "SNAPSHOT"
  | "AUDIO"

/**
 * A recorded stream profile — `CameraStreamProfileView`
 * (`cameras/schemas.py:160-173`).
 *
 * The codec field is `codec`, **not** `video_codec`. The summary carries
 * `video_codec` (`cameras/schemas.py:128`) and the two are easy to conflate;
 * reading `video_codec` off a profile silently yields `undefined` for every
 * camera, because nothing named that is ever sent.
 */
export type CameraStreamProfile = {
  id: string
  name: string
  /** The adapter's own key for this profile. Stable across re-discovery. */
  adapter_profile_key: string
  codec: string | null
  width: number | null
  height: number | null
  fps: number | null
  bitrate_kbps: number | null
  gop_seconds: number | null
  audio_codec: string | null
  has_audio: boolean
  /** Free-form on the wire: `available`, `unavailable`, `unknown`, … */
  status: string
  last_verified_at: string | null
}

/**
 * `CameraStreamBindingView` (`cameras/schemas.py:176-179`).
 *
 * `stream_profile_id` is **not** nullable on the wire — the pydantic model types
 * it `uuid.UUID`, so a null would fail serialization server-side. `auto` is a
 * `selection_mode`, not a missing profile.
 */
export type CameraStreamBinding = {
  purpose: StreamPurpose
  stream_profile_id: string
  selection_mode: "auto" | "manual"
}

export type CameraDetail = CameraSummary & {
  streams: CameraStreamProfile[]
  bindings: CameraStreamBinding[]
}

/**
 * `CameraClockProjectionView` (`cameras/schemas.py:51-78`).
 *
 * `device_id` is what separates the two `unsupported` branches — a camera with
 * no device record at all (`cameras/api.py:1424-1431`) versus a device that is
 * not ONVIF (`:1437-1447`). Without it the two are the same string.
 *
 * `health` and `quality` are Literals on the server, not free strings. Typing
 * them as `string` here would let a typo in a label map compile silently.
 *
 * Note that `health === "unknown"` covers **two different situations**: the
 * channel is set to ignore the clock (`:1449-1456`) and the clock has simply
 * never been measured (`:1465-1472`). They are the same value, and only
 * `sync_mode` tells them apart — so the UI must not branch on `health` alone.
 */
export type CameraClockHealth =
  | "unknown"
  | "healthy"
  | "warning"
  | "critical"
  | "unsupported"

export type CameraClockQuality = "unknown" | "good" | "degraded" | "poor"

export type CameraClock = {
  camera_id: string
  device_id: string | null
  health: CameraClockHealth
  quality: CameraClockQuality
  sync_mode: TimeSyncMode
  measured_at: string | null
  offset_ms: number | null
  uncertainty_ms: number | null
  rtt_ms: number | null
  device_timezone: string | null
  device_time_source: string | null
  error_code: string | null
}

/* -------------------------------------------------------------------------- */
/* Capability health                                                          */
/* -------------------------------------------------------------------------- */

/**
 * `healthy | degraded | critical | unknown | unsupported | disabled`
 * (`cameras/schemas.py:82-88`).
 */
export type HealthState =
  | "healthy"
  | "degraded"
  | "critical"
  | "unknown"
  | "unsupported"
  | "disabled"

/**
 * `CameraCapabilityHealthLayerView`.
 *
 * `reason` is a stable machine code and `details` is an open dict whose keys
 * differ per reason, so both are rendered as text rather than destructured.
 */
export type CameraHealthLayer = {
  state: HealthState
  reason: string | null
  details: Record<string, unknown>
}

/** `CameraCapabilityHealthView` — six independent layers, one endpoint. */
export type CameraCapabilityHealth = {
  camera_id: string
  control: CameraHealthLayer
  media: CameraHealthLayer
  recording: CameraHealthLayer
  events: CameraHealthLayer
  ptz: CameraHealthLayer
  clock: CameraHealthLayer
}

export const HEALTH_STATE_LABEL: Record<HealthState, string> = {
  healthy: "正常",
  degraded: "降级",
  critical: "严重",
  unknown: "未知",
  unsupported: "不支持",
  disabled: "已停用",
}

/**
 * Every `reason` the projection can emit, from
 * `cameras/capability_health.py`. An unmapped code renders verbatim rather than
 * disappearing — a new reason is information, not noise.
 */
export const HEALTH_REASON_LABEL: Record<string, string> = {
  camera_retired: "通道已退役",
  camera_disabled: "通道已停用",
  device_disabled: "设备已停用",
  onvif_control_not_supported: "设备不支持 ONVIF 控制",
  onvif_events_not_supported: "设备不支持 ONVIF 事件",
  onvif_endpoint_unavailable: "ONVIF 端点不可用",
  ptz_not_supported: "设备不支持云台",
  device_clock_not_supported: "设备不支持时钟读取",
  clock_monitoring_ignored: "该通道已设为忽略时钟",
  awaiting_control_observation: "尚未观察到控制层状态",
  awaiting_media_observation: "尚未观察到媒体层状态",
  awaiting_recording_observation: "尚未观察到录制层状态",
  awaiting_ptz_observation: "尚未观察到云台状态",
  clock_not_measured: "尚未测量设备时钟",
  event_subscription_unobserved: "尚未观察到事件订阅",
  event_subscription_starting: "事件订阅正在建立",
  stream_bindings_missing: "未绑定任何码流",
  stream_binding_invalid: "码流绑定指向已不存在的 profile",
  bound_stream_unavailable: "已绑定的码流不可用",
  recording_not_enabled: "该通道没有启用的录制计划",
  recording_stream_binding_missing: "录制计划未绑定码流",
  recording_stream_binding_invalid: "录制计划绑定的码流已失效",
  recording_stream_unavailable: "录制用码流不可用",
  recording_not_currently_required: "当前时段不需要录制",
  recording_media_offline: "录制媒体层离线",
  recording_source_offline: "录制源离线",
  recording_inactive: "录制未在进行中",
}

export const HEALTH_LAYER_LABEL: Record<keyof CameraCapabilityHealth, string> = {
  camera_id: "",
  control: "控制",
  media: "媒体",
  recording: "录制",
  events: "事件",
  ptz: "云台",
  clock: "时钟",
}

/** Layer order is the order an operator triages in, not the schema's. */
export const HEALTH_LAYER_ORDER = [
  "control",
  "media",
  "recording",
  "events",
  "ptz",
  "clock",
] as const satisfies readonly (keyof CameraCapabilityHealth)[]

/**
 * The layers that can legitimately report `healthy`.
 *
 * The projection is explicit that it proves states from stored configuration,
 * not from a live observation feed (`capability_health.py:45-49`). Reading the
 * six projections, three of them have **no** `healthy` branch at all:
 *
 * - `control` → unsupported / disabled / degraded / unknown, never healthy
 * - `ptz`     → unsupported / disabled / degraded / unknown, never healthy
 * - `clock`   → unsupported / disabled / unknown, never healthy
 *
 * `media`, `recording` and `events` do have one, derived from bindings, the
 * policy window and the subscription state respectively.
 *
 * So a panel that showed "正常" for a healthy-looking control or PTZ layer would
 * be reporting something the backend cannot produce. The UI uses this to say
 * *why* a layer is stuck at 未知 instead of leaving the operator to guess.
 */
export const HEALTHY_POSSIBLE_LAYERS = new Set<
  keyof Omit<CameraCapabilityHealth, "camera_id">
>(["media", "recording", "events"])

/* -------------------------------------------------------------------------- */
/* Stream diagnostics                                                         */
/* -------------------------------------------------------------------------- */

/** `CameraProbeTrackView` (`cameras/schemas.py:204-213`). */
export type CameraProbeTrack = {
  kind: "video" | "audio"
  codec: string | null
  /** `false` means the track exists but the probe could not read it. */
  ready: boolean
  width: number | null
  height: number | null
  fps: number | null
  gop_seconds: number | null
  sample_rate: number | null
  channels: number | null
}

/**
 * `CameraStreamDiagnosticView` (`cameras/schemas.py:216-220`).
 *
 * Returned only on success. A probe failure raises instead, with
 * `details.profile_id` set (`cameras/api.py:1960-1969`).
 */
export type CameraStreamDiagnostic = {
  profile: CameraStreamProfile
  video: CameraProbeTrack | null
  audio: CameraProbeTrack | null
  verified_at: string
}

/** Profile `status` values written by verify and refresh. */
export const STREAM_STATUS_LABEL: Record<string, string> = {
  available: "可用",
  unavailable: "不可用",
  unknown: "未验证",
}

/**
 * How a binding reads on screen.
 *
 * `stream_profile_id` is non-nullable and the FK is `ondelete="RESTRICT"`
 * (`cameras/models.py:342-346`), so a binding always points at a profile that
 * exists. The missing-profile branch is therefore not reachable through the
 * API — it exists so a cross-camera or hand-edited row degrades to a readable
 * warning instead of rendering `undefined`, and because the health projection
 * explicitly models the case as `stream_binding_invalid`.
 *
 * `auto` is **not** "unbound": the profile is real, the *choice* of it is the
 * server's. Rendering it as empty would tell the operator a stream is missing
 * when one is selected.
 */
export function boundStreamName(
  streams: readonly CameraStreamProfile[],
  binding: CameraStreamBinding,
): string {
  const profile = streams.find((item) => item.id === binding.stream_profile_id)
  if (!profile) return "绑定的码流已不存在"
  return binding.selection_mode === "auto"
    ? `${profile.name}（自动）`
    : profile.name
}

export const STREAM_PURPOSE_LABEL: Record<StreamPurpose, string> = {
  RECORD: "录像",
  LIVE_HIGH: "实时主码流",
  LIVE_LOW: "实时子码流",
  AI_DETECT: "AI 检测",
  SNAPSHOT: "抓图",
  AUDIO: "音频",
}

/** Backend sends a bare string; anything unrecognised becomes "unknown". */
export function normalizeConnectivity(raw: string): ConnectivityStatus {
  const v = raw?.toLowerCase()
  if (v === "online" || v === "offline" || v === "degraded") return v
  return "unknown"
}

export function listCameras(
  params: { includeRetired?: boolean } = {},
  signal?: AbortSignal,
) {
  const qs = new URLSearchParams()
  if (params.includeRetired) qs.set("include_retired", "true")
  const suffix = qs.toString() ? `?${qs}` : ""
  return api.get<CameraSummary[]>(`/cameras${suffix}`, signal)
}

export function getCamera(id: string, signal?: AbortSignal) {
  return api.get<CameraDetail>(`/cameras/${id}`, signal)
}

export function getCameraClock(id: string, signal?: AbortSignal) {
  return api.get<CameraClock>(`/cameras/${id}/clock`, signal)
}

export function getCameraHealth(id: string, signal?: AbortSignal) {
  return api.get<CameraCapabilityHealth>(`/cameras/${id}/health`, signal)
}

/**
 * `GET /cameras/{id}/streams` is redundant with `CameraDetail.streams` — same
 * rows, same projection (`cameras/api.py:340-355`). It exists, and it is
 * deliberately not called: one detail request beats a detail request plus a
 * second one for a subset of the same payload.
 */

/**
 * Probe one profile through the real media path and return what was measured.
 *
 * Only succeeds when the probe succeeds. A failure raises with the ZLM status
 * and code passed straight through and `details.profile_id` set
 * (`cameras/api.py:1960-1969`) — the endpoint's own `camera_stream_profile_not_found`
 * (404) is the only code it originates.
 *
 * The Vue panel called this and **threw the response away**, showing a fixed
 * "已更新最新状态与分辨率" string instead (`CameraDetailStreamsTab.vue:199`). The
 * measured tracks are the whole point of a diagnostic, so they are surfaced.
 */
export function verifyStreamProfile(
  id: string,
  profileId: string,
  signal?: AbortSignal,
) {
  return api.post<CameraStreamDiagnostic>(
    `/cameras/${id}/streams/${profileId}/verify`,
    undefined,
    signal,
  )
}

/* -------------------------------------------------------------------------- */
/* Writes                                                                     */
/* -------------------------------------------------------------------------- */

/**
 * `mode` is accepted by the schema but has exactly one legal value today, so
 * it is not offered as a choice anywhere in the UI.
 */
export type ManualRtspStreamInput = {
  name: string
  rtsp_url: string
}

export type CameraCreate = {
  name: string
  primary_stream: ManualRtspStreamInput
  location?: string | null
  storage_label?: string | null
  secondary_stream?: ManualRtspStreamInput | null
}

/**
 * Every field is optional and the backend applies `exclude_unset`, so a field
 * left out here is genuinely untouched. Sending `null` clears it — which is
 * the only way to remove a location, and the reason the form must track
 * "changed" separately from "present".
 */
export type CameraUpdate = {
  name?: string | null
  location?: string | null
  storage_label?: string | null
  maintenance?: boolean | null
  time_sync_mode?: TimeSyncMode | null
  manufacturer?: string | null
  model?: string | null
  form_factor?: FormFactor | null
}

export type TimeSyncMode = "monitor" | "manage_ntp" | "ignore"

export type FormFactor =
  | "box"
  | "dome"
  | "bullet"
  | "ptz"
  | "fisheye"
  | "multi_sensor"
  | "encoder"
  | "nvr"
  | "unknown"

/**
 * `selection_mode` is **required**, not optional.
 *
 * The Vue panel hardcoded `"manual"` for every row and dropped whatever was
 * stored, so an `auto` binding created at import time was silently rewritten the
 * first time an operator saved any purpose on that camera. Making the field
 * mandatory means a caller that forgets it is a type error rather than a silent
 * data change.
 */
export type CameraStreamBindingInput = {
  purpose: StreamPurpose
  stream_profile_id: string
  selection_mode: "auto" | "manual"
}

/**
 * The `selection_mode` to submit for one purpose.
 *
 * `auto` is not a display preference — it means **the live path re-picks the
 * profile on every request**, scoring candidates for H.264 and taking the best
 * (`cameras/api.py:2331-2345`). So an operator who selects a specific profile in
 * this form while the row is still `auto` gets their choice ignored: the save
 * reports success and playback does not change.
 *
 * That makes the touched/untouched distinction the whole answer:
 *
 * - **touched** — the operator just made a choice. That *is* a manual selection,
 *   so it must be stored as `manual` or their pick is discarded at runtime.
 * - **untouched** — the form is not expressing an opinion about this purpose, so
 *   the stored mode is round-tripped verbatim. Rewriting an `auto` to `manual`
 *   here would silently take the server's right to re-pick away, which is how the
 *   Vue version lost bindings in the first place.
 */
export function bindingSelectionMode(
  existing: CameraStreamBinding | undefined,
  touched: boolean,
): "auto" | "manual" {
  if (touched) return "manual"
  return existing?.selection_mode ?? "manual"
}

export function createCamera(body: CameraCreate, signal?: AbortSignal) {
  return api.post<CameraDetail>("/cameras", body, signal)
}

export function updateCamera(
  id: string,
  body: CameraUpdate,
  signal?: AbortSignal,
) {
  return api.patch<CameraDetail>(`/cameras/${id}`, body)
}

export function enableCamera(id: string, signal?: AbortSignal) {
  return api.post<CameraDetail>(`/cameras/${id}/enable`, undefined, signal)
}

export function disableCamera(id: string, signal?: AbortSignal) {
  return api.post<CameraDetail>(`/cameras/${id}/disable`, undefined, signal)
}

/** Retiring also forces `enabled = false` and stops manual recording triggers. */
export function retireCamera(id: string, signal?: AbortSignal) {
  return api.post<CameraDetail>(`/cameras/${id}/retire`, undefined, signal)
}

/** Restoring returns the camera to the inventory but leaves it disabled. */
export function restoreCamera(id: string, signal?: AbortSignal) {
  return api.post<CameraDetail>(`/cameras/${id}/restore`, undefined, signal)
}

export function probeCamera(id: string, signal?: AbortSignal) {
  return api.post<CameraDetail>(`/cameras/${id}/probe`, undefined, signal)
}

export function listStreamBindings(id: string, signal?: AbortSignal) {
  return api.get<CameraStreamBinding[]>(
    `/cameras/${id}/stream-bindings`,
    signal,
  )
}

/**
 * Replaces every binding at once. Anything omitted is cleared, so the caller
 * must send the full desired set rather than a delta.
 */
export function replaceStreamBindings(
  id: string,
  bindings: CameraStreamBindingInput[],
) {
  return api.put<CameraStreamBinding[]>(
    `/cameras/${id}/stream-bindings`,
    { bindings },
  )
}

export type CameraProbeResult = {
  ok: true
  reachable: boolean
  width: number | null
  height: number | null
  fps: number | null
  video_codec: string | null
  audio_codec: string | null
  latency_ms: number | null
}

/** Probes without persisting; used to validate a URL before offering to save. */
export function testCameraStreams(
  body: CameraCreate,
  signal?: AbortSignal,
) {
  return api.post<CameraProbeResult>("/cameras/test", body, signal)
}
