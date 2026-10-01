import { flushPromises, mount } from "@vue/test-utils"
import { beforeEach, describe, expect, it, vi } from "vitest"

import CameraDetailPanel from "./CameraDetailPanel.vue"

const camId = "00000000-0000-0000-0000-000000000001"

const routerMocks = vi.hoisted(() => ({
  push: vi.fn()
}))

vi.mock("vue-i18n", () => ({
  useI18n: () => ({
    t: (key: string) => key,
    te: () => false
  })
}))

vi.mock("vue-router", () => ({
  useRouter: () => ({
    push: routerMocks.push
  })
}))

vi.mock("../../stores/auth", () => ({
  useAuthStore: () => ({
    hasPermission: () => true
  })
}))

const apiMocks = vi.hoisted(() => ({
  getCamera: vi.fn(),
  updateCamera: vi.fn(),
  setCameraEnabled: vi.fn(),
  retireCamera: vi.fn(),
  restoreCamera: vi.fn(),
  refreshOnvifCapabilities: vi.fn(),
  replaceCameraBindings: vi.fn(),
  probeCamera: vi.fn(),
  verifyCameraStream: vi.fn(),
  getRecordingPolicy: vi.fn(),
  putRecordingPolicy: vi.fn(),
  listRecordingTriggers: vi.fn(),
  createRecordingTrigger: vi.fn(),
  stopRecordingTrigger: vi.fn(),
  listStorageTargets: vi.fn(),
  listRetentionPolicies: vi.fn()
}))

vi.mock("../../api/cameras", () => ({
  getCamera: apiMocks.getCamera,
  updateCamera: apiMocks.updateCamera,
  setCameraEnabled: apiMocks.setCameraEnabled,
  retireCamera: apiMocks.retireCamera,
  restoreCamera: apiMocks.restoreCamera,
  refreshOnvifCapabilities: apiMocks.refreshOnvifCapabilities,
  replaceCameraBindings: apiMocks.replaceCameraBindings,
  probeCamera: apiMocks.probeCamera,
  verifyCameraStream: apiMocks.verifyCameraStream
}))

vi.mock("../../api/recordings", () => ({
  getRecordingPolicy: apiMocks.getRecordingPolicy,
  putRecordingPolicy: apiMocks.putRecordingPolicy,
  listRecordingTriggers: apiMocks.listRecordingTriggers,
  createRecordingTrigger: apiMocks.createRecordingTrigger,
  stopRecordingTrigger: apiMocks.stopRecordingTrigger
}))

vi.mock("../../api/storage", () => ({
  listStorageTargets: apiMocks.listStorageTargets,
  listRetentionPolicies: apiMocks.listRetentionPolicies
}))

