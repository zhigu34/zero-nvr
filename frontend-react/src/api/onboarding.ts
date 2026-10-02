/**
 * Camera-onboarding contract. Mirrors
 * `backend/app/modules/cameras/{api,schemas,onvif_onboarding,discovery_service}.py`.
 *
 * ## The flow is five calls, and only two of them write
 *
 * ```text
 * POST /cameras/discovery            → candidates            (3 s, WS-Discovery)
 * POST /cameras/onvif/test           → inspection            (10 s, read-only)
 * POST /cameras/onvif/import         → device + cameras      (writes)
 * POST /cameras/test                 → probe result          (12 s, read-only)
 * POST /cameras                      → camera                (writes)
 * ```
 *
 * `POST /cameras` does **not** probe the stream — it validates only
 * `invalid_rtsp_url` syntax (`cameras/service.py:104,112`). The
 * probe-before-create ordering the Vue wizard used
 * (`CameraOnboardingPanel.vue:873-874`) is a client convention, not an enforced
 * invariant, so the React wizard keeps it as a deliberate step rather than
 * assuming the server checked.
 *
 * ## Batch is 100% client-side
 *
 * There is no bulk endpoint and no CSV parsing on the server. The Vue panel
 * loops rows **serially**, calling inspect then import (or test then create) for
 * each. There is also **no dry-run**: `POST /cameras/onvif/import` is the only
 * "validation" and it writes. So a batch is not atomic and cannot be previewed
 * (G-39) — the UI must show per-row outcomes and never promise an all-or-nothing
 * result.
 *
 * ## `profile_tokens: null` means "every profile", not "none"
 *
 * `_usable_profiles` selects all profiles when the field is `None`
 * (`onvif_onboarding.py:229-230`). Sending `[]` takes a different path and can
 * reach 422 `onvif_no_usable_profiles`. This is the same absent-vs-empty
 * distinction as the backup and notification contracts, and it is the one most
 * likely to be got wrong, because a form that starts with nothing checked
 * naturally sends `[]`.
 *
 * ## N profiles is not N cameras
 *
 * Cameras are grouped by `video_source_token`
 * (`onvif_onboarding.py:1149-1176`), so a multi-channel device produces several
 * cameras named `"<name> 1"`, `"<name> 2"` from **one** import. Never assume
 * `cameras.length === profile_tokens.length`.
 *
 * ## Identity is a four-state machine and one state needs an echo
 *
 * ```text
 * new_device                          → import directly
 * same_device                         → offer refresh instead of import
 * probable_match_requires_confirmation→ resend with confirm_existing_device_id
 * identity_conflict                   → unrecoverable via import
 * ```
 *
 * `confirm_existing_device_id` must be echoed **exactly** as
 * `identity.matched_device_id`; any other value produces a *different* 409,
 * `onvif_device_identity_confirmation_invalid` (`:490, :547`). So one user
 * mistake can surface two different messages, and the form has to send the id
 * the server just gave it rather than one it derived.
 *
 * ## Everything network-bound shares one code
 *
 * ONVIF auth failure, a wrong IP and a firewall all arrive as 422
 * `onvif_connection_failed` with the raw SOAP text suppressed
 * (`onvif_adapter.py:471-479`). Branching on the status to say "wrong password"
 * is not possible, so the form must not imply it knows which.
 *
 * ## A 503 on import means the camera graph already exists
 *
 * `details.configuration_persisted: true` (`api.py:893-904`). Fourth instance
 * of the pattern in G-17/G-23 — see `importPersistedAnyway`.
 *
 * ## Credentials never come back, and a manual camera's cannot be changed
 *
 * `rtsp_url` is a `SecretStr` on input and is stored encrypted in the
 * `SecretStore` keyring (`onvif_onboarding.py:730-743`, `service.py:136`).
 * `CameraSummary` exposes only `rtsp_path` / `sub_rtsp_path` — no host, no
 * userinfo — and inspection returns `stream_uri_available: boolean`, never the
 * URI. Worse, `CameraUpdate` has **no** stream or credential field at all
 * (`schemas.py:36`), so a manual camera's RTSP password can only be changed by
 * deleting and recreating it (G-38). The form has to say so at creation time,
 * because afterwards there is nowhere to say it.
 */
