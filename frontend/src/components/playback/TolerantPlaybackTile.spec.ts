import {
  flushPromises,
  mount
} from "@vue/test-utils"
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi
} from "vitest"

import type {
  PlaybackPlayable
} from "../../api/playback"
import TolerantPlaybackTile from "./TolerantPlaybackTile.vue"

const playbackMocks = vi.hoisted(() => ({
  resolveCameraPlayback: vi.fn()
}))

vi.mock("vue-i18n", () => ({
  useI18n: () => ({
    t: (key: string) => key
  })
}))

vi.mock("../../api/playback", () => ({
  resolveCameraPlayback:
    playbackMocks.resolveCameraPlayback
}))

const anchorMs = Date.parse("2026-09-28T00:00:00Z")
const playable: PlaybackPlayable = {
  status: "playable",
  segment_id: "11111111-1111-1111-1111-111111111111",
  segment_start_at: "2026-09-28T00:00:00Z",
  offset_ms: 0,
  transport: "fmp4",
  url: "/zlm/recording.live.mp4",
  expires_at: "2026-09-28T00:05:00Z",
  codec: "h264"
}

function configureVideo(
  element: HTMLVideoElement,
  initialTime = 120,
  duration = Number.POSITIVE_INFINITY,
  initialSeekableStart: number | null = 120
) {
  let currentTime = initialTime
  let seekableStart = initialSeekableStart
  const setCurrentTime = vi.fn((value: number) => {
    currentTime = value
  })
  Object.defineProperties(element, {
    currentTime: {
      configurable: true,
      get: () => currentTime,
      set: setCurrentTime
    },
    duration: {
      configurable: true,
      value: duration
    },
    paused: {
      configurable: true,
      get: () => false
    },
    readyState: {
      configurable: true,
      get: () => 4
    },
    seekable: {
      configurable: true,
      get: () => ({
        length: seekableStart === null ? 0 : 1,
        start: () => seekableStart ?? 0,
        end: () => duration
      })
    }
  })
  return {
    setCurrentTime,
    setSeekableStart: (value: number | null) => {
      seekableStart = value
    },
    advanceCurrentTime: (seconds: number) => {
      currentTime += seconds
    }
  }
}

async function mountTile(
  masterTimeMs = anchorMs,
  playbackRate = 1,
  initialTime = 120,
  duration = Number.POSITIVE_INFINITY,
  seekableStart: number | null = 120
) {
  const wrapper = mount(TolerantPlaybackTile, {
    props: {
      cameraId: "22222222-2222-2222-2222-222222222222",
      cameraName: "Meeting room",
      masterTimeMs,
      playing: true,
      playbackRate,
      muted: true,
      seekGeneration: 0,
      focused: true
    }
  })
  await flushPromises()
  const video = wrapper.get("video")
  const controls = configureVideo(
    video.element as HTMLVideoElement,
    initialTime,
    duration,
    seekableStart
  )
  return { wrapper, video, ...controls }
}

