/**
 * Live read contract. Mirrors `backend/app/modules/cameras/schemas.py:362-436`.
 *
 * The media path is `Camera -> ZLMediaKit -> browser`. The browser never sees
 * a camera credential: `hls_url` is a **same-origin relative path** under
 * `/zlm/...` carrying a short-lived HMAC signature, which is what lets it go
 * straight into `<video src>` or hls.js with nothing appended.
 *
 * Two contract facts that are easy to lose:
 *
 * 1. `transports` advertises WebRTC, but the response carries **no** WebRTC
 *    URL. The WHEP endpoint is an SDP offer/answer exchange, so a browser
 *    cannot pick that path from this payload alone.
 * 2. Keeping a session alive does **not** re-sign `hls_url`. The signature
 *    lives 30 minutes; after that the tile needs a fresh `getCameraLiveStream`
 *    call, not another keepalive.
 */
import { api } from "./client"

export type LiveSource = "auto" | "sub" | "main" | "profile"

export type LiveSourceRole = "sub" | "main" | "profile"

export type LivePurpose = "LIVE_HIGH" | "LIVE_LOW" | "RECORD" | "PROFILE"

export type LiveTransport = "webrtc" | "hls"

export type IceServerView = {
  urls: string[]
  username: string | null
  credential: string | null
}

export type CameraLiveStreamView = {
  camera_id: string
  profile_id: string
  source_role: LiveSourceRole
  profile_name: string
  adapter_profile_key: string
  purpose: LivePurpose
  /** Legacy field, constant `"hls"`. */
  transport: "hls"
  transports: LiveTransport[]
  /** Same-origin relative path, e.g. `/zlm/zero-nvr/live/hls.m3u8?...`. */
  hls_url: string
  media_session_id: string
  expires_at: string
  source_codec: string | null
  codec: string | null
  width: number | null
  height: number | null
  /** Float, not an integer frame count. */
  fps: number | null
  has_audio: boolean
  ice_servers: IceServerView[]
  ice_error: string | null
  compatibility: "h264_transcode" | null
  compatibility_lease_id: string | null
  compatibility_acceleration: "cpu" | "nvenc" | "vaapi" | null
}

export type CameraLiveSessionKeepaliveView = {
  expires_at: string
}

export type CameraLiveDiagnosticView = {
  status: string
  detail: string | null
}

export type CameraPtzActionView = {
  ok: true
}

export function getCameraLiveStream(
  cameraId: string,
  params: { source?: LiveSource; profileId?: string } = {},
  signal?: AbortSignal,
) {
  const qs = new URLSearchParams()
  if (params.source) qs.set("source", params.source)
  if (params.profileId) qs.set("profile_id", params.profileId)
  const suffix = qs.toString() ? `?${qs}` : ""
  // `quality` is deliberately not sent: the backend declares the parameter and
  // then ignores it (`cameras/api.py:2802` vs `_select_live_stream`). Sending
  // it would advertise a control the server does not honour.
  return api.get<CameraLiveStreamView>(
    `/cameras/${cameraId}/live${suffix}`,
    signal,
  )
}

export function keepaliveLiveSession(
  cameraId: string,
  mediaSessionId: string,
  signal?: AbortSignal,
) {
  return api.post<CameraLiveSessionKeepaliveView>(
    `/cameras/${cameraId}/live/session/${mediaSessionId}/keepalive`,
    undefined,
    signal,
  )
}

export function releaseLiveSession(
  cameraId: string,
  mediaSessionId: string,
) {
  return api.del<void>(
    `/cameras/${cameraId}/live/session/${mediaSessionId}`,
  )
}

export function getLiveDiagnostics(
  cameraId: string,
  signal?: AbortSignal,
) {
  return api.get<CameraLiveDiagnosticView>(
    `/cameras/${cameraId}/live/diagnostics`,
    signal,
  )
}

/** JPEG snapshot. Requires `camera.view`; 409 when the camera is disabled. */
export function snapshotUrl(cameraId: string): string {
  return `/api/v1/cameras/${cameraId}/snapshot`
}

/* -------------------------------------------------------------------------- */
/* PTZ — note the different permission                                        */
/* -------------------------------------------------------------------------- */

