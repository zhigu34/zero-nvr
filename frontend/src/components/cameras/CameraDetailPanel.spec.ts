import { flushPromises, mount } from "@vue/test-utils"
import { beforeEach, describe, expect, it, vi } from "vitest"

import CameraDetailPanel from "./CameraDetailPanel.vue"

const camId = "00000000-0000-0000-0000-000000000001"

vi.mock("vue-i18n", () => ({
  useI18n: () => ({
    t: (key: string) => key,
    te: () => false
  })
}))

vi.mock("vue-router", () => ({
  useRouter: () => ({
    push: vi.fn()
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

describe("CameraDetailPanel - Recording Policy & Manual Controls", () => {
  beforeEach(() => {
    vi.clearAllMocks()

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

  it("renders recording configuration and switches modes", async () => {
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

    // Switch to recording tab
    const tabs = wrapper.findAll(".camera-detail-tabs button")
    await tabs[2].trigger("click")
    await flushPromises()

    expect(wrapper.text()).toContain("即时手动录制 (Manual Recording)")
    expect(wrapper.text()).toContain("录制策略基线模式")
    expect(wrapper.text()).toContain("全天候连续录制")
    expect(wrapper.text()).toContain("计划排程定时录制")
    expect(wrapper.text()).toContain("仅事件触发录制")
  })

  it("triggers manual recording and handles stop", async () => {
    apiMocks.createRecordingTrigger.mockResolvedValue({
      id: "trigger-1",
      camera_id: camId,
      type: "MANUAL",
      source: "api",
      requested_at: new Date().toISOString(),
      pre_roll_seconds: 10,
      post_roll_seconds: 15,
      planned_start_at: new Date().toISOString(),
      planned_end_at: null,
      state: "ACTIVE",
      reason: "夜巡异常排查",
      correlation_id: "corr-1"
    })
    apiMocks.stopRecordingTrigger.mockResolvedValue({
      id: "trigger-1",
      state: "COMPLETED"
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
          storage_label: null,
          adapter_type: "onvif",
          time_sync_mode: "manage_ntp",
          ptz_capable: false
        }
      }
    })

    await flushPromises()
    const tabs = wrapper.findAll(".camera-detail-tabs button")
    await tabs[2].trigger("click")
    await flushPromises()

    // Enter memo and start manual record
    const reasonInput = wrapper.find(".manual-reason-input")
    await reasonInput.setValue("夜巡异常排查")

    const startBtn = wrapper.find(".manual-action-btn")
    await startBtn.trigger("click")
    await flushPromises()

    expect(apiMocks.createRecordingTrigger).toHaveBeenCalledWith(camId, "夜巡异常排查")
    expect(wrapper.text()).toContain("正在录制")

    // Stop manual record
    const stopBtn = wrapper.find(".button--danger")
    await stopBtn.trigger("click")
    await flushPromises()

    expect(apiMocks.stopRecordingTrigger).toHaveBeenCalledWith("trigger-1")
  })

  it("applies schedule presets and toggles smart tags", async () => {
    const wrapper = mount(CameraDetailPanel, {
      props: {
        camera: {
          id: camId,
          name: "Front Door 4K",
          enabled: true,
          maintenance: false,
          retired_at: null,
          location: "Entrance",
          storage_label: null,
          adapter_type: "onvif",
          time_sync_mode: "manage_ntp",
          ptz_capable: false
        }
      }
    })

    await flushPromises()
    const tabs = wrapper.findAll(".camera-detail-tabs button")
    await tabs[2].trigger("click")
    await flushPromises()

    // Select schedule mode
    const modeInputs = wrapper.findAll('input[name="recording-mode"]')
    await modeInputs[1].setValue() // schedule
    await flushPromises()

    // Click workdays preset
    const presetButtons = wrapper.findAll(".preset-chip")
    expect(presetButtons.length).toBe(4)
    await presetButtons[1].trigger("click") // workdays
    await flushPromises()

    // Check smart tags
    const tagChips = wrapper.findAll(".smart-tag-chip")
    expect(tagChips.length).toBe(6)

    // Tag for person is initially selected (from policy event_filter labels)
    expect(tagChips[0].classes()).toContain("smart-tag-chip--active")

    // Click package tag to toggle it on
    await tagChips[4].trigger("click")
    await flushPromises()
    expect(tagChips[4].classes()).toContain("smart-tag-chip--active")
  })

  it("saves recording policy with accurate parameters", async () => {
    apiMocks.putRecordingPolicy.mockResolvedValue({
      id: "policy-1",
      camera_id: camId,
      baseline_mode: "continuous",
      schedule: {},
      schedule_timezone: "Asia/Shanghai",
      event_recording_enabled: true,
      event_filter: { labels: ["person"] },
      segment_target_seconds: 300,
      pre_roll_seconds: 10,
      post_roll_seconds: 15,
      storage_target_id: null,
      retention_policy_id: null,
      enabled: true,
      runtime: null
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
          storage_label: null,
          adapter_type: "onvif",
          time_sync_mode: "manage_ntp",
          ptz_capable: false
        }
      }
    })

    await flushPromises()
    const tabs = wrapper.findAll(".camera-detail-tabs button")
    await tabs[2].trigger("click")
    await flushPromises()

    const form = wrapper.find(".camera-recording-editor")
    await form.trigger("submit")
    await flushPromises()

    expect(apiMocks.putRecordingPolicy).toHaveBeenCalledWith(
      camId,
      expect.objectContaining({
        baseline_mode: "continuous",
        event_recording_enabled: true,
        pre_roll_seconds: 10,
        post_roll_seconds: 15,
        segment_target_seconds: 300
      })
    )
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
})