describe("CameraDetailPanel - Drawer Surface (Recording Delegated To Schedules)", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    Object.defineProperty(HTMLMediaElement.prototype, "pause", {
      configurable: true,
      value: vi.fn()
    })
    Object.defineProperty(HTMLMediaElement.prototype, "load", {
      configurable: true,
      value: vi.fn()
    })

    apiMocks.getCamera.mockResolvedValue({
      id: camId,
      name: "Front Door 4K",
      enabled: true,
      maintenance: false,
      retired_at: null,
      location: "Entrance",
      storage_label: "local-fast",
      adapter_type: "onvif",
      time_sync_mode: "manage_ntp",
      ptz_capable: false,
      streams: [
        {
          id: "str-1",
          name: "Main",
          adapter_profile_key: "p-main",
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
        { purpose: "RECORD", stream_profile_id: "str-1", selection_mode: "auto" }
      ]
    })

    apiMocks.getRecordingPolicy.mockResolvedValue({
      id: "policy-1",
      camera_id: camId,
      baseline_mode: "continuous",
      schedule: {},
      schedule_timezone: "Asia/Shanghai",
      event_recording_enabled: true,
      event_filter: {
        labels: ["person", "car"],
        zones: ["driveway"],
        min_confidence: 0.65
      },
      segment_target_seconds: 300,
      pre_roll_seconds: 10,
      post_roll_seconds: 15,
      storage_target_id: null,
      retention_policy_id: null,
      enabled: true,
      runtime: {
        desired_mode: "persistent",
        recording: true,
        changed: false,
        assumed_existing_mode: true
      }
    })

    apiMocks.listRecordingTriggers.mockResolvedValue([])
    apiMocks.listStorageTargets.mockResolvedValue([])
    apiMocks.listRetentionPolicies.mockResolvedValue([])
  })

  it("delegates recording control to the recording schedule view", async () => {
    const wrapper = mount(CameraDetailPanel, {
      props: {
        camera: {
          id: camId,
          name: "Front Door 4K",
          enabled: true,
          maintenance: false,
          retired_at: null,
          location: "Entrance",
          storage_label: "local-fast",
          adapter_type: "onvif",
          time_sync_mode: "manage_ntp",
          ptz_capable: false
        }
      }
    })

    await flushPromises()

    // Only general + streams tabs remain; the recording tab is gone
    const tabs = wrapper.findAll(".camera-detail-tabs button")
    expect(tabs.length).toBe(2)
    expect(tabs.map((tab) => tab.text())).toEqual([
      "cameras.detail.general",
      "cameras.detail.streams"
    ])

    // No manual recording trigger buttons anywhere in the drawer
    expect(wrapper.text()).not.toContain("启动录像")
    expect(wrapper.text()).not.toContain("停止录像")
    expect(wrapper.find(".quick-action-btn--record").exists()).toBe(false)
    expect(wrapper.find(".quick-action-btn--stop").exists()).toBe(false)

    // Recording state is reported from the schedule runtime only
    expect(wrapper.find(".device-hero-card").text()).toContain("正在录像")

    // Quick action bar links straight to the recording schedule page
    const scheduleBtn = wrapper
      .findAll(".quick-action-btn")
      .find((btn) => btn.text().includes("录制计划"))
    expect(scheduleBtn).toBeDefined()
    await scheduleBtn!.trigger("click")

    expect(routerMocks.push).toHaveBeenCalledWith({ path: "/recording-schedules" })
    expect(apiMocks.createRecordingTrigger).not.toHaveBeenCalled()
    expect(apiMocks.putRecordingPolicy).not.toHaveBeenCalled()
  })

  it("shows the observed recording state in the hero card", async () => {
    const cases: Array<[Record<string, unknown>, string]> = [
      [{ recording: true, stream_online: true }, "正在录像"],
      [{ recording: false, stream_online: true }, "流已在线 · 未录像"],
      [{ recording: false, stream_online: false }, "视频流未上线 · 未录像"],
      [{ recording: null, stream_online: null }, "无法获取录像状态"]
    ]

    for (const [runtime, expected] of cases) {
      apiMocks.getRecordingPolicy.mockResolvedValue({
        id: "policy-1",
        camera_id: camId,
        baseline_mode: "continuous",
        schedule: {},
        schedule_timezone: null,
        event_recording_enabled: false,
        event_filter: {},
        segment_target_seconds: 300,
        pre_roll_seconds: 10,
        post_roll_seconds: 10,
        storage_target_id: null,
        retention_policy_id: null,
        enabled: true,
        runtime: {
          desired_mode: "persistent",
          changed: false,
          assumed_existing_mode: false,
          ...runtime
        }
      })

      const wrapper = mount(CameraDetailPanel, {
        props: {
          camera: {
            id: camId,
            name: "Front Door 4K",
            enabled: true,
            maintenance: false,
            retired_at: null,
            location: "Entrance",
            storage_label: "local-fast",
            adapter_type: "onvif",
            time_sync_mode: "manage_ntp",
            ptz_capable: false
          }
        }
      })
      await flushPromises()

      const hero = wrapper.find(".device-hero-card")
      expect(hero.text(), JSON.stringify(runtime)).toContain(expected)
      // A 24x7 policy must never render as an idle "waiting" state.
      expect(hero.text(), JSON.stringify(runtime)).not.toContain("空闲待命")

      wrapper.unmount()
    }
  })

  it("renders hero card, fast navigation between cameras, and triggers probe", async () => {
    apiMocks.probeCamera.mockResolvedValue({
      id: camId,
      name: "Front Door 4K",
      manufacturer: "Hikvision",
      model: "DS-2CD2T87G2-L",
      form_factor: "bullet",
      video_codec: "h265",
      width: 3840,
      height: 2160,
      fps: 25,
      audio_codec: "aac",
      connectivity_status: "online",
      last_probe_at: "2026-09-29T11:00:00Z",
      streams: [],
      bindings: []
    })

    const wrapper = mount(CameraDetailPanel, {
      props: {
        camera: {
          id: camId,
          name: "Front Door 4K",
          enabled: true,
          maintenance: false,
          retired_at: null,
          location: "Entrance",
          storage_label: "local-fast",
          adapter_type: "onvif",
          time_sync_mode: "manage_ntp",
          ptz_capable: false
        },
        cameras: [
          {
            id: camId,
            name: "Front Door 4K",
            enabled: true,
            maintenance: false,
            retired_at: null,
            location: "Entrance",
            storage_label: "local-fast",
            adapter_type: "onvif",
            time_sync_mode: "manage_ntp",
            ptz_capable: false
          },
          {
            id: "00000000-0000-0000-0000-000000000002",
            name: "Backyard PTZ",
            enabled: true,
            maintenance: false,
            retired_at: null,
            location: "Backyard",
            storage_label: null,
            adapter_type: "onvif",
            time_sync_mode: "monitor",
            ptz_capable: true
          }
        ]
      }
    })

    await flushPromises()

    // Hero card renders
    expect(wrapper.find(".device-hero-card").exists()).toBe(true)

    // Fast navigation buttons
    const navStepBtns = wrapper.findAll(".nav-step-btn")
    expect(navStepBtns.length).toBe(2)
    // First button (prev) is disabled because index is 0
    expect(navStepBtns[0].attributes("disabled")).toBeDefined()
    // Second button (next) is enabled
    expect(navStepBtns[1].attributes("disabled")).toBeUndefined()

    await navStepBtns[1].trigger("click")
    expect(wrapper.emitted("navigate")).toBeTruthy()
    expect(wrapper.emitted("navigate")![0][0]).toEqual(
      expect.objectContaining({ name: "Backyard PTZ" })
    )

    // Probe button trigger
    const probeBtn = wrapper.find(".quick-action-btn")
    expect(probeBtn.text()).toContain("连接检测")
    await probeBtn.trigger("click")
    await flushPromises()

    expect(apiMocks.probeCamera).toHaveBeenCalledWith(camId)
  })

  it("verifies stream profile and saves general form with manufacturer & form_factor", async () => {
    apiMocks.updateCamera.mockResolvedValue({
      id: camId,
      name: "Front Door 4K Pro",
      manufacturer: "Hikvision",
      model: "DS-2CD2T87G2-L",
      form_factor: "bullet",
      location: "East Gate",
      storage_label: "pool-nvme",
      enabled: true,
      maintenance: false,
      retired_at: null,
      adapter_type: "onvif",
      time_sync_mode: "manage_ntp",
      ptz_capable: false,
      streams: [],
      bindings: []
    })

    const wrapper = mount(CameraDetailPanel, {
      props: {
        camera: {
          id: camId,
          name: "Front Door 4K",
          enabled: true,
          maintenance: false,
          retired_at: null,
          location: "Entrance",
          storage_label: "local-fast",
          adapter_type: "onvif",
          time_sync_mode: "manage_ntp",
          ptz_capable: false
        }
      }
    })

    await flushPromises()

    // Test stream verify in streams tab
    const tabs = wrapper.findAll(".camera-detail-tabs button")
    await tabs[1].trigger("click") // streams tab
    await flushPromises()

    const verifyBtn = wrapper.find(".stream-actions button")
    expect(verifyBtn.exists()).toBe(true)
    await verifyBtn.trigger("click")
    await flushPromises()

    expect(apiMocks.verifyCameraStream).toHaveBeenCalledWith(camId, "str-1")

    // Test saving general form
    await tabs[0].trigger("click") // general tab
    await flushPromises()

    const brandPills = wrapper.findAll(".brand-pill")
    expect(brandPills.length).toBeGreaterThan(0)
    // Click first brand pill (Hikvision)
    await brandPills[0].trigger("click")
    await flushPromises()

    const form = wrapper.find(".camera-detail-form")
    await form.trigger("submit")
    await flushPromises()

    expect(apiMocks.updateCamera).toHaveBeenCalledWith(
      camId,
      expect.objectContaining({
        manufacturer: expect.stringContaining("海康威视")
      })
    )
  })

  it("emits openPtz when clicking PTZ quick action and toggles maintenance", async () => {
    apiMocks.updateCamera.mockResolvedValue({
      id: camId,
      name: "Front Door 4K",
      enabled: true,
      maintenance: true,
      retired_at: null,
      location: "Entrance",
      storage_label: "local-fast",
      adapter_type: "onvif",
      time_sync_mode: "manage_ntp",
      ptz_capable: true
    })

    const wrapper = mount(CameraDetailPanel, {
      props: {
        camera: {
          id: camId,
          name: "Front Door 4K",
          enabled: true,
          maintenance: false,
          retired_at: null,
          location: "Entrance",
          storage_label: "local-fast",
          adapter_type: "onvif",
          time_sync_mode: "manage_ntp",
          ptz_capable: true
        }
      }
    })
    await flushPromises()

    // PTZ quick action button
    const ptzBtn = wrapper.find(".quick-action-btn--ptz")
    expect(ptzBtn.exists()).toBe(true)
    await ptzBtn.trigger("click")
    expect(wrapper.emitted("openPtz")).toBeTruthy()

    // Toggle maintenance in general tab actions
    const maintBtn = wrapper.findAll(".camera-detail-actions button").find((b) => b.text().includes("进入维护模式"))
    expect(maintBtn?.exists()).toBe(true)
    await maintBtn!.trigger("click")
    await flushPromises()

    expect(apiMocks.updateCamera).toHaveBeenCalledWith(camId, { maintenance: true })
  })

  it("defaults live preview to paused and toggles via center play button", async () => {
    const wrapper = mount(CameraDetailPanel, {
      props: {
        camera: {
          id: camId,
          name: "Front Door 4K",
          enabled: true,
          maintenance: false,
          retired_at: null,
          location: "Entrance",
          storage_label: "local-fast",
          adapter_type: "onvif",
          time_sync_mode: "manage_ntp",
          ptz_capable: false
        }
      },
      global: {
        stubs: {
          LiveCameraTile: {
            template: `<div class="mock-live-camera-tile">LiveCameraTile</div>`
          }
        }
      }
    })
    await flushPromises()

    // Initially preview is NOT playing
    expect(wrapper.find(".preview-toggle-btn").text()).toContain("未播放")
    expect(wrapper.find(".mock-live-camera-tile").exists()).toBe(false)

    // Center play button exists
    const centerBtn = wrapper.find(".preview-center-btn")
    expect(centerBtn.exists()).toBe(true)
    expect(centerBtn.classes()).not.toContain("preview-center-btn--pause")

    // Clicking center play button starts stream
    await centerBtn.trigger("click")
    await flushPromises()

    expect(wrapper.find(".preview-toggle-btn").text()).toContain("正在直播")
    expect(wrapper.find(".mock-live-camera-tile").exists()).toBe(true)
    expect(centerBtn.classes()).toContain("preview-center-btn--pause")

    // Clicking pause button stops stream
    await centerBtn.trigger("click")
    await flushPromises()

    expect(wrapper.find(".preview-toggle-btn").text()).toContain("未播放")
    expect(wrapper.find(".mock-live-camera-tile").exists()).toBe(false)
  })
})