/**
 * PTZ is gated on `camera.control`, not `camera.view`
 * (`cameras/api.py:3773` vs `:2810`). A Viewer can watch a camera and still
 * be refused pan/tilt/zoom, so this control has to be hidden independently of
 * the tile itself.
 */
export type PtzMoveRequest = {
  /** Normalised -1.0..1.0. Not degrees, not 0-100. */
  pan?: number
  tilt?: number
  zoom?: number
}

export function ptzMove(
  cameraId: string,
  body: PtzMoveRequest,
  signal?: AbortSignal,
) {
  return api.post<CameraPtzActionView>(
    `/cameras/${cameraId}/ptz/move`,
    body,
    signal,
  )
}

export function ptzStop(cameraId: string, signal?: AbortSignal) {
  return api.post<CameraPtzActionView>(
    `/cameras/${cameraId}/ptz/stop`,
    undefined,
    signal,
  )
}

/* -------------------------------------------------------------------------- */
/* Preview wall                                                               */
/* -------------------------------------------------------------------------- */

export const PREVIEW_WALL_SOCKET = "/api/v1/live/previews/ws"

/** The wall only accepts these slot counts — note there is no single-tile mode. */
export const PREVIEW_WALL_SLOTS = [4, 9, 16] as const
export type PreviewWallSlots = (typeof PREVIEW_WALL_SLOTS)[number]

/**
 * Frame budget per layout, fixed in the server scheduler and **not exposed by
 * any endpoint** (`live_preview_wall.py:50-54`). Hard-coded here because the
 * UI has to size the tiles correctly on first paint.
 */
export const PREVIEW_WALL_RESOLUTION: Record<
  PreviewWallSlots,
  { width: number; fps: number }
> = {
  4: { width: 640, fps: 5 },
  9: { width: 480, fps: 3 },
  16: { width: 320, fps: 2 },
}

export type PreviewWallSyncMessage = {
  type: "sync"
  version: 1
  layout_slots: PreviewWallSlots
  streams: Array<{
    slot: number
    /** Client-chosen; used to discard frames from a superseded subscription. */
    subscription_id: number
    camera_id: string
    media_session_id: string
  }>
}

export type PreviewWallServerMessage =
  | { type: "synced"; version: number }
  | { type: "ready"; slot: number; subscription_id: number }
  | {
      type: "error"
      slot: number
      subscription_id: number
      code: string
      message: string
    }
  | { type: "fatal"; code: string; message: string }

/**
 * Binary frame layout: `[0x01, slot, u32be subscription_id, ...jpeg]`
 * (`live_preview_wall.py:141-156`).
 */
export const PREVIEW_FRAME_MAGIC = 0x01
export const PREVIEW_FRAME_HEADER_BYTES = 6

export type PreviewFrame = {
  slot: number
  subscriptionId: number
  jpeg: Uint8Array
}

export function parsePreviewFrame(data: ArrayBuffer): PreviewFrame | null {
  if (data.byteLength <= PREVIEW_FRAME_HEADER_BYTES) return null
  const view = new DataView(data)
  if (view.getUint8(0) !== PREVIEW_FRAME_MAGIC) return null
  return {
    slot: view.getUint8(1),
    subscriptionId: view.getUint32(2),
    jpeg: new Uint8Array(data, PREVIEW_FRAME_HEADER_BYTES),
  }
}

/* -------------------------------------------------------------------------- */
/* Presentation                                                               */
/* -------------------------------------------------------------------------- */

export const SOURCE_ROLE_LABEL: Record<LiveSourceRole, string> = {
  sub: "子码流",
  main: "主码流",
  profile: "指定码流",
}

/**
 * The spec is explicit that the UI must show the real media path rather than a
 * generic SD/HD label, so these come from the descriptor's own fields.
 */
export function describeLiveSource(
  stream: CameraLiveStreamView,
): string {
  const parts = [SOURCE_ROLE_LABEL[stream.source_role] ?? stream.source_role]
  if (stream.profile_name) parts.push(stream.profile_name)
  if (stream.width && stream.height) {
    parts.push(`${stream.width}×${stream.height}`)
  }
  if (stream.fps) parts.push(`${stream.fps}fps`)
  if (stream.compatibility === "h264_transcode") {
    const accel = stream.compatibility_acceleration
    parts.push(`兼容转码${accel ? `（${accel}）` : ""}`)
  }
  return parts.join(" · ")
}
