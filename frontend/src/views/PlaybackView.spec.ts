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

import PlaybackView from "./PlaybackView.vue"

const anchorIso = "2026-09-28T00:00:00.000Z"
const anchorMs = Date.parse(anchorIso)
const cameraId = "11111111-1111-1111-1111-111111111111"

const apiMocks = vi.hoisted(() => ({
  listCameras: vi.fn(),
  getCameraTimeline: vi.fn(),
  resolveCameraPlayback: vi.fn(),
  resolveRecordingSegment: vi.fn()
}))

vi.mock("vue-router", () => ({
  useRoute: () => ({
    query: {
      camera: cameraId,
      at: anchorIso
    }
  })
}))

vi.mock("vue-i18n", () => ({
  useI18n: () => ({
    locale: { value: "en" },
    t: (key: string) => key,
    te: () => false
  })
}))

vi.mock("../stores/auth", () => ({
  useAuthStore: () => ({
    hasPermission: (permission: string) =>
      permission === "camera.view" ||
      permission === "recording.view"
  })
}))

vi.mock("../api/cameras", () => ({
  listCameras: apiMocks.listCameras
}))

vi.mock("../api/playback", async (importOriginal) => {
  const original = await importOriginal<
    typeof import("../api/playback")
  >()
  return {
    ...original,
    getAlignedCameraTimelines: vi.fn(),
    getCameraTimeline: apiMocks.getCameraTimeline,
    resolveCameraPlayback:
      apiMocks.resolveCameraPlayback,
    resolveRecordingSegment:
      apiMocks.resolveRecordingSegment
  }
})

