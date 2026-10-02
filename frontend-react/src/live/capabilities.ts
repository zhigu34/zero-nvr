/**
 * What this browser can actually decode, as opposed to what it claims.
 *
 * `canPlayType` and `MediaSource.isTypeSupported` are the two checks that
 * matter for HLS, and both are consulted because a browser may support the
 * codec through MSE while reporting nothing for the container, or vice versa.
 *
 * This probes capabilities only. Whether a particular ZLM-served stream is
 * playable is a separate question that browser support cannot answer — see
 * `resolveLivePlaybackTransports`.
 */
import type { LivePlaybackCapabilities } from "./transports"

const H264_MIME_TYPES = [
  'video/mp4; codecs="avc1.42E01E"',
  'video/mp4; codecs="avc1.4D401F"',
]

const NATIVE_HLS_MIME = "application/vnd.apple.mpegurl"

function supportsMediaType(
  video: HTMLVideoElement | null,
  type: string,
): boolean {
  let native = false
  try {
    native = Boolean(video?.canPlayType(type))
  } catch {
    // A detached element can throw here; treat it as unsupported.
    native = false
  }
  const mse =
    typeof MediaSource !== "undefined" &&
    typeof MediaSource.isTypeSupported === "function" &&
    MediaSource.isTypeSupported(type)
  return native || mse
}

function hasNativeHls(video: HTMLVideoElement | null): boolean {
  try {
    return Boolean(video?.canPlayType(NATIVE_HLS_MIME))
  } catch {
    return false
  }
}

export function detectLivePlaybackCapabilities(
  video: HTMLVideoElement | null,
): LivePlaybackCapabilities {
  const webrtc = typeof RTCPeerConnection !== "undefined"
  const hls = hasNativeHls(video) || hlsJsSupported()

  return {
    webrtc,
    webrtcH264: webrtc && rtcCanDecodeH264(),
    hls,
    hlsH264: hls && H264_MIME_TYPES.some((type) => supportsMediaType(video, type)),
  }
}

function rtcCanDecodeH264(): boolean {
  if (
    typeof RTCRtpReceiver === "undefined" ||
    typeof RTCRtpReceiver.getCapabilities !== "function"
  ) {
    // No capability report at all is not evidence against H.264; most engines
    // that expose WebRTC also expose getCapabilities, so this is rare.
    return true
  }
  const codecs = RTCRtpReceiver.getCapabilities("video")?.codecs ?? []
  if (codecs.length === 0) return true
  return codecs.some((codec) => codec.mimeType.toLowerCase() === "video/h264")
}

/**
 * Injected so tests do not need a real hls.js instance. hls.js cannot play
 * through MSE on IE-era engines, which is the main reason this is not a
 * hard-coded `true`.
 */
let hlsJsSupported: () => boolean = () => false

export function setHlsJsSupportProbe(probe: () => boolean): void {
  hlsJsSupported = probe
}