import { api, ApiError } from "./client"
import type { CameraSummary } from "./cameras"

/* -------------------------------------------------------------------------- */
/* Discovery                                                                  */
/* -------------------------------------------------------------------------- */

export type DiscoveryCandidateView = {
  id: string
  candidate_key: string
  host: string | null
  port: number | null
  device_service_url: string | null
  /** Built from WS-Discovery scopes: `name`, `hardware`, `location`, `host`. */
  display_info: Record<string, unknown>
  state: string
}

export type DiscoverySessionView = {
  id: string
  /** `onvif_ws_discovery` in practice. */
  method: string
  status: string
  started_at: string
  completed_at: string | null
  candidates: DiscoveryCandidateView[]
}

export const DISCOVERY_MAX_SOURCE_ADDRESSES = 16

/* -------------------------------------------------------------------------- */
/* Inspection                                                                 */
/* -------------------------------------------------------------------------- */

export type OnvifDeviceInfo = {
  manufacturer: string | null
  model: string | null
  firmware_version: string | null
  serial_number: string | null
  hardware_id: string | null
}

export type OnvifProfileView = {
  token: string
  name: string
  video_source_token: string
  codec: string
  width: number | null
  height: number | null
  fps: number | null
  bitrate_kbps: number | null
  gop_seconds: number | null
  audio_codec: string | null
  has_audio: boolean
  /** The real gate. A profile can exist with no usable stream URI. */
  stream_uri_available: boolean
}

export type OnvifIdentityState =
  | "new_device"
  | "same_device"
  | "probable_match_requires_confirmation"
  | "identity_conflict"

export type OnvifIdentityView = {
  state: OnvifIdentityState
  matched_device_id: string | null
  matched_device_name: string | null
  conflicting_device_ids: string[]
  reason: string | null
}

export type OnvifInspectionView = {
  device: OnvifDeviceInfo
  capabilities: string[]
  profiles: OnvifProfileView[]
  identity: OnvifIdentityView
}

export type OnvifProbeInput = {
  /** A bare host: the schema rejects `://`, `/`, `@` and whitespace. */
  host: string
  port?: number
  username?: string
  password: string
}

export const ONVIF_PORT_MIN = 1
export const ONVIF_PORT_MAX = 65535
export const ONVIF_HOST_MAX = 512

/* -------------------------------------------------------------------------- */
/* Import                                                                     */
/* -------------------------------------------------------------------------- */

export type OnvifImportInput = OnvifProbeInput & {
  name?: string | null
  location?: string | null
  storage_label?: string | null
  /** `null` = every usable profile. `[]` is a different, usually failing, ask. */
  profile_tokens?: string[] | null
  discovery_candidate_id?: string | null
  /** Must equal `identity.matched_device_id` exactly. */
  confirm_existing_device_id?: string | null
}

export type OnvifImportResult = {
  device_id: string
  reconfigured: boolean
  /**
   * Grouped by `video_source_token`, so this can exceed the profile count.
   *
   * Typed as `CameraSummary` rather than `unknown[]`: the response is
   * `list[CameraDetail]`, which is the summary plus `streams` and `bindings`
   * (`cameras/schemas.py:182`). The wizard only needs the summary fields, and
   * typing it keeps the cast-and-re-narrow out of every call site.
   */
  cameras: CameraSummary[]
}

export type OnvifRefreshDiff = {
  profiles_added: string[]
  profiles_missing: string[]
  profiles_changed: string[]
  profiles_recovered: string[]
  profiles_unmapped_added: string[]
  capabilities_added: string[]
  capabilities_removed: string[]
}

export type OnvifCapabilityRefreshResult = {
  device_id: string
  diff: OnvifRefreshDiff
  cameras: CameraSummary[]
}

/* -------------------------------------------------------------------------- */
/* Manual RTSP                                                                */
/* -------------------------------------------------------------------------- */

export type CameraStreamInput = {
  name: string
  /** SecretStr on the wire; stored encrypted; never returned. */
  rtsp_url: string
}

export type CameraCreateInput = {
  mode?: "manual_rtsp"
  name: string
  location?: string | null
  storage_label?: string | null
  primary_stream: CameraStreamInput
  secondary_stream?: CameraStreamInput | null
}

