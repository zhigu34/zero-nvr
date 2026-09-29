import { flushPromises, mount } from "@vue/test-utils"
import { beforeEach, describe, expect, it, vi } from "vitest"

import CamerasView from "./CamerasView.vue"

const cam1Id = "00000000-0000-0000-0000-000000000001"
const cam2Id = "00000000-0000-0000-0000-000000000002"
const mockRouterPush = vi.fn()

vi.mock("vue-router", () => ({
  useRouter: () => ({
    push: mockRouterPush
  }),
  useRoute: () => ({
    query: {}
  })
}))

vi.mock("vue-i18n", () => ({
  useI18n: () => ({
    t: (key: string) => key,
    te: () => false
  })
}))

vi.mock("../stores/auth", () => ({
  useAuthStore: () => ({
    hasPermission: () => true
  })
}))

const apiMocks = vi.hoisted(() => ({
  listCameras: vi.fn(),
  getCamera: vi.fn(),
  getCameraClock: vi.fn(),
  updateCamera: vi.fn(),
  moveCameraPtz: vi.fn(),
  stopCameraPtz: vi.fn()
}))

vi.mock("../api/cameras", () => ({
  listCameras: apiMocks.listCameras,
  getCamera: apiMocks.getCamera,
  getCameraClock: apiMocks.getCameraClock,
  updateCamera: apiMocks.updateCamera,
  moveCameraPtz: apiMocks.moveCameraPtz,
  stopCameraPtz: apiMocks.stopCameraPtz
}))

