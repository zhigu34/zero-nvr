import { flushPromises, mount } from "@vue/test-utils"
import { beforeEach, describe, expect, it, vi } from "vitest"

import RecordingScheduleView from "./RecordingScheduleView.vue"

const mockCameras = [
  {
    id: "cam-01",
    name: "Front Door 4K",
    enabled: true,
    maintenance: false,
    retired_at: null,
    location: "Entrance",
    storage_label: "local-default",
    adapter_type: "onvif",
    time_sync_mode: "manage_ntp" as const,
    ptz_capable: false,
    ip: "192.168.1.101"
  },
  {
    id: "cam-02",
    name: "Backyard PTZ",
    enabled: true,
    maintenance: false,
    retired_at: null,
    location: "Yard",
    storage_label: "pool-nvme",
    adapter_type: "onvif",
    time_sync_mode: "monitor" as const,
    ptz_capable: true,
    ip: "192.168.1.102"
  },
  {
    id: "cam-03",
    name: "Warehouse Indoor",
    enabled: true,
    maintenance: false,
    retired_at: null,
    location: "Warehouse",
    storage_label: "local-default",
    adapter_type: "onvif",
    time_sync_mode: "manage_ntp" as const,
    ptz_capable: false,
    ip: "192.168.1.103"
  }
]

const mockPolicies = [
  {
    id: "pol-01",
    camera_id: "cam-01",
    baseline_mode: "continuous" as const,
    enabled: true,
    event_recording_enabled: false,
    schedule: {},
    schedule_timezone: "UTC",
    segment_target_seconds: 300,
    pre_roll_seconds: 10,
    post_roll_seconds: 10,
    storage_target_id: "target-01",
    retention_policy_id: null,
    event_filter: {},
    runtime: {
      desired_mode: "persistent" as const,
      recording: true,
      changed: false,
      assumed_existing_mode: false
    }
  },
  {
    id: "pol-02",
    camera_id: "cam-02",
    baseline_mode: "schedule" as const,
    enabled: true,
    event_recording_enabled: false,
    schedule: {
      weekly: [
        { days: [0, 1, 2, 3, 4], start: "08:00", end: "18:00" },
        { days: [4], start: "22:00", end: "06:00" }
      ]
    },
    schedule_timezone: "Asia/Shanghai",
    segment_target_seconds: 300,
    pre_roll_seconds: 10,
    post_roll_seconds: 10,
    storage_target_id: "target-01",
    retention_policy_id: null,
    event_filter: {},
    runtime: {
      desired_mode: "persistent" as const,
      recording: true,
      changed: false,
      assumed_existing_mode: false
    }
  },
  {
    id: "pol-03",
    camera_id: "cam-03",
    baseline_mode: "disabled" as const,
    enabled: false,
    event_recording_enabled: false,
    schedule: {},
    schedule_timezone: null,
    segment_target_seconds: 300,
    pre_roll_seconds: 10,
    post_roll_seconds: 10,
    storage_target_id: null,
    retention_policy_id: null,
    event_filter: {},
    runtime: null
  }
]

const apiMocks = {
  listCameras: vi.fn(),
  listRecordingPolicies: vi.fn(),
  getRecordingPolicy: vi.fn(),
  putRecordingPolicy: vi.fn(),
  listStorageTargets: vi.fn(),
  listRetentionPolicies: vi.fn()
}

vi.mock("../api/cameras", () => ({
  listCameras: () => apiMocks.listCameras()
}))

vi.mock("../api/recordings", () => ({
  listRecordingPolicies: () => apiMocks.listRecordingPolicies(),
  getRecordingPolicy: (id: string) => apiMocks.getRecordingPolicy(id),
  putRecordingPolicy: (id: string, body: unknown) => apiMocks.putRecordingPolicy(id, body)
}))

vi.mock("../api/storage", () => ({
  listStorageTargets: () => apiMocks.listStorageTargets(),
  listRetentionPolicies: () => apiMocks.listRetentionPolicies()
}))

vi.mock("../stores/auth", () => ({
  useAuthStore: () => ({
    hasPermission: () => true
  })
}))

vi.mock("vue-router", () => ({
  useRouter: () => ({
    push: vi.fn()
  })
}))