describe("PlaybackView server-resolved VOD", () => {
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  beforeEach(() => {
    vi.useFakeTimers()
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
    vi.stubGlobal(
      "requestAnimationFrame",
      vi.fn(() => 1)
    )
    vi.stubGlobal("cancelAnimationFrame", vi.fn())

    apiMocks.listCameras.mockResolvedValue([
      {
        id: cameraId,
        name: "Meeting room",
        enabled: true,
        maintenance: false,
        retired_at: null,
        location: "Office",
        storage_label: null,
        adapter_type: "manual_rtsp",
        time_sync_mode: "monitor",
        ptz_capable: false
      }
    ])
    apiMocks.getCameraTimeline.mockResolvedValue({
      camera_id: cameraId,
      detail: "hour",
      range: {
        start_at: "2026-09-27T21:00:00Z",
        end_at: "2026-09-28T03:00:00Z"
      },
      segments: [
        {
          id: "22222222-2222-2222-2222-222222222222",
          playback_ref:
            "22222222-2222-2222-2222-222222222222",
          start_at: anchorIso,
          end_at: "2026-09-28T00:05:00Z",
          availability: "local"
        }
      ],
      recording_ranges: [
        {
          start_at: anchorIso,
          end_at: "2026-09-28T00:05:00Z",
          availability: "local"
        }
      ],
      gaps: [],
      events: []
    })
    const playable = {
      status: "playable",
      segment_id:
        "22222222-2222-2222-2222-222222222222",
      segment_start_at: anchorIso,
      offset_ms: 0,
      transport: "fmp4",
      url: "/zlm/recording.live.mp4",
      expires_at: "2026-09-28T00:05:00Z",
      codec: "h264"
    }
    apiMocks.resolveCameraPlayback.mockResolvedValue(playable)
    apiMocks.resolveRecordingSegment.mockResolvedValue(playable)
  })

  it("does not seek the browser when startup buffering delays the first frame", async () => {
    const wrapper = mount(PlaybackView, {
      global: {
        stubs: {
          PlaybackTimelineCanvas: true,
          TolerantPlaybackTile: true,
          UiIcon: true
        }
      }
    })
    await flushPromises()

    const video = wrapper.get("video")
    let currentTime = 120
    const setCurrentTime = vi.fn((value: number) => {
      currentTime = value
    })
    Object.defineProperties(video.element, {
      currentTime: {
        configurable: true,
        get: () => currentTime,
        set: setCurrentTime
      },
      duration: {
        configurable: true,
        value: Number.POSITIVE_INFINITY
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
        value: {
          length: 1,
          start: () => 120,
          end: () => 180
        }
      }
    })

    await video.trigger("play")
    expect(requestAnimationFrame).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1_500)
    await video.trigger("canplay")
    expect(requestAnimationFrame).not.toHaveBeenCalled()
    await video.trigger("playing")
    expect(requestAnimationFrame).toHaveBeenCalledTimes(1)
    await video.trigger("waiting")
    expect(cancelAnimationFrame).toHaveBeenCalledWith(1)
    await video.trigger("playing")
    expect(requestAnimationFrame).toHaveBeenCalledTimes(2)
    await video.trigger("timeupdate")

    expect(setCurrentTime).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it("seeks a static recording to its offset once after metadata loads", async () => {
    apiMocks.resolveRecordingSegment.mockResolvedValue({
      status: "playable",
      segment_id:
        "22222222-2222-2222-2222-222222222222",
      segment_start_at: anchorIso,
      offset_ms: 15_000,
      transport: "mp4",
      url: "/api/v1/recordings/segment/media",
      expires_at: "2026-09-28T00:05:00Z",
      codec: "h264"
    })
    const wrapper = mount(PlaybackView, {
      global: {
        stubs: {
          PlaybackTimelineCanvas: true,
          TolerantPlaybackTile: true,
          UiIcon: true
        }
      }
    })
    await flushPromises()

    const video = wrapper.get("video")
    let currentTime = 0
    const setCurrentTime = vi.fn((value: number) => {
      currentTime = value
    })
    Object.defineProperties(video.element, {
      currentTime: {
        configurable: true,
        get: () => currentTime,
        set: setCurrentTime
      },
      duration: {
        configurable: true,
        value: 300
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
        value: {
          length: 1,
          start: () => 0,
          end: () => 300
        }
      }
    })

    await video.trigger("loadedmetadata")
    await video.trigger("loadedmetadata")
    await video.trigger("canplay")
    await video.trigger("timeupdate")

    expect(setCurrentTime).toHaveBeenCalledTimes(1)
    expect(setCurrentTime).toHaveBeenCalledWith(15)
    wrapper.unmount()
  })

  it("seeks preloaded MP4 files again when a player slot is reused", async () => {
    vi.useFakeTimers()
    const firstId =
      "22222222-2222-2222-2222-222222222222"
    const secondId =
      "33333333-3333-3333-3333-333333333333"
    const thirdId =
      "44444444-4444-4444-4444-444444444444"
    const iso = (offsetSeconds: number) =>
      new Date(
        anchorMs + offsetSeconds * 1000
      ).toISOString()
    apiMocks.getCameraTimeline.mockResolvedValue({
      camera_id: cameraId,
      detail: "hour",
      range: {
        start_at: iso(-60),
        end_at: iso(900)
      },
      segments: [
        {
          id: firstId,
          playback_ref: firstId,
          start_at: iso(0),
          end_at: iso(300),
          availability: "local"
        },
        {
          id: secondId,
          playback_ref: secondId,
          start_at: iso(290),
          end_at: iso(590),
          availability: "local"
        },
        {
          id: thirdId,
          playback_ref: thirdId,
          start_at: iso(580),
          end_at: iso(880),
          availability: "local"
        }
      ],
      recording_ranges: [
        {
          start_at: iso(0),
          end_at: iso(880),
          availability: "local"
        }
      ],
      gaps: [],
      events: []
    })
    apiMocks.resolveRecordingSegment.mockImplementation(
      (segmentId: string, offsetMs: number) =>
        Promise.resolve({
          status: "playable",
          segment_id: segmentId,
          segment_start_at:
            segmentId === firstId
              ? iso(0)
              : segmentId === secondId
                ? iso(290)
                : iso(580),
          offset_ms: offsetMs,
          transport: "mp4",
          url: `/api/v1/recordings/${segmentId}/media`,
          expires_at: iso(900),
          codec: "h264"
        })
    )
    const wrapper = mount(PlaybackView, {
      global: {
        stubs: {
          PlaybackTimelineCanvas: true,
          TolerantPlaybackTile: true,
          UiIcon: true
        }
      }
    })
    await flushPromises()

    const instrument = (element: Element) => {
      let currentTime = 0
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
          value: 300
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
          value: {
            length: 1,
            start: () => 0,
            end: () => 300
          }
        }
      })
      return setCurrentTime
    }

    const initialVideos = wrapper.findAll("video")
    expect(initialVideos).toHaveLength(2)
    const active = initialVideos[0]
    const firstStandby = initialVideos[1]
    instrument(active.element)
    const firstStandbySeek = instrument(
      firstStandby.element
    )
    await active.trigger("loadedmetadata")
    await firstStandby.trigger("loadedmetadata")
    await firstStandby.trigger("canplay")

    expect(firstStandbySeek).toHaveBeenCalledWith(10)
    await active.trigger("playing")
    await vi.advanceTimersByTimeAsync(300_000)
    await flushPromises()

    const reusedVideos = wrapper.findAll("video")
    expect(reusedVideos).toHaveLength(2)
    const reusedStandby = reusedVideos.find(
      (item) =>
        !item.classes().includes(
          "playback-video--active"
        )
    )
    expect(reusedStandby).toBeDefined()
    const reusedStandbySeek = instrument(
      reusedStandby!.element
    )
    await reusedStandby!.trigger("loadedmetadata")
    await reusedStandby!.trigger("loadedmetadata")
    await reusedStandby!.trigger("canplay")

    expect(reusedStandbySeek).toHaveBeenCalledTimes(1)
    expect(reusedStandbySeek).toHaveBeenCalledWith(10)
    expect(
      apiMocks.resolveRecordingSegment
    ).toHaveBeenCalledTimes(3)
    wrapper.unmount()
  })
})
