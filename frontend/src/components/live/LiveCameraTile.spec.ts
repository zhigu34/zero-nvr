import {
  flushPromises,
  mount
} from "@vue/test-utils"
import {
  nextTick
} from "vue"
import {
  beforeEach,
  describe,
  expect,
  it,
  vi
} from "vitest"

import type {
  CameraSummary
} from "../../api/cameras"
import type {
  CameraLiveStream
} from "../../api/live"
import LiveCameraTile from "./LiveCameraTile.vue"

const liveMocks = vi.hoisted(() => ({
  getCameraLiveStream: vi.fn(),
  getCameraCompatibleLiveStream: vi.fn(),
  revokeCameraMediaSession: vi.fn(
    () => Promise.resolve()
  )
}))

vi.mock("vue-i18n", () => ({
  useI18n: () => ({
    t: (key: string) => key
  })
}))

vi.mock("../../api/cameras", () => ({
  getCamera: vi.fn(() => Promise.resolve({
    id: "11111111-1111-1111-1111-111111111111",
    name: "Front Door",
    enabled: true,
    maintenance: false,
    retired_at: null,
    location: "Entrance",
    storage_label: null,
    adapter_type: "manual_rtsp",
    time_sync_mode: "monitor",
    ptz_capable: false,
    streams: [
      {
        id: "22222222-2222-2222-2222-222222222222",
        name: "Sub",
        adapter_profile_key: "manual-secondary",
        codec: "h264",
        width: 640,
        height: 360,
        fps: 15,
        bitrate_kbps: 512,
        gop_seconds: null,
        audio_codec: null,
        has_audio: false,
        status: "available",
        last_verified_at: null
      }
    ],
    bindings: []
  })),
  moveCameraPtz: vi.fn(() => Promise.resolve()),
  stopCameraPtz: vi.fn(() => Promise.resolve())
}))

vi.mock("../../stores/auth", () => ({
  useAuthStore: () => ({
    hasPermission: () => false
  })
}))

vi.mock("../../api/live", () => ({
  cameraSnapshotUrl: () => "/snapshot",
  createCameraWhepSession: vi.fn(),
  deleteCameraWhepSession: vi.fn(
    () => Promise.resolve()
  ),
  getCameraCompatibleLiveStream:
    liveMocks.getCameraCompatibleLiveStream,
  getCameraLiveDiagnostics: vi.fn(),
  getCameraLiveStream:
    liveMocks.getCameraLiveStream,
  keepCameraCompatibilityLease: vi.fn(
    () => Promise.resolve()
  ),
  keepCameraMediaSessionAlive: vi.fn(
    () => Promise.resolve({
      expires_at: "2026-09-26T00:30:00Z"
    })
  ),
  releaseCameraCompatibilityLease: vi.fn(
    () => Promise.resolve()
  ),
  revokeCameraMediaSession:
    liveMocks.revokeCameraMediaSession
}))

const camera: CameraSummary = {
  id: "11111111-1111-1111-1111-111111111111",
  name: "Front Door",
  enabled: true,
  maintenance: false,
  retired_at: null,
  location: "Entrance",
  storage_label: null,
  adapter_type: "manual_rtsp",
  time_sync_mode: "monitor",
  ptz_capable: false
}

const descriptor: CameraLiveStream = {
  camera_id: camera.id,
  profile_id: "22222222-2222-2222-2222-222222222222",
  source_role: "sub",
  profile_name: "Sub",
  adapter_profile_key: "manual-secondary",
  purpose: "LIVE_LOW",
  transport: "hls",
  transports: ["hls"],
  hls_url: "/zlm/zero-nvr/profile-test/hls.m3u8",
  media_session_id:
    "33333333-3333-3333-3333-333333333333",
  expires_at: "2026-09-26T00:30:00Z",
  source_codec: "h264",
  codec: "h264",
  width: 640,
  height: 360,
  fps: 15,
  has_audio: false,
  ice_servers: [],
  ice_error: null
}

