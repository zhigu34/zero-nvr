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
})
