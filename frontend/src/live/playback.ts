import Hls from "hls.js"

import type {
  CameraLiveStream
} from "../api/live"

export interface LivePlaybackCapabilities {
  webrtc: boolean
  webrtcH264: boolean
  webrtcH265: boolean
  hls: boolean
  hlsH264: boolean
  hlsH265: boolean
}

function supportsMediaType(
  video: HTMLVideoElement | null,
  type: string
): boolean {
  const native = Boolean(
    video?.canPlayType(type)
  )
  const mse = (
    typeof MediaSource !== "undefined" &&
    typeof MediaSource.isTypeSupported === "function" &&
    MediaSource.isTypeSupported(type)
  )
  return native || mse
}

function rtcVideoCodecs(): Set<string> {
  if (
    typeof RTCRtpReceiver === "undefined" ||
    typeof RTCRtpReceiver.getCapabilities !== "function"
  ) {
    return new Set()
  }

  const capabilities = RTCRtpReceiver.getCapabilities(
    "video"
  )
  return new Set(
    (capabilities?.codecs ?? [])
      .map((codec) => codec.mimeType.toLowerCase())
  )
}

export function detectLivePlaybackCapabilities(
  video: HTMLVideoElement | null
): LivePlaybackCapabilities {
  const rtcCodecs = rtcVideoCodecs()
  const webrtc =
    typeof RTCPeerConnection !== "undefined"

  const h264Types = [
    'video/mp4; codecs="avc1.42E01E"',
    'video/mp4; codecs="avc1.4D401F"'
  ]
  const h265Types = [
    'video/mp4; codecs="hvc1.1.6.L93.B0"',
    'video/mp4; codecs="hev1.1.6.L93.B0"'
  ]
  const nativeHls = Boolean(
    video?.canPlayType(
      "application/vnd.apple.mpegurl"
    )
  )
  const hls = nativeHls || Hls.isSupported()

  return {
    webrtc,
    webrtcH264:
      webrtc &&
      (
        rtcCodecs.size === 0 ||
        rtcCodecs.has("video/h264")
      ),
    webrtcH265:
      webrtc &&
      rtcCodecs.has("video/h265"),
    hls,
    hlsH264:
      hls &&
      h264Types.some((type) =>
        supportsMediaType(video, type)
      ),
    hlsH265:
      hls &&
      h265Types.some((type) =>
        supportsMediaType(video, type)
      )
  }
}

function normalizedCodec(
  codec: string | null
): "h264" | "h265" | "unknown" {
  const value = (codec ?? "").toLowerCase()
  if (
    value.includes("h264") ||
    value.includes("avc")
  ) {
    return "h264"
  }
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

export function resolveLivePlaybackTransports(
  stream: CameraLiveStream,
  capabilities: LivePlaybackCapabilities
): Array<"webrtc" | "hls"> {
  const available = new Set(stream.transports)
  const codec = normalizedCodec(stream.codec)
  const result: Array<"webrtc" | "hls"> = []

  const rtcCompatible =
    capabilities.webrtc &&
    (
      codec === "unknown" ||
      (
        codec === "h264" &&
        capabilities.webrtcH264
      ) ||
      (
        codec === "h265" &&
        capabilities.webrtcH265
      )
    )
  const hlsCompatible =
    capabilities.hls &&
    (
      codec === "unknown" ||
      (
        codec === "h264" &&
        capabilities.hlsH264
      ) ||
      (
        codec === "h265" &&
        capabilities.hlsH265
      )
    )

  const ordered: Array<"webrtc" | "hls"> =
    stream.purpose === "LIVE_LOW"
      ? ["hls", "webrtc"]
      : ["webrtc", "hls"]

  for (const transport of ordered) {
    if (
      transport === "webrtc" &&
      available.has("webrtc") &&
      rtcCompatible
    ) {
      result.push("webrtc")
    }
    if (
      transport === "hls" &&
      available.has("hls") &&
      hlsCompatible
    ) {
      result.push("hls")
    }
  }

  return result
}