describe("LiveCameraTile", () => {
  beforeEach(() => {
    vi.clearAllMocks()
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
      "load",
      {
        configurable: true,
        value: vi.fn()
      }
    )
  })

  it("revokes a stale descriptor returned after playback stops", async () => {
    let resolveDescriptor!:
      (value: CameraLiveStream) => void
    const pendingDescriptor = new Promise<CameraLiveStream>(
      (resolve) => {
        resolveDescriptor = resolve
      }
    )
    liveMocks.getCameraLiveStream.mockReturnValueOnce(
      pendingDescriptor
    )

    const wrapper = mount(LiveCameraTile, {
      props: {
        camera,
        quality: "low",
        playbackEnabled: true
      },
      global: {
        stubs: {
          UiIcon: true
        }
      }
    })

    await nextTick()
    expect(
      liveMocks.getCameraLiveStream
    ).toHaveBeenCalledTimes(1)

    await wrapper.setProps({
      playbackEnabled: false
    })
    await nextTick()

    resolveDescriptor(descriptor)
    await flushPromises()

    expect(
      liveMocks.revokeCameraMediaSession
    ).toHaveBeenCalledWith(
      camera.id,
      descriptor.media_session_id
    )
    expect(
      liveMocks.getCameraCompatibleLiveStream
    ).not.toHaveBeenCalled()
    expect(
      wrapper.find(".live-status-dot").classes()
    ).not.toContain("live-status-dot--active")

    wrapper.unmount()
  })

  it("advances AUTO from failed substream compatibility to mainstream", async () => {
    const subDescriptor: CameraLiveStream = {
      ...descriptor,
      source_codec: "h265",
      codec: "h265",
      transports: [],
      media_session_id:
        "44444444-4444-4444-4444-444444444444"
    }
    const mainDescriptor: CameraLiveStream = {
      ...subDescriptor,
      profile_id:
        "55555555-5555-5555-5555-555555555555",
      source_role: "main",
      profile_name: "Main",
      adapter_profile_key: "manual-primary",
      purpose: "LIVE_HIGH",
      media_session_id:
        "66666666-6666-6666-6666-666666666666"
    }

    liveMocks.getCameraLiveStream
      .mockResolvedValueOnce(subDescriptor)
      .mockResolvedValueOnce(mainDescriptor)
    liveMocks.getCameraCompatibleLiveStream
      .mockRejectedValueOnce(
        new Error("sub compatibility failed")
      )
      .mockRejectedValueOnce(
        new Error("main compatibility failed")
      )

    const wrapper = mount(LiveCameraTile, {
      props: {
        camera,
        quality: "low",
        playbackEnabled: true
      },
      global: {
        stubs: {
          UiIcon: true
        }
      }
    })

    await flushPromises()

    expect(
      liveMocks.getCameraLiveStream
    ).toHaveBeenNthCalledWith(
      1,
      camera.id,
      "low",
      "auto",
      null
    )
    expect(
      liveMocks.getCameraLiveStream
    ).toHaveBeenNthCalledWith(
      2,
      camera.id,
      "low",
      "main",
      null
    )
    expect(
      liveMocks.getCameraCompatibleLiveStream
    ).toHaveBeenNthCalledWith(
      1,
      camera.id,
      "low",
      subDescriptor.media_session_id
    )
    expect(
      liveMocks.getCameraCompatibleLiveStream
    ).toHaveBeenNthCalledWith(
      2,
      camera.id,
      "low",
      mainDescriptor.media_session_id
    )
    expect(
      liveMocks.revokeCameraMediaSession
    ).toHaveBeenCalledWith(
      camera.id,
      subDescriptor.media_session_id
    )

    wrapper.unmount()
  })

  it("does not advance a manually selected substream to mainstream", async () => {
    const subDescriptor: CameraLiveStream = {
      ...descriptor,
      source_codec: "h265",
      codec: "h265",
      transports: [],
      media_session_id:
        "77777777-7777-7777-7777-777777777777"
    }
    liveMocks.getCameraLiveStream.mockResolvedValueOnce(
      subDescriptor
    )
    liveMocks.getCameraCompatibleLiveStream.mockRejectedValueOnce(
      new Error("sub compatibility failed")
    )

    const wrapper = mount(LiveCameraTile, {
      props: {
        camera,
        quality: "low",
        playbackEnabled: false
      },
      global: {
        stubs: {
          UiIcon: true
        }
      }
    })

    await flushPromises()
    await wrapper.find(".live-source-select").setValue("sub")
    await wrapper.setProps({ playbackEnabled: true })
    await flushPromises()

    expect(
      liveMocks.getCameraLiveStream
    ).toHaveBeenCalledTimes(1)
    expect(
      liveMocks.getCameraLiveStream
    ).toHaveBeenCalledWith(
      camera.id,
      "low",
      "sub",
      null
    )
    expect(
      liveMocks.getCameraCompatibleLiveStream
    ).toHaveBeenCalledTimes(1)

    wrapper.unmount()
  })
})
