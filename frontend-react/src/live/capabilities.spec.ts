import { afterEach, describe, expect, it, vi } from "vitest"

import {
  detectLivePlaybackCapabilities,
  setHlsJsSupportProbe,
} from "./capabilities"

function fakeVideo(answers: Record<string, string>): HTMLVideoElement {
  return {
    canPlayType: (type: string) => answers[type] ?? "",
  } as unknown as HTMLVideoElement
}

const H264 = 'video/mp4; codecs="avc1.42E01E"'
const HLS = "application/vnd.apple.mpegurl"

afterEach(() => {
  setHlsJsSupportedFallback()
  vi.unstubAllGlobals()
})

function setHlsJsSupportedFallback() {
  setHlsJsSupportProbe(() => false)
}

describe("detectLivePlaybackCapabilities", () => {
  it("reports HLS available when the element understands the container", () => {
    setHlsJsSupportProbe(() => false)
    const caps = detectLivePlaybackCapabilities(
      fakeVideo({ [HLS]: "maybe", [H264]: "probably" }),
    )

    expect(caps.hls).toBe(true)
    expect(caps.hlsH264).toBe(true)
  })

  it("reports HLS available through MSE alone", () => {
    setHlsJsSupportProbe(() => true)
    vi.stubGlobal("MediaSource", { isTypeSupported: () => true })

    const caps = detectLivePlaybackCapabilities(fakeVideo({}))
    expect(caps.hls).toBe(true)
    expect(caps.hlsH264).toBe(true)
  })

  it("reports nothing when the browser can do neither path", () => {
    setHlsJsSupportProbe(() => false)
    vi.stubGlobal("MediaSource", { isTypeSupported: () => false })

    const caps = detectLivePlaybackCapabilities(fakeVideo({}))
    expect(caps.hls).toBe(false)
    expect(caps.hlsH264).toBe(false)
  })

  it("does not claim H.264 when only the container is understood", () => {
    setHlsJsSupportProbe(() => false)
    vi.stubGlobal("MediaSource", { isTypeSupported: () => false })

    const caps = detectLivePlaybackCapabilities(
      fakeVideo({ [HLS]: "maybe" }),
    )
    expect(caps.hls).toBe(true)
    expect(caps.hlsH264).toBe(false)
  })

  it("tolerates a null element instead of throwing", () => {
    setHlsJsSupportProbe(() => true)
    expect(() => detectLivePlaybackCapabilities(null)).not.toThrow()
  })

  it("treats a throwing canPlayType as unsupported", () => {
    setHlsJsSupportProbe(() => false)
    const hostile = {
      canPlayType: () => {
        throw new Error("detached")
      },
    } as unknown as HTMLMediaElement

    const caps = detectLivePlaybackCapabilities(hostile as HTMLVideoElement)
    expect(caps.hls).toBe(false)
  })

  it("assumes H.264 for WebRTC when the browser reports no codec list", () => {
    setHlsJsSupportProbe(() => true)
    vi.stubGlobal("RTCPeerConnection", class {})
    vi.stubGlobal("RTCRtpReceiver", { getCapabilities: () => ({ codecs: [] }) })

    const caps = detectLivePlaybackCapabilities(fakeVideo({ [HLS]: "maybe" }))
    expect(caps.webrtc).toBe(true)
    expect(caps.webrtcH264).toBe(true)
  })

  it("rejects WebRTC H.264 when the browser lists codecs without it", () => {
    setHlsJsSupportProbe(() => true)
    vi.stubGlobal("RTCPeerConnection", class {})
    vi.stubGlobal("RTCRtpReceiver", {
      getCapabilities: () => ({ codecs: [{ mimeType: "video/VP9" }] }),
    })

    const caps = detectLivePlaybackCapabilities(fakeVideo({ [HLS]: "maybe" }))
    expect(caps.webrtcH264).toBe(false)
  })

  it("reports no WebRTC in an engine without RTCPeerConnection", () => {
    setHlsJsSupportProbe(() => true)
    const caps = detectLivePlaybackCapabilities(fakeVideo({ [HLS]: "maybe" }))
    expect(caps.webrtc).toBe(false)
  })
})