export type CameraProbeTrackView = {
  kind: string
  codec: string | null
  ready: boolean
  width: number | null
  height: number | null
  fps: number | null
  /** Seconds. */
  gop_seconds: number | null
  sample_rate: number | null
  channels: number | null
}

export type CameraProbeStreamView = {
  role: "primary" | "secondary"
  name: string
  video: CameraProbeTrackView | null
  audio: CameraProbeTrackView | null
}

export type CameraProbeResult = {
  ok: true
  streams: CameraProbeStreamView[]
}

export const CAMERA_NAME_MAX = 128
export const CAMERA_LOCATION_MAX = 256
export const CAMERA_STORAGE_LABEL_MAX = 128

/* -------------------------------------------------------------------------- */
/* Endpoints                                                                  */
/* -------------------------------------------------------------------------- */

/**
 * WS-Discovery multicast probe, 3 s server-side
 * (`core/config/settings.py:76`). **Not** a subnet sweep and not mDNS, so it
 * finds only devices on the same broadcast domain.
 *
 * The POST is synchronous and already returns the completed session, so
 * `getDiscoverySession` exists for re-reading a failed one — the row is
 * committed with `status="failed"` and `details.discovery_id` in the error
 * (`api.py:1255-1282`).
 */
export function startDiscovery(sourceAddresses: string[] = []) {
  const qs = new URLSearchParams()
  for (const address of sourceAddresses) qs.append("source_address", address)
  const query = qs.toString()
  return api.post<DiscoverySessionView>(
    `/cameras/discovery${query ? `?${query}` : ""}`,
  )
}

export function getDiscoverySession(
  discoveryId: string,
  signal?: AbortSignal,
) {
  return api.get<DiscoverySessionView>(
    `/cameras/discovery/${discoveryId}`,
    signal,
  )
}

/** Read-only. 10 s server-side. Auth failures arrive as 422, not 401. */
export function inspectOnvif(body: OnvifProbeInput) {
  return api.post<OnvifInspectionView>("/cameras/onvif/test", body)
}

/**
 * Creates the device, its cameras, profiles, credential and endpoints.
 *
 * Order is identity → commit → ZLM probe of every selected profile → persist
 * (`api.py:774-776`), so a probe failure creates nothing at all. Slow by
 * construction: 10 s inspection plus 12 s per selected profile.
 */
export function importOnvifDevice(body: OnvifImportInput) {
  return api.post<OnvifImportResult>("/cameras/onvif/import", body)
}

/**
 * Re-read capabilities for a device already onboarded.
 *
 * The path segment is a **device** id, not a camera id — the result carries
 * `device_id` and the response is a list of every camera on that device
 * (`cameras/api.py:916`). Naming the parameter `cameraId` invites a caller to
 * pass a camera id and get a 404, so it is `deviceId` on purpose.
 */
export function refreshOnvifCapabilities(deviceId: string) {
  return api.post<OnvifCapabilityRefreshResult>(`/cameras/${deviceId}/onvif/refresh`)
}

/** Opens a real ZLM proxy per stream, 12 s timeout (`settings.py:64`). */
export function testManualCamera(body: CameraCreateInput) {
  return api.post<CameraProbeResult>("/cameras/test", body)
}

/**
 * Creates the camera. **Does not probe** — only `invalid_rtsp_url` is checked,
 * and the camera lands enabled with `adapter_type="manual_rtsp"` and an empty
 * `capabilities_json` (`service.py:161-166`).
 */
export function createManualCamera(body: CameraCreateInput) {
  return api.post<unknown>("/cameras", body)
}

/* -------------------------------------------------------------------------- */
/* The 503 that means "it worked"                                            */
/* -------------------------------------------------------------------------- */

/** Fourth instance of the G-17 / G-23 pattern, this time on import. */
export function importPersistedAnyway(error: unknown): {
  persisted: true
  deviceId: string | null
} | null {
  if (!(error instanceof ApiError)) return null
  if (error.details?.configuration_persisted !== true) return null
  const id = error.details.device_id
  return { persisted: true, deviceId: typeof id === "string" ? id : null }
}