describe("CamerasView - Devices & Discovery Center", () => {
  beforeEach(() => {
    vi.clearAllMocks()

    apiMocks.listCameras.mockResolvedValue([
      {
        id: cam1Id,
        name: "Lobby Front Door",
        enabled: true,
        maintenance: false,
        retired_at: null,
        location: "Lobby",
        storage_label: "local-nvme",
        adapter_type: "onvif",
        time_sync_mode: "manage_ntp",
        ptz_capable: true
      },
      {
        id: cam2Id,
        name: "Perimeter East",
        enabled: true,
        maintenance: true,
        retired_at: null,
        location: "Perimeter",
        storage_label: null,
        adapter_type: "manual_rtsp",
        time_sync_mode: "monitor",
        ptz_capable: false
      }
    ])

    apiMocks.getCamera.mockImplementation((id: string) =>
      Promise.resolve({
        id,
        name: id === cam1Id ? "Lobby Front Door" : "Perimeter East",
        enabled: true,
        maintenance: id === cam2Id,
        retired_at: null,
        location: id === cam1Id ? "Lobby" : "Perimeter",
        storage_label: null,
        adapter_type: id === cam1Id ? "onvif" : "manual_rtsp",
        time_sync_mode: id === cam1Id ? "manage_ntp" : "monitor",
        ptz_capable: id === cam1Id,
        streams: [
          {
            id: `str-${id}-0`,
            name: "Main",
            adapter_profile_key: "profile-1",
            codec: "h265",
            width: 3840,
            height: 2160,
            fps: 25,
            bitrate_kbps: 4096,
            gop_seconds: 2,
            audio_codec: "aac",
            has_audio: true,
            status: "available",
            last_verified_at: "2026-09-29T10:00:00Z"
          }
        ],
        bindings: [
          {
            purpose: "RECORD",
            stream_profile_id: `str-${id}-0`,
            selection_mode: "manual"
          }
        ]
      })
    )

    apiMocks.getCameraClock.mockImplementation((id: string) =>
      Promise.resolve({
        camera_id: id,
        device_id: null,
        health: "healthy",
        quality: "good",
        sync_mode: "manage_ntp",
        measured_at: "2026-09-29T10:00:00Z",
        offset_ms: 4,
        uncertainty_ms: 1,
        rtt_ms: 5,
        device_timezone: "UTC",
        device_time_source: "ntp",
        error_code: null
      })
    )

    apiMocks.updateCamera.mockResolvedValue({})
    apiMocks.moveCameraPtz.mockResolvedValue({ ok: true })
    apiMocks.stopCameraPtz.mockResolvedValue({ ok: true })
  })

  it("renders Devices & Discovery header and filter chips", async () => {
    const wrapper = mount(CamerasView, {
      global: {
        stubs: {
          UiIcon: true,
          CameraDetailPanel: true,
          CameraGroupsPanel: true,
          CameraOnboardingPanel: true
        }
      }
    })
    await flushPromises()

    expect(wrapper.find(".devices-title").text()).toContain("Devices & Discovery")
    expect(wrapper.text()).toContain("发现新摄像机")
    expect(wrapper.text()).toContain("CSV 批量导入")
    expect(wrapper.text()).toContain("导出 CSV")

    const chips = wrapper.findAll(".chip-btn")
    expect(chips.length).toBeGreaterThanOrEqual(4)
    expect(chips[0].text()).toContain("全部摄像机 (2)")
    expect(chips[1].text()).toContain("在线正常 (1)")
    expect(chips[2].text()).toContain("维护模式 (1)")
  })

  it("displays cameras table with real streams and clock facts", async () => {
    const wrapper = mount(CamerasView, {
      global: {
        stubs: {
          UiIcon: true,
          CameraDetailPanel: true,
          CameraGroupsPanel: true,
          CameraOnboardingPanel: true
        }
      }
    })
    await flushPromises()

    const rows = wrapper.findAll(".devices-row")
    expect(rows.length).toBe(2)

    // First camera: PTZ capable, 4K H.265
    expect(rows[0].text()).toContain("Lobby Front Door")
    expect(rows[0].text()).toContain("ONVIF")
    expect(rows[0].text()).toContain("4K H.265")
    expect(rows[0].text()).toContain("🕹️ PTZ 摇杆控制")

    // Second camera: Perimeter East, in maintenance
    expect(rows[1].text()).toContain("Perimeter East")
    expect(rows[1].text()).toContain("维护中")
    expect(rows[1].text()).toContain("固定视角")
  })

  it("allows toggling camera maintenance mode", async () => {
    const wrapper = mount(CamerasView, {
      global: {
        stubs: {
          UiIcon: true,
          CameraDetailPanel: true,
          CameraGroupsPanel: true,
          CameraOnboardingPanel: true
        }
      }
    })
    await flushPromises()

    const rows = wrapper.findAll(".devices-row")
    // Click maintenance toggle on camera 1
    const maintBtn = rows[0].findAll(".action-btn-sm").find((b) => b.text() === "维护")
    expect(maintBtn?.exists()).toBe(true)

    await maintBtn!.trigger("click")
    expect(apiMocks.updateCamera).toHaveBeenCalledWith(cam1Id, { maintenance: true })
  })

  it("opens PTZ modal and triggers velocity moves and stop", async () => {
    const wrapper = mount(CamerasView, {
      global: {
        stubs: {
          UiIcon: true,
          CameraDetailPanel: true,
          CameraGroupsPanel: true,
          CameraOnboardingPanel: true
        }
      }
    })
    await flushPromises()

    const ptzBtn = wrapper.find(".ptz-trigger-btn")
    expect(ptzBtn.exists()).toBe(true)
    await ptzBtn.trigger("click")
    await flushPromises()

    // PTZ Modal should be visible
    expect(wrapper.find(".ptz-modal-dialog").exists()).toBe(true)
    expect(wrapper.find(".ptz-modal-title").text()).toContain("Lobby Front Door")

    // Trigger D-Pad up button
    const dpadBtns = wrapper.findAll(".dpad-btn")
    const upBtn = dpadBtns.find((b) => b.text() === "▲")
    expect(upBtn?.exists()).toBe(true)

    await upBtn!.trigger("mousedown")
    expect(apiMocks.moveCameraPtz).toHaveBeenCalledWith(cam1Id, expect.objectContaining({ tilt: expect.any(Number) }))

    await upBtn!.trigger("mouseup")
    expect(apiMocks.stopCameraPtz).toHaveBeenCalledWith(cam1Id)
  })

  it("jumps to playback when clicking playback action button", async () => {
    const wrapper = mount(CamerasView, {
      global: {
        stubs: {
          UiIcon: true,
          CameraDetailPanel: true,
          CameraGroupsPanel: true,
          CameraOnboardingPanel: true
        }
      }
    })
    await flushPromises()

    const playbackBtn = wrapper.find(".action-btn-sm--playback")
    expect(playbackBtn.exists()).toBe(true)

    await playbackBtn.trigger("click")
    expect(mockRouterPush).toHaveBeenCalledWith({
      path: "/playback",
      query: { camera: cam1Id }
    })
  })
})
