import { describe, expect, it } from "vitest"

import type { CameraLiveStream } from "../api/live"
import {
  needsFastPreview,
  resolveLivePlaybackTransports,
  type LivePlaybackCapabilities
} from "./playback"

const capabilities: LivePlaybackCapabilities = {
  webrtc: true,
  webrtcH264: true,
  webrtcH265: false,
  hls: true,
  hlsH264: true,
  hlsH265: false
}

function stream(
  purpose: CameraLiveStream["purpose"],
  codec: string
): CameraLiveStream {
  return {
    camera_id: "11111111-1111-1111-1111-111111111111",
    profile_id: "22222222-2222-2222-2222-222222222222",
    source_role: purpose === "LIVE_LOW" ? "sub" : "main",
    profile_name: purpose === "LIVE_LOW" ? "Sub" : "Main",
    adapter_profile_key:
      purpose === "LIVE_LOW"
        ? "manual-secondary"
        : "manual-primary",
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
    ice_error: null
  }
}

describe("resolveLivePlaybackTransports", () => {
  it("prefers HLS for compatible low/grid playback", () => {
    expect(
      resolveLivePlaybackTransports(
        stream("LIVE_LOW", "h264"),
        capabilities
      )
    ).toEqual(["hls", "webrtc"])
  })

  it("keeps WebRTC first for compatible high playback", () => {
    expect(
      resolveLivePlaybackTransports(
        stream("LIVE_HIGH", "h264"),
        capabilities
      )
    ).toEqual(["webrtc", "hls"])
  })

  it("skips native transports for unsupported H265", () => {
    expect(
      resolveLivePlaybackTransports(
        stream("LIVE_LOW", "h265"),
        capabilities
      )
    ).toEqual([])
  })

  it("uses WebRTC-first ordering for an explicit profile", () => {
    expect(
      resolveLivePlaybackTransports(
        {
          ...stream("LIVE_LOW", "h264"),
          source_role: "profile",
          purpose: "PROFILE"
        },
        capabilities
      )
    ).toEqual(["webrtc", "hls"])
  })

  it("routes H265 to compatibility even when the browser advertises it", () => {
    expect(
      resolveLivePlaybackTransports(
        stream("LIVE_HIGH", "h265"),
        {
          ...capabilities,
          webrtcH265: true,
          hlsH265: true
        }
      )
    ).toEqual([])
  })
})

describe("needsFastPreview", () => {
  it("uses a fast placeholder only for a source without direct playback", () => {
    expect(
      needsFastPreview(
        stream("LIVE_LOW", "h265"),
        capabilities
      )
    ).toBe(true)
    expect(
      needsFastPreview(
        stream("LIVE_LOW", "h264"),
        capabilities
      )
    ).toBe(false)
    expect(
      needsFastPreview(
        {
          ...stream("LIVE_LOW", "h264"),
          compatibility: "h264_transcode"
        },
        capabilities
      )
    ).toBe(false)
  })
})