/* -------------------------------------------------------------------------- */
/* Identity                                                                   */
/* -------------------------------------------------------------------------- */

export const IDENTITY_STATE_LABEL: Record<OnvifIdentityState, string> = {
  new_device: "新设备",
  same_device: "已在本系统中",
  probable_match_requires_confirmation: "疑似已录入，需确认",
  identity_conflict: "身份冲突",
}

/**
 * What the wizard may do next, given the identity verdict.
 *
 * `identity_conflict` has no path forward through import
 * (`onvif_onboarding.py:462-481`) — the operator has to resolve it out of band,
 * and the UI must not offer a button that will 409.
 */
export function identityAction(
  identity: OnvifIdentityView,
): "import" | "refresh" | "confirm" | "blocked" {
  switch (identity.state) {
    case "new_device":
      return "import"
    case "same_device":
      return "refresh"
    case "probable_match_requires_confirmation":
      return "confirm"
    case "identity_conflict":
      return "blocked"
    default:
      return "blocked"
  }
}

export function identityBlockedReason(
  identity: OnvifIdentityView,
): string | null {
  if (identityAction(identity) !== "blocked") return null
  return (
    `该设备与本系统中已有的设备身份冲突` +
    `${identity.matched_device_name ? `（${identity.matched_device_name}）` : ""}` +
    "，无法通过导入新增。请先在设备列表中确认并移除冲突的记录。"
  )
}

/**
 * The `confirm_existing_device_id` to echo back, or `null`.
 *
 * Deliberately derived from the server's own `matched_device_id` and nothing
 * else. Deriving it from anything local is how a wizard ends up sending a
 * different 409 for the same mistake.
 */
export function confirmationIdFor(
  identity: OnvifIdentityView,
): string | null {
  return identity.state === "probable_match_requires_confirmation"
    ? identity.matched_device_id
    : null
}

/* -------------------------------------------------------------------------- */
/* Build body                                                                 */
/* -------------------------------------------------------------------------- */

export type OnvifForm = {
  host: string
  port: number
  username: string
  password: string
  name: string
  location: string
  storageLabel: string
  /** Which profile tokens the operator ticked. */
  selectedProfileTokens: string[]
  /** True when the operator explicitly ticked nothing. */
  selectionTouched: boolean
  discoveryCandidateId: string | null
}

export type OnvifFormField =
  | "host"
  | "port"
  | "password"
  | "name"
  | "location"
  | "storageLabel"
  | "profiles"

export type OnvifFormError = { field: OnvifFormField; message: string }

export function emptyOnvifForm(host = "", port = 80): OnvifForm {
  return {
    host,
    port,
    username: "",
    password: "",
    name: "",
    location: "",
    storageLabel: "",
    selectedProfileTokens: [],
    selectionTouched: false,
    discoveryCandidateId: null,
  }
}

/**
 * The host validator, mirrored.
 *
 * The schema rejects `://`, `/`, `@` and whitespace
 * (`cameras/schemas.py:260-272`) because the field is a bare host, not a URL.
 * Checking it here names the rule instead of returning a 422 about a field the
 * operator filled in what looked like a perfectly good address.
 */
export function validateOnvifForm(form: OnvifForm): OnvifFormError[] {
  const errors: OnvifFormError[] = []

  const host = form.host.trim()
  if (host === "") {
    errors.push({ field: "host", message: "请填写设备地址" })
  } else if (host.length > ONVIF_HOST_MAX) {
    errors.push({ field: "host", message: `地址最长 ${ONVIF_HOST_MAX} 个字符` })
  } else if (/[:/@\s]/.test(host)) {
    errors.push({
      field: "host",
      message: "这里只填主机名或 IP，不要带 rtsp:// 前缀、路径、端口或账号密码",
    })
  }

  if (
    !Number.isInteger(form.port) ||
    form.port < ONVIF_PORT_MIN ||
    form.port > ONVIF_PORT_MAX
  ) {
    errors.push({
      field: "port",
      message: `端口需在 ${ONVIF_PORT_MIN}–${ONVIF_PORT_MAX} 之间`,
    })
  }

  if (form.password === "") {
    errors.push({ field: "password", message: "请填写设备密码" })
  }

  if (form.name.trim().length > CAMERA_NAME_MAX) {
    errors.push({ field: "name", message: `名称最长 ${CAMERA_NAME_MAX} 个字符` })
  }
  if (form.location.trim().length > CAMERA_LOCATION_MAX) {
    errors.push({ field: "location", message: `位置最长 ${CAMERA_LOCATION_MAX} 个字符` })
  }
  if (form.storageLabel.trim().length > CAMERA_STORAGE_LABEL_MAX) {
    errors.push({
      field: "storageLabel",
      message: `存储标签最长 ${CAMERA_STORAGE_LABEL_MAX} 个字符`,
    })
  }

  return errors
}