const i18nStrings: Record<string, string> = {
  "schedules.batchApply": "批量应用周计划",
  "schedules.mode.continuous": "全天自动录像",
  "schedules.mode.weekly": "自定义周计划",
  "schedules.mode.events": "动检事件录像",
  "schedules.mode.off": "停用 / 仅手动",
}

vi.mock("vue-i18n", () => ({
  useI18n: () => ({
    t: (key: string) => i18nStrings[key] ?? key
  })
}))

describe("RecordingScheduleView.vue", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMocks.listCameras.mockResolvedValue([...mockCameras])
    apiMocks.listRecordingPolicies.mockResolvedValue([...mockPolicies])
    apiMocks.listStorageTargets.mockResolvedValue([
      { id: "target-01", name: "Local NVMe", type: "local", role: "recording", enabled: true }
    ])
    apiMocks.listRetentionPolicies.mockResolvedValue([])
    apiMocks.putRecordingPolicy.mockImplementation((id: string, body: Record<string, unknown>) =>
      Promise.resolve({
        id: `pol-${id}`,
        camera_id: id,
        ...body,
        runtime: { recording: true }
      })
    )
  })

  it("renders recording schedule table and summary stats chips", async () => {
    const wrapper = mount(RecordingScheduleView)
    await flushPromises()

    // Title and stats
    expect(wrapper.find(".schedule-title").text()).toContain("录制计划 (Schedules)")
    const statCards = wrapper.findAll(".stat-card")
    expect(statCards.length).toBe(5)

    // Table rows
    const rows = wrapper.findAll(".schedule-row")
    expect(rows.length).toBe(3)

    // Mode badges
    expect(wrapper.text()).toContain("全天自动录像")
    expect(wrapper.text()).toContain("自定义周计划")
    expect(wrapper.text()).toContain("停用 / 仅手动")
  })

  it("filters cameras by search input and mode chips", async () => {
    const wrapper = mount(RecordingScheduleView)
    await flushPromises()

    // Search query
    const searchInput = wrapper.find(".search-input")
    await searchInput.setValue("Backyard")
    await flushPromises()

    let rows = wrapper.findAll(".schedule-row")
    expect(rows.length).toBe(1)
    expect(rows[0].text()).toContain("Backyard PTZ")

    // Clear search
    await searchInput.setValue("")
    await flushPromises()
    rows = wrapper.findAll(".schedule-row")
    expect(rows.length).toBe(3)

    // Click stat card to filter by continuous
    const statCards = wrapper.findAll(".stat-card")
    await statCards[1].trigger("click") // continuous
    await flushPromises()

    rows = wrapper.findAll(".schedule-row")
    expect(rows.length).toBe(1)
    expect(rows[0].text()).toContain("Front Door 4K")
  })

  it("opens single camera schedule dialog and saves updated weekly windows", async () => {
    const wrapper = mount(RecordingScheduleView)
    await flushPromises()

    // Click "配置计划" on second camera (Backyard PTZ)
    const actionBtns = wrapper.findAll(".btn-row-action")
    expect(actionBtns.length).toBe(3)
    await actionBtns[1].trigger("click")
    await flushPromises()

    // Modal opens
    expect(wrapper.find(".dialog-card").exists()).toBe(true)
    expect(wrapper.find(".dialog-header").text()).toContain("Backyard PTZ")

    // Check weekly schedule window exists
    const windowCards = wrapper.findAll(".window-card")
    expect(windowCards.length).toBeGreaterThanOrEqual(1)

    // Save plan
    const saveBtn = wrapper.find(".btn-footer--save")
    await saveBtn.trigger("click")
    await flushPromises()

    expect(apiMocks.putRecordingPolicy).toHaveBeenCalledWith(
      "cam-02",
      expect.objectContaining({
        baseline_mode: "schedule",
        enabled: true
      })
    )
  })

  it("preserves the existing AI event filter when saving a schedule", async () => {
    apiMocks.listRecordingPolicies.mockResolvedValue(
      mockPolicies.map((policy) =>
        policy.camera_id === "cam-02"
          ? {
              ...policy,
              event_filter: {
                labels: ["person", "vehicle"],
                zones: ["driveway"],
                min_confidence: 0.72
              }
            }
          : policy
      )
    )

    const wrapper = mount(RecordingScheduleView)
    await flushPromises()

    const actionBtns = wrapper.findAll(".btn-row-action")
    await actionBtns[1].trigger("click")
    await flushPromises()

    const saveBtn = wrapper.find(".btn-footer--save")
    await saveBtn.trigger("click")
    await flushPromises()

    expect(apiMocks.putRecordingPolicy).toHaveBeenCalledWith(
      "cam-02",
      expect.objectContaining({
        event_filter: {
          labels: ["person", "vehicle"],
          zones: ["driveway"],
          min_confidence: 0.72
        }
      })
    )
  })

  it("supports multi-camera selection and batch schedule application", async () => {
    const wrapper = mount(RecordingScheduleView)
    await flushPromises()

    // Select camera 1 and camera 2
    const checkboxes = wrapper.findAll(".schedule-row input[type='checkbox']")
    expect(checkboxes.length).toBe(3)
    await checkboxes[0].setValue(true)
    await checkboxes[1].setValue(true)
    await flushPromises()

    // Batch button is now enabled
    const batchBtn = wrapper.find(".btn-action--primary")
    expect(batchBtn.attributes("disabled")).toBeUndefined()
    expect(batchBtn.text()).toContain("批量应用周计划 (2)")

    await batchBtn.trigger("click")
    await flushPromises()

    // Batch dialog opens
    expect(wrapper.find(".dialog-card").exists()).toBe(true)
    expect(wrapper.find(".dialog-header").text()).toContain("批量应用周计划 · 2 路机位")

    // Select "全天自动录像" mode
    const modeCards = wrapper.findAll(".mode-card")
    await modeCards[0].trigger("click") // continuous
    await flushPromises()

    // Click save
    const saveBtn = wrapper.find(".btn-footer--save")
    await saveBtn.trigger("click")
    await flushPromises()

    expect(apiMocks.putRecordingPolicy).toHaveBeenCalledTimes(2)
    expect(apiMocks.putRecordingPolicy).toHaveBeenCalledWith(
      "cam-01",
      expect.objectContaining({
        baseline_mode: "continuous",
        enabled: true
      })
    )
    expect(apiMocks.putRecordingPolicy).toHaveBeenCalledWith(
      "cam-02",
      expect.objectContaining({
        baseline_mode: "continuous",
        enabled: true
      })
    )
  })
})

  it("reports the observed recorder state instead of echoing the policy", async () => {
    const policyWith = (
      cameraId: string,
      runtime: Record<string, unknown>
    ) => ({
      id: `pol-${cameraId}`,
      camera_id: cameraId,
      baseline_mode: "continuous" as const,
      enabled: true,
      event_recording_enabled: false,
      schedule: {},
      schedule_timezone: null,
      segment_target_seconds: 300,
      pre_roll_seconds: 10,
      post_roll_seconds: 10,
      storage_target_id: "target-01",
      retention_policy_id: null,
      event_filter: {},
      runtime: {
        desired_mode: "persistent",
        changed: false,
        assumed_existing_mode: false,
        ...runtime
      }
    })

    const cases: Array<[string, Record<string, unknown>, string]> = [
      ["recording", { recording: true, stream_online: true }, "正在录制"],
      [
        "recorder not running on an online stream",
        { recording: false, stream_online: true },
        "流已在线 · 录制器未运行"
      ],
      [
        "stream offline",
        { recording: false, stream_online: false },
        "视频流未上线 · 未录制"
      ],
      [
        "media runtime unreachable",
        { recording: null, stream_online: null },
        "无法获取录制状态"
      ]
    ]

    for (const [name, runtime, expected] of cases) {
      apiMocks.listRecordingPolicies.mockResolvedValue([
        policyWith("cam-01", runtime)
      ])

      const wrapper = mount(RecordingScheduleView)
      await flushPromises()

      const status = wrapper.find(".runtime-status-cell")
      expect(status.text(), name).toContain(expected)
      // The 24x7 policy text must never be shown as proof of recording.
      expect(status.text(), name).not.toContain("全天录像中")

      wrapper.unmount()
    }
  })
