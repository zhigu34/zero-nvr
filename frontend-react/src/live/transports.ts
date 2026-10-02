/**
 * Transport selection for a live tile.
 *
 * The backend hands back a descriptor that may advertise more transports than
 * this build can actually use, and the browser advertises codecs it can decode
 * but not necessarily decode *from a ZLM-served stream*. So the usable set is
 * the intersection, ordered by cost rather than by the order the backend
 * happened to list.
 *
 * Cost model, from spec 0020: a grid of tiles should prefer HLS over WebRTC,
 * because WebRTC pays WHEP/ICE setup per tile and that setup dominates for
 * small substream panes. A single large tile prefers WebRTC for latency.
 * `source_role` is the proxy for "small tile" because that is what the backend
 * already decided when it picked the profile.
 */
import type { CameraLiveStreamView } from "../api/live"

export type LiveTransport = "webrtc" | "hls"

export interface LivePlaybackCapabilities {
  webrtc: boolean
  webrtcH264: boolean
  hls: boolean
  hlsH264: boolean
}

/**
 * Browser codec names are not consistent: the descriptor may say `h265`,
 * `hevc`, `hvc1.1.6.L93.B0` or `avc1.42E01E` depending on which layer wrote
 * it, and ONVIF devices in particular report it punctuated as `H.265`. Strip
 * separators before matching — an unrecognised codec falls through to the
 * optimistic branch below and gets played anyway, which for H.265 means a
 * silent black tile rather than an error.
 */
export function normalizedCodec(
  codec: string | null | undefined,
): "h264" | "h265" | "unknown" {
  const value = (codec ?? "").toLowerCase().replace(/[\s._-]/g, "")
  if (value.includes("h264") || value.includes("avc")) return "h264"
  if (
    value.includes("h265") ||
    value.includes("hevc") ||
    value.includes("hvc1") ||
    value.includes("hev1")
  ) {
    return "h265"
  }
  return "unknown"
}

/**
 * Ordered list of transports worth trying, best first. An empty list means the
 * tile must fall back to a compatibility transcode or to the JPEG preview
 * wall — never to "try HLS and hope".
 */
export function resolveLivePlaybackTransports(
  stream: Pick<
    CameraLiveStreamView,
    "transports" | "codec" | "source_role"
  >,
  capabilities: LivePlaybackCapabilities,
): LiveTransport[] {
  // H.265 is excluded unconditionally. The browser reporting a decode
  // capability is not evidence that the ZLM-to-browser path is interoperable,
  // and the failure mode is a silent black tile rather than an error. Anything
  // on H.265 goes to the bounded H.264 compatibility derivative instead.
  if (normalizedCodec(stream.codec) === "h265") return []

  const available = new Set(stream.transports)
  const codec = normalizedCodec(stream.codec)
  // An unknown codec is optimistically allowed through; the media element's
  // own error handling is the backstop for that case.
  const rtcCompatible =
    capabilities.webrtc &&
    (codec === "unknown" || (codec === "h264" && capabilities.webrtcH264))
  const hlsCompatible =
    capabilities.hls &&
    (codec === "unknown" || (codec === "h264" && capabilities.hlsH264))

  const ordered: LiveTransport[] =
    stream.source_role === "sub" ? ["hls", "webrtc"] : ["webrtc", "hls"]

  const result: LiveTransport[] = []
  for (const transport of ordered) {
    if (!available.has(transport)) continue
    if (transport === "webrtc" && rtcCompatible) result.push(transport)
    if (transport === "hls" && hlsCompatible) result.push(transport)
  }
  return result
}

/**
 * True when this source has no direct playback path at all, so the tile must
 * show the shared JPEG preview wall while a transcode is negotiated. A source
 * that is *already* a compatibility transcode does not need one — showing a
 * preview for it would hide working video.
 */
export function needsFastPreview(
  stream: Pick<CameraLiveStreamView, "transports" | "codec" | "source_role" | "compatibility">,
  capabilities: LivePlaybackCapabilities,
): boolean {
  return (
    stream.compatibility !== "h264_transcode" &&
    normalizedCodec(stream.codec) === "h265" &&
    resolveLivePlaybackTransports(stream, capabilities).length === 0
  )
}

/* -------------------------------------------------------------------------- */
/* Reconnect backoff                                                          */
/* -------------------------------------------------------------------------- */

/** Grows to the cap and stays there; a camera that is genuinely down never recovers. */
export const RECONNECT_DELAYS_MS = [1_000, 2_000, 4_000, 8_000, 15_000] as const

/**
 * Delay before reconnect attempt `attempt` (0-based). Bounded on purpose: a
 * tile that is off because the camera is off should stop retrying at 15s
 * intervals rather than spin, but must keep trying — recovery is automatic
 * when the camera comes back.
 */
export function reconnectDelayMs(attempt: number): number {
  if (!Number.isFinite(attempt) || attempt < 0) {
    return RECONNECT_DELAYS_MS[0]
  }
  const index = Math.min(
    Math.floor(attempt),
    RECONNECT_DELAYS_MS.length - 1,
  )
  return RECONNECT_DELAYS_MS[index]
}

/* -------------------------------------------------------------------------- */
/* First-frame gates                                                          */
/* -------------------------------------------------------------------------- */

/** A healthy stream paints a frame well inside this; past it, show the reason. */
export const FIRST_FRAME_TIMEOUT_MS = 6_000

/**
 * Second, longer budget used when the stream still has to negotiate a
 * compatibility transcode lease before the first frame can exist.
 */
export const FIRST_FRAME_TIMEOUT_WITH_TRANSCODE_MS = 8_000

export type FirstFrameFailure =
  | "timeout"
  | "media_error"
  | "cancelled"

/**
 * Turns a "first frame" failure into something an operator can act on, rather
 * than a generic black tile. The project rule is that a failure must state a
 * reason and offer a retry — a silent black box is not an acceptable state.
 */
export function describeFirstFrameFailure(
  failure: FirstFrameFailure,
  context: { hasVideo: boolean; hasAudio: boolean },
): string {
  switch (failure) {
    case "timeout":
      return context.hasVideo
        ? "已连接但未收到视频画面，请检查码流是否正常输出"
        : "已连接但没有收到任何画面"
    case "media_error":
      return "媒体解码失败，浏览器可能不支持该编码"
    case "cancelled":
      return "播放已取消"
  }
}