describe("TolerantPlaybackTile server-resolved VOD", () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  beforeEach(() => {
    vi.clearAllMocks()
    Object.defineProperty(
      HTMLMediaElement.prototype,
      "load",
      {
        configurable: true,
        value: vi.fn()
      }
    )
    Object.defineProperty(
      HTMLMediaElement.prototype,
      "pause",
      {
        configurable: true,
        value: vi.fn()
      }
    )
    Object.defineProperty(
      HTMLMediaElement.prototype,
      "play",
      {
        configurable: true,
        value: vi.fn(() => Promise.resolve())
      }
    )
    playbackMocks.resolveCameraPlayback.mockResolvedValue(
      playable
    )
  })

  it("does not seek the browser when the server-resolved stream becomes playable", async () => {
    const { wrapper, video, setCurrentTime } =
      await mountTile()

    await video.trigger("canplay")

    expect(setCurrentTime).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it("seeks a static recording to its offset once after metadata loads", async () => {
    playbackMocks.resolveCameraPlayback.mockResolvedValue({
      ...playable,
      offset_ms: 15_000,
      transport: "mp4",
      url: "/api/v1/recordings/segment/media"
    })
    const {
      wrapper,
      video,
      setCurrentTime,
      setSeekableStart
    } = await mountTile(
      anchorMs + 15_000,
      1,
      0,
      300,
      null
    )

    await video.trigger("loadedmetadata")
    await video.trigger("loadedmetadata")
    setSeekableStart(0)
    await video.trigger("canplay")
    await video.trigger("playing")
    await video.trigger("timeupdate")

    expect(setCurrentTime).toHaveBeenCalledTimes(1)
    expect(setCurrentTime).toHaveBeenCalledWith(15)
    expect(
      playbackMocks.resolveCameraPlayback
    ).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it("applies a fresh offset when an MP4 source is re-resolved", async () => {
    vi.useFakeTimers()
    playbackMocks.resolveCameraPlayback.mockImplementation(
      (_cameraId: string, at: Date) =>
        Promise.resolve({
          ...playable,
          transport: "mp4",
          url: "/api/v1/recordings/segment/media",
          offset_ms: at.getTime() - anchorMs
        })
    )
    const { wrapper, video } = await mountTile(
      anchorMs,
      1,
      0,
      300,
      0
    )
    await video.trigger("loadedmetadata")
    await video.trigger("canplay")
    await video.trigger("playing")

    await wrapper.setProps({
      masterTimeMs: anchorMs + 6_000
    })
    await video.trigger("timeupdate")
    await flushPromises()

    expect(
      playbackMocks.resolveCameraPlayback
    ).toHaveBeenCalledTimes(2)
    const replacement = wrapper.get("video")
    const replacementControls = configureVideo(
      replacement.element as HTMLVideoElement,
      0,
      300,
      0
    )
    await replacement.trigger("loadedmetadata")
    await replacement.trigger("loadedmetadata")
    await replacement.trigger("canplay")

    expect(
      replacementControls.setCurrentTime
    ).toHaveBeenCalledTimes(1)
    expect(
      replacementControls.setCurrentTime
    ).toHaveBeenCalledWith(6)
    wrapper.unmount()
  })

  it("uses rate correction for startup-sized drift without restarting the stream", async () => {
    const { wrapper, video, setCurrentTime } =
      await mountTile()
    await video.trigger("canplay")
    setCurrentTime.mockClear()

    await wrapper.setProps({
      masterTimeMs: anchorMs + 2_000
    })
    await video.trigger("timeupdate")
    await flushPromises()

    expect(
      playbackMocks.resolveCameraPlayback
    ).toHaveBeenCalledTimes(1)
    expect(
      (video.element as HTMLVideoElement).playbackRate
    ).toBeGreaterThan(1)
    expect(setCurrentTime).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it("re-resolves severe drift through the server instead of hard-seeking the browser", async () => {
    vi.useFakeTimers()
    playbackMocks.resolveCameraPlayback.mockImplementation(
      (_cameraId: string, at: Date) =>
        Promise.resolve({
          ...playable,
          offset_ms: at.getTime() - anchorMs
        })
    )
    const { wrapper, video, setCurrentTime } =
      await mountTile(anchorMs, 0.5)
    await video.trigger("canplay")
    setCurrentTime.mockClear()

    await wrapper.setProps({
      masterTimeMs: anchorMs + 6_000
    })
    await video.trigger("timeupdate")
    await flushPromises()

    expect(
      playbackMocks.resolveCameraPlayback
    ).toHaveBeenCalledTimes(2)
    expect(setCurrentTime).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(20_000)
    const replacement = wrapper.get("video")
    const replacementControls = configureVideo(
      replacement.element as HTMLVideoElement
    )
    await replacement.trigger("canplay")
    await replacement.trigger("playing")
    await wrapper.setProps({
      masterTimeMs: anchorMs + 12_000
    })
    await replacement.trigger("timeupdate")
    await flushPromises()

    await vi.advanceTimersByTimeAsync(20_000)
    replacementControls.advanceCurrentTime(10.8)
    await wrapper.setProps({
      masterTimeMs: anchorMs + 22_000
    })
    await replacement.trigger("timeupdate")
    await flushPromises()

    expect(
      playbackMocks.resolveCameraPlayback
    ).toHaveBeenCalledTimes(2)
    expect(
      (replacement.element as HTMLVideoElement).playbackRate
    ).toBeGreaterThan(0.5)
    expect(
      replacementControls.setCurrentTime
    ).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})