/**
 * Whether the profile selection is something the import endpoint can act on.
 *
 * **Separate from `validateOnvifForm` on purpose.** An untouched empty selection
 * is not a malformed form — it is the encoding of "every profile", a perfectly
 * valid ask. It only becomes a problem at the point where a body is built, and
 * folding it into form validity would let a caller gate the *inspection* step on
 * a rule that has nothing to do with inspecting. Two steps, two validators.
 */
export function validateProfileSelection(
  form: OnvifForm,
): OnvifFormError[] {
  if (form.selectionTouched && form.selectedProfileTokens.length === 0) {
    return [
      {
        field: "profiles",
        message: "已取消全部勾选将导入 0 个码流。请至少选一个，或恢复默认的「全部」。",
      },
    ]
  }
  return []
}

/** Both validators, for the one place that is about to submit. */
export function validateOnvifForImport(form: OnvifForm): OnvifFormError[] {
  return [...validateOnvifForm(form), ...validateProfileSelection(form)]
}

export function buildOnvifProbeInput(form: OnvifForm): OnvifProbeInput {
  return {
    host: form.host.trim(),
    port: form.port,
    username: form.username.trim(),
    password: form.password,
  }
}

/**
 * Build the import body.
 *
 * `profile_tokens` is `null` — not `[]` — unless the operator explicitly
 * touched the selection. That single choice decides whether "import everything"
 * or "import nothing" is sent, and `[]` can reach 422
 * `onvif_no_usable_profiles`.
 */
export function buildOnvifImportInput(
  form: OnvifForm,
  identity: OnvifIdentityView | null,
): OnvifImportInput {
  const body: OnvifImportInput = {
    ...buildOnvifProbeInput(form),
    name: form.name.trim() || null,
    location: form.location.trim() || null,
    storage_label: form.storageLabel.trim() || null,
    profile_tokens: form.selectionTouched ? [...form.selectedProfileTokens] : null,
    discovery_candidate_id: form.discoveryCandidateId,
  }
  const confirm = identity ? confirmationIdFor(identity) : null
  if (confirm) body.confirm_existing_device_id = confirm
  return body
}

/** Only profiles with a usable stream URI can actually be imported. */
export function importableProfiles(
  inspection: OnvifInspectionView | null,
): OnvifProfileView[] {
  return (inspection?.profiles ?? []).filter((p) => p.stream_uri_available)
}

/* -------------------------------------------------------------------------- */
/* Manual form                                                                */
/* -------------------------------------------------------------------------- */

export type ManualCameraForm = {
  name: string
  location: string
  storageLabel: string
  primaryName: string
  primaryUrl: string
  secondaryName: string
  secondaryUrl: string
  /** Explicit opt-in; there is no way to detect a second stream from a URL. */
  hasSecondary: boolean
}

export type ManualFormField =
  | "name"
  | "primaryName"
  | "primaryUrl"
  | "secondaryName"
  | "secondaryUrl"

export function emptyManualCameraForm(): ManualCameraForm {
  return {
    name: "",
    location: "",
    storageLabel: "",
    primaryName: "主码流",
    primaryUrl: "",
    secondaryName: "子码流",
    secondaryUrl: "",
    hasSecondary: false,
  }
}

/**
 * Only the scheme, host and presence are checkable here.
 *
 * The server checks exactly this much (`cameras/service.py:104,112`): an
 * unparseable URL, a scheme that is not `rtsp`, or no host. Whether the stream
 * actually plays is what `POST /cameras/test` is for, and a form that claimed to
 * validate reachability would be lying.
 */
