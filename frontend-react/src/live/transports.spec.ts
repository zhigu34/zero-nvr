import { describe, expect, it } from "vitest"

import type { CameraLiveStreamView } from "../api/live"
import {
  FIRST_FRAME_TIMEOUT_MS,
  RECONNECT_DELAYS_MS,
  describeFirstFrameFailure,
  needsFastPreview,
  normalizedCodec,
  reconnectDelayMs,
  resolveLivePlaybackTransports,
  type LivePlaybackCapabilities,
} from "./transports"

/**
 * These lock the transport ordering rules from spec 0020. The ordering is not
 * cosmetic: preferring WebRTC for a 16-tile grid means paying WHEP/ICE setup
 * sixteen times, and preferring H.265 because the browser says it can decode
 * it produces a silent black tile.
 */

const capabilities: LivePlaybackCapabilities = {
  webrtc: true,
  webrtcH264: true,
  hls: true,
  hlsH264: true,
}

function stream(
  purpose: CameraLiveStreamView["purpose"],
  codec: string,
): CameraLiveStreamView {
  return {
    camera_id: "11111111-1111-1111-1111-111111111111",
    profile_id: "22222222-2222-2222-2222-222222222222",
    source_role: purpose === "LIVE_LOW" ? "sub" : "main",
    profile_name: purpose === "LIVE_LOW" ? "Sub" : "Main",
    adapter_profile_key: "manual",
    purpose,
    transport: "hls",
    transports: ["webrtc", "hls"],
    hls_url: "/zlm/zero-nvr/profile-test/hls.m3u8",
    media_session_id: "33333333-3333-3333-3333-333333333333",
    expires_at: "2026-09-26T00:30:00Z",
    source_codec: codec,
    codec,
    width: 640,
    height: 360,
    fps: 15,
    has_audio: false,
    ice_servers: [],
    ice_error: null,
    compatibility: null,
    compatibility_lease_id: null,
    compatibility_acceleration: null,
  }
}

describe("normalizedCodec", () => {
  it("recognises the spelling variants each layer produces", () => {
    expect(normalizedCodec("h264")).toBe("h264")
    expect(normalizedCodec("avc1.42E01E")).toBe("h264")
    expect(normalizedCodec("H.265")).toBe("h265")
    expect(normalizedCodec("hevc")).toBe("h265")
    expect(normalizedCodec("hvc1.1.6.L93.B0")).toBe("h265")
    expect(normalizedCodec(null)).toBe("unknown")
    expect(normalizedCodec("vp9")).toBe("unknown")
  })
})

describe("resolveLivePlaybackTransports", () => {
  it("prefers HLS for grid playback to avoid per-tile ICE setup", () => {
    expect(
      resolveLivePlaybackTransports(stream("LIVE_LOW", "h264"), capabilities),
    ).toEqual(["hls", "webrtc"])
  })

  it("keeps WebRTC first for a large single tile", () => {
    expect(
      resolveLivePlaybackTransports(stream("LIVE_HIGH", "h264"), capabilities),
    ).toEqual(["webrtc", "hls"])
  })

  it("uses WebRTC-first ordering for an explicit profile", () => {
    expect(
      resolveLivePlaybackTransports(
        { ...stream("LIVE_LOW", "h264"), source_role: "profile" },
        capabilities,
      ),
    ).toEqual(["webrtc", "hls"])
  })

  it("refuses H.265 outright", () => {
    expect(
      resolveLivePlaybackTransports(stream("LIVE_LOW", "h265"), capabilities),
    ).toEqual([])
  })

  it("refuses H.265 even when the browser advertises support", () => {
    // Capability advertisement is not evidence that the ZLM-to-browser path
    // is interoperable, and the failure is a silent black tile.
    expect(
      resolveLivePlaybackTransports(stream("LIVE_HIGH", "h265"), capabilities),
    ).toEqual([])
  })

  it("never offers a transport the backend did not advertise", () => {
    const hlsOnly = { ...stream("LIVE_HIGH", "h264"), transports: ["hls" as const] }
    expect(resolveLivePlaybackTransports(hlsOnly, capabilities)).toEqual(["hls"])
  })

  it("drops WebRTC when the browser cannot decode H.264 for it", () => {
    const noRtcH264: LivePlaybackCapabilities = {
      ...capabilities,
      webrtcH264: false,
    }
    expect(
      resolveLivePlaybackTransports(stream("LIVE_HIGH", "h264"), noRtcH264),
    ).toEqual(["hls"])
  })

  it("returns nothing when no transport survives the intersection", () => {
    const nothing: LivePlaybackCapabilities = {
      webrtc: false,
      webrtcH264: false,
      hls: false,
      hlsH264: false,
    }
    expect(
      resolveLivePlaybackTransports(stream("LIVE_HIGH", "h264"), nothing),
    ).toEqual([])
  })
})

describe("needsFastPreview", () => {
  it("is true only for a source with no direct playback path", () => {
    expect(needsFastPreview(stream("LIVE_LOW", "h265"), capabilities)).toBe(true)
    expect(needsFastPreview(stream("LIVE_LOW", "h264"), capabilities)).toBe(false)
  })

  it("is false for a source that is already a compatibility transcode", () => {
    // Showing a placeholder here would hide working video.
    expect(
      needsFastPreview(
        { ...stream("LIVE_LOW", "h265"), compatibility: "h264_transcode" },
        capabilities,
      ),
    ).toBe(false)
  })
})

describe("reconnectDelayMs", () => {
  it("grows through the ladder and then holds at the cap", () => {
    expect(reconnectDelayMs(0)).toBe(1_000)
    expect(reconnectDelayMs(1)).toBe(2_000)
    expect(reconnectDelayMs(2)).toBe(4_000)
    expect(reconnectDelayMs(3)).toBe(8_000)
    expect(reconnectDelayMs(4)).toBe(15_000)
    // Bounded on purpose: recovery stays automatic, but the loop stops
    // hammering a camera that is genuinely off.
    expect(reconnectDelayMs(5)).toBe(15_000)
    expect(reconnectDelayMs(99)).toBe(RECONNECT_DELAYS_MS.at(-1))
  })

  it("falls back to the first step for a nonsense attempt count", () => {
    expect(reconnectDelayMs(-1)).toBe(1_000)
    expect(reconnectDelayMs(Number.NaN)).toBe(1_000)
  })
})

describe("describeFirstFrameFailure", () => {
  it("always yields an actionable message", () => {
    // A failure with no stated reason is a black box; the project rule is that
    // the reason and a retry must both be reachable.
    for (const failure of ["timeout", "media_error", "cancelled"] as const) {
      const message = describeFirstFrameFailure(failure, {
        hasVideo: true,
        hasAudio: false,
      })
      expect(message.length).toBeGreaterThan(0)
      expect(message).not.toMatch(/undefined|NaN/)
    }
  })

  it("distinguishes a silent camera from a decoder problem", () => {
    const timeout = describeFirstFrameFailure("timeout", {
      hasVideo: true,
      hasAudio: false,
    })
    const media = describeFirstFrameFailure("media_error", {
      hasVideo: true,
      hasAudio: false,
    })
    expect(timeout).not.toBe(media)
    expect(media).toContain("解码")
  })

  it("leaves room for a transcode lease before declaring failure", () => {
    expect(FIRST_FRAME_TIMEOUT_MS).toBeLessThan(8_000)
  })
})
