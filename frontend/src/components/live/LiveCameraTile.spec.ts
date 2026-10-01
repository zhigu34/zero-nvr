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
import type {
  LivePreviewWallClient,
  PreviewWallListener
} from "../../live/previewWall"
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
  cameraLivePreviewUrl: (
    cameraId: string,
    mediaSessionId: string,
    width: number,
    fps: number
  ) => `/preview/${cameraId}/${mediaSessionId}/${width}/${fps}`,
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
    liveMocks.revokeCameraMediaSession.mockImplementation(
      () => Promise.resolve()
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
      "load",
      {
        configurable: true,
        value: vi.fn()
      }
    )
    Object.defineProperty(
      HTMLMediaElement.prototype,
      "canPlayType",
      {
        configurable: true,
        value: vi.fn(() => "")
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
    Object.defineProperty(
      HTMLVideoElement.prototype,
      "requestVideoFrameCallback",
      {
        configurable: true,
        value: undefined
      }
    )
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: vi.fn(() => "blob:preview-frame")
    })
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: vi.fn()
    })
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

    let releaseSubSession!: () => void
    const subSessionReleased = new Promise<void>((resolve) => {
      releaseSubSession = resolve
    })
    liveMocks.revokeCameraMediaSession
      .mockImplementationOnce(() => subSessionReleased)

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
        quality: "high",
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
    ).toHaveBeenCalledTimes(1)
    expect(
      liveMocks.revokeCameraMediaSession
    ).toHaveBeenCalledWith(
      camera.id,
      subDescriptor.media_session_id
    )

    releaseSubSession()
    await flushPromises()

    expect(
      liveMocks.getCameraLiveStream
    ).toHaveBeenNthCalledWith(
      1,
      camera.id,
      "high",
      "auto",
      null
    )
    expect(
      liveMocks.getCameraLiveStream
    ).toHaveBeenNthCalledWith(
      2,
      camera.id,
      "high",
      "main",
      null
    )
    expect(
      liveMocks.getCameraCompatibleLiveStream
    ).toHaveBeenNthCalledWith(
      1,
      camera.id,
      "high",
      subDescriptor.media_session_id
    )
    expect(
      liveMocks.getCameraCompatibleLiveStream
    ).toHaveBeenNthCalledWith(
      2,
      camera.id,
      "high",
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
        quality: "high",
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
      "high",
      "sub",
      null
    )
    expect(
      liveMocks.getCameraCompatibleLiveStream
    ).toHaveBeenCalledTimes(1)

    wrapper.unmount()
  })

  it("uses the shared wall without multipart fallback for H265 grid playback", async () => {
    const h265Descriptor: CameraLiveStream = {
      ...descriptor,
      source_codec: "h265",
      codec: "h265",
      transports: []
    }
    liveMocks.getCameraLiveStream.mockResolvedValueOnce(
      h265Descriptor
    )
    liveMocks.getCameraCompatibleLiveStream.mockReturnValueOnce(
      new Promise<CameraLiveStream>(() => undefined)
    )
    let wallListener!: PreviewWallListener
    let resolveFirstFrame!: (ready: boolean) => void
    const registrationClose = vi.fn()
    const firstFrame = new Promise<boolean>((resolve) => {
      resolveFirstFrame = resolve
    })
    const previewWall: LivePreviewWallClient = {
      setLayout: vi.fn(),
      subscribe: vi.fn((_input, listener) => {
        wallListener = listener
        return { firstFrame, close: registrationClose }
      }),
      close: vi.fn()
    }
    vi.mocked(URL.createObjectURL)
      .mockReturnValueOnce("blob:preview-frame-1")
      .mockReturnValueOnce("blob:preview-frame-2")

    const wrapper = mount(LiveCameraTile, {
      props: {
        camera,
        quality: "low",
        playbackEnabled: true,
        previewWall,
        previewSlot: 3
      },
      global: { stubs: { UiIcon: true } }
    })
    await flushPromises()

    expect(previewWall.subscribe).toHaveBeenCalledWith(
      {
        slot: 3,
        cameraId: camera.id,
        mediaSessionId: h265Descriptor.media_session_id
      },
      expect.any(Object)
    )
    expect(wrapper.find(".live-tile__state").exists()).toBe(true)
    expect(wrapper.find(".live-tile__fast-preview").exists()).toBe(false)

    wallListener.onFrame(new Blob(["jpeg"], { type: "image/jpeg" }))
    resolveFirstFrame(true)
    await flushPromises()
    const preview = wrapper.find(".live-tile__fast-preview")
    expect(preview.attributes("src")).toBe("blob:preview-frame-1")
    expect(wrapper.find(".live-tile__state").exists()).toBe(false)
    expect(
      liveMocks.getCameraCompatibleLiveStream
    ).not.toHaveBeenCalled()
    expect(
      wrapper.find(".live-status-dot").classes()
    ).toContain("live-status-dot--active")

    wallListener.onFrame(new Blob(["new-jpeg"], { type: "image/jpeg" }))
    await nextTick()
    expect(
      wrapper.find(".live-tile__fast-preview").attributes("src")
    ).toBe("blob:preview-frame-2")
    expect(URL.revokeObjectURL).toHaveBeenCalledWith(
      "blob:preview-frame-1"
    )

    await wrapper.setProps({ playbackEnabled: false })
    await nextTick()
    expect(registrationClose).toHaveBeenCalledOnce()
    expect(URL.revokeObjectURL).toHaveBeenCalledWith(
      "blob:preview-frame-2"
    )
    expect(
      wrapper.find(".live-tile__fast-preview").exists()
    ).toBe(false)

    wrapper.unmount()
  })

  it("does not start fast preview for directly playable H264", async () => {
    liveMocks.getCameraLiveStream.mockResolvedValueOnce(descriptor)
    Object.defineProperty(
      HTMLMediaElement.prototype,
      "canPlayType",
      {
        configurable: true,
        value: vi.fn(() => "probably")
      }
    )
    Object.defineProperty(
      HTMLVideoElement.prototype,
      "requestVideoFrameCallback",
      {
        configurable: true,
        value: vi.fn(() => 1)
      }
    )

    const wrapper = mount(LiveCameraTile, {
      props: {
        camera,
        quality: "low",
        playbackEnabled: true
      },
      global: { stubs: { UiIcon: true } }
    })
    await flushPromises()

    expect(
      wrapper.find(".live-tile__fast-preview").exists()
    ).toBe(false)
    expect(
      liveMocks.getCameraCompatibleLiveStream
    ).not.toHaveBeenCalled()

    await wrapper.setProps({
      previewWall: {
        setLayout: vi.fn(),
        subscribe: vi.fn(),
        close: vi.fn()
      },
      previewSlot: 1
    })
    await flushPromises()
    expect(liveMocks.getCameraLiveStream).toHaveBeenCalledOnce()

    wrapper.unmount()
  })

  it("offers no manual recording control in the live tile", async () => {
    liveMocks.getCameraLiveStream.mockResolvedValueOnce(descriptor)
    Object.defineProperty(
      HTMLMediaElement.prototype,
      "canPlayType",
      {
        configurable: true,
        value: vi.fn(() => "probably")
      }
    )

    const wrapper = mount(LiveCameraTile, {
      props: {
        camera,
        quality: "low",
        playbackEnabled: true
      },
      global: { stubs: { UiIcon: true } }
    })
    await flushPromises()

    // Recording is plan-driven only: no record button, no REC badge, no error strip
    expect(wrapper.find(".media-button--recording").exists()).toBe(false)
    expect(wrapper.find(".live-recording-badge").exists()).toBe(false)
    expect(wrapper.find(".live-tile__action-error").exists()).toBe(false)
    expect(wrapper.text()).not.toContain("REC")
    expect(wrapper.html()).not.toContain("ManualRecording")

    wrapper.unmount()
  })

  it("unregisters a pending shared preview when the tile unmounts", async () => {
    const h265Descriptor: CameraLiveStream = {
      ...descriptor,
      source_codec: "h265",
      codec: "h265",
      transports: []
    }
    liveMocks.getCameraLiveStream.mockResolvedValueOnce(h265Descriptor)
    const registrationClose = vi.fn()
    const previewWall: LivePreviewWallClient = {
      setLayout: vi.fn(),
      subscribe: vi.fn(() => ({
        firstFrame: new Promise<boolean>(() => undefined),
        close: registrationClose
      })),
      close: vi.fn()
    }
    const wrapper = mount(LiveCameraTile, {
      props: {
        camera,
        quality: "low",
        playbackEnabled: true,
        previewWall,
        previewSlot: 0
      },
      global: { stubs: { UiIcon: true } }
    })
    await flushPromises()

    expect(previewWall.subscribe).toHaveBeenCalledOnce()
    wrapper.unmount()
    expect(registrationClose).toHaveBeenCalledOnce()
  })

  it("rebinds a shared preview when its slot or controller changes", async () => {
    const h265Descriptor: CameraLiveStream = {
      ...descriptor,
      source_codec: "h265",
      codec: "h265",
      transports: []
    }
    liveMocks.getCameraLiveStream.mockResolvedValue(h265Descriptor)
    const firstClose = vi.fn()
    const secondClose = vi.fn()
    const firstWall: LivePreviewWallClient = {
      setLayout: vi.fn(),
      subscribe: vi.fn(() => ({
        firstFrame: new Promise<boolean>(() => undefined),
        close: firstClose
      })),
      close: vi.fn()
    }
    const secondWall: LivePreviewWallClient = {
      setLayout: vi.fn(),
      subscribe: vi.fn(() => ({
        firstFrame: new Promise<boolean>(() => undefined),
        close: secondClose
      })),
      close: vi.fn()
    }
    const wrapper = mount(LiveCameraTile, {
      props: {
        camera,
        quality: "low",
        playbackEnabled: true,
        previewWall: firstWall,
        previewSlot: 0
      },
      global: { stubs: { UiIcon: true } }
    })
    await flushPromises()

    await wrapper.setProps({ previewSlot: 1 })
    await flushPromises()
    expect(firstClose).toHaveBeenCalledOnce()
    expect(firstWall.subscribe).toHaveBeenLastCalledWith(
      expect.objectContaining({ slot: 1 }),
      expect.any(Object)
    )

    await wrapper.setProps({ previewWall: secondWall })
    await flushPromises()
    expect(firstClose).toHaveBeenCalledTimes(2)
    expect(secondWall.subscribe).toHaveBeenCalledWith(
      expect.objectContaining({ slot: 1 }),
      expect.any(Object)
    )

    wrapper.unmount()
    expect(secondClose).toHaveBeenCalledOnce()
  })

  it("upgrades H265 preview when requested quality becomes high", async () => {
    const h265Descriptor: CameraLiveStream = {
      ...descriptor,
      source_codec: "h265",
      codec: "h265",
      transports: []
    }
    const compatible: CameraLiveStream = {
      ...h265Descriptor,
      source_codec: "h265",
      codec: "h264",
      transports: ["hls"],
      compatibility: "h264_transcode",
      compatibility_lease_id:
        "88888888-8888-8888-8888-888888888888"
    }
    liveMocks.getCameraLiveStream
      .mockResolvedValueOnce(h265Descriptor)
      .mockResolvedValueOnce(h265Descriptor)
    liveMocks.getCameraCompatibleLiveStream.mockResolvedValueOnce(
      compatible
    )
    Object.defineProperty(
      HTMLMediaElement.prototype,
      "canPlayType",
      {
        configurable: true,
        value: vi.fn(() => "probably")
      }
    )
    Object.defineProperty(
      HTMLVideoElement.prototype,
      "requestVideoFrameCallback",
      {
        configurable: true,
        value: vi.fn(() => 1)
      }
    )

    const wrapper = mount(LiveCameraTile, {
      props: {
        camera,
        quality: "low",
        playbackEnabled: true
      },
      global: { stubs: { UiIcon: true } }
    })
    await flushPromises()
    await wrapper.find(
      ".live-tile__fast-preview"
    ).trigger("load")
    await flushPromises()

    expect(
      liveMocks.getCameraCompatibleLiveStream
    ).not.toHaveBeenCalled()

    await wrapper.setProps({ quality: "high" })
    await flushPromises()

    expect(
      liveMocks.getCameraLiveStream
    ).toHaveBeenCalledTimes(2)
    expect(
      liveMocks.getCameraCompatibleLiveStream
    ).toHaveBeenCalledWith(
      camera.id,
      "high",
      h265Descriptor.media_session_id
    )

    wrapper.unmount()
  })

  it("replaces fast preview after the compatibility video reaches first frame", async () => {
    const h265Descriptor: CameraLiveStream = {
      ...descriptor,
      source_codec: "h265",
      codec: "h265",
      transports: []
    }
    const compatible: CameraLiveStream = {
      ...h265Descriptor,
      source_codec: "h265",
      codec: "h264",
      transports: ["hls"],
      compatibility: "h264_transcode",
      compatibility_lease_id:
        "99999999-9999-9999-9999-999999999999"
    }
    const frameCallbacks: Array<() => void> = []
    Object.defineProperty(
      HTMLMediaElement.prototype,
      "canPlayType",
      {
        configurable: true,
        value: vi.fn(() => "probably")
      }
    )
    Object.defineProperty(
      HTMLVideoElement.prototype,
      "requestVideoFrameCallback",
      {
        configurable: true,
        value: vi.fn((callback: () => void) => {
          frameCallbacks.push(callback)
          return 1
        })
      }
    )
    Object.defineProperty(
      HTMLVideoElement.prototype,
      "cancelVideoFrameCallback",
      {
        configurable: true,
        value: vi.fn()
      }
    )
    liveMocks.getCameraLiveStream.mockResolvedValueOnce(
      h265Descriptor
    )
    liveMocks.getCameraCompatibleLiveStream.mockResolvedValueOnce(
      compatible
    )

    const wrapper = mount(LiveCameraTile, {
      props: {
        camera,
        quality: "high",
        playbackEnabled: true
      },
      global: { stubs: { UiIcon: true } }
    })
    await flushPromises()
    await nextTick()
    await flushPromises()

    expect(
      wrapper.find(".live-tile__fast-preview").exists()
    ).toBe(true)
    const previewElement = wrapper.find(
      ".live-tile__fast-preview"
    ).element as HTMLImageElement
    expect(
      liveMocks.getCameraCompatibleLiveStream
    ).toHaveBeenCalledTimes(1)
    expect(frameCallbacks).toHaveLength(1)

    frameCallbacks[0]?.()
    await flushPromises()

    expect(
      wrapper.find(".live-tile__fast-preview").exists()
    ).toBe(false)
    expect(previewElement.hasAttribute("src")).toBe(false)

    wrapper.unmount()
  })
})