export function validateManualCameraForm(
  form: ManualCameraForm,
): ManualFormError[] {
  const errors: ManualFormError[] = []

  const name = form.name.trim()
  if (name === "") errors.push({ field: "name", message: "请填写机位名称" })
  else if (name.length > CAMERA_NAME_MAX) {
    errors.push({ field: "name", message: `名称最长 ${CAMERA_NAME_MAX} 个字符` })
  }

  if (form.primaryName.trim() === "") {
    errors.push({ field: "primaryName", message: "请填写主码流名称" })
  }
  if (!isRtspUrl(form.primaryUrl)) {
    errors.push({
      field: "primaryUrl",
      message: "主码流地址必须是 rtsp:// 开头且带主机名的完整 URL",
    })
  }

  if (form.hasSecondary) {
    if (form.secondaryName.trim() === "") {
      errors.push({ field: "secondaryName", message: "请填写子码流名称" })
    }
    if (!isRtspUrl(form.secondaryUrl)) {
      errors.push({
        field: "secondaryUrl",
        message: "子码流地址必须是 rtsp:// 开头且带主机名的完整 URL",
      })
    }
  }

  return errors
}

export type ManualFormError = { field: ManualFormField; message: string }

function isRtspUrl(value: string): boolean {
  const trimmed = value.trim()
  if (trimmed === "") return false
  let url: URL
  try {
    url = new URL(trimmed)
  } catch {
    return false
  }
  return url.protocol === "rtsp:" && url.hostname !== ""
}

export function buildManualCameraInput(
  form: ManualCameraForm,
): CameraCreateInput {
  const body: CameraCreateInput = {
    name: form.name.trim(),
    location: form.location.trim() || null,
    storage_label: form.storageLabel.trim() || null,
    primary_stream: {
      name: form.primaryName.trim(),
      rtsp_url: form.primaryUrl.trim(),
    },
  }
  if (form.hasSecondary) {
    body.secondary_stream = {
      name: form.secondaryName.trim(),
      rtsp_url: form.secondaryUrl.trim(),
    }
  }
  return body
}

/* -------------------------------------------------------------------------- */
/* Presentation                                                               */
/* -------------------------------------------------------------------------- */

/** The server-side timeouts, for setting a client-side budget. */
export const ONVIF_TIMEOUT_BUDGET_MS = {
  discovery: 3_000,
  inspection: 10_000,
  probePerStream: 12_000,
} as const

/**
 * What one import actually costs, worst case.
 *
 * The import re-runs the inspection and then probes every selected profile, so
 * a client-side timeout has to clear the sum or it will abort a call the server
 * is still legitimately working on. `profileCount` of 0 still pays for the
 * inspection.
 */
export function importBudgetMs(profileCount: number): number {
  return (
    ONVIF_TIMEOUT_BUDGET_MS.inspection +
    Math.max(0, profileCount) * ONVIF_TIMEOUT_BUDGET_MS.probePerStream
  )
}

export function describeProfile(profile: OnvifProfileView): string {
  const parts: string[] = [profile.codec || "未知编码"]
  if (profile.width && profile.height) parts.push(`${profile.width}×${profile.height}`)
  if (profile.fps) parts.push(`${profile.fps}fps`)
  if (profile.bitrate_kbps) parts.push(`${profile.bitrate_kbps}kbps`)
  if (profile.has_audio) parts.push("含音频")
  return parts.join(" · ")
}

/**
 * What a probe result can honestly claim.
 *
 * `ready` on a track is the only success signal, and a null track means the role
 * was not resolved at all — not that it failed. The distinction matters because
 * a camera with no audio track would otherwise read as broken.
 */
export function describeProbeStream(stream: CameraProbeStreamView): string {
  const role = stream.role === "primary" ? "主码流" : "子码流"
  if (!stream.video) return `${role}：未解析到视频轨`
  const video = stream.video
  if (!video.ready) return `${role}：${video.codec ?? "未知编码"} 尚未就绪`
  const parts = [video.codec ?? "未知编码"]
  if (video.width && video.height) parts.push(`${video.width}×${video.height}`)
  if (video.fps) parts.push(`${video.fps}fps`)
  return `${role}：${parts.join(" · ")}${stream.audio ? " · 含音频" : " · 无音频"}`
}
