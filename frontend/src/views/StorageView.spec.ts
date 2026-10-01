import { flushPromises, mount } from "@vue/test-utils"
import { describe, expect, it, vi } from "vitest"

import StorageView from "./StorageView.vue"

const mockTargets = [
  {
    id: "target-local-01",
    type: "local" as const,
    role: "recording" as const,
    name: "NVMe Main SSD",
    enabled: true,
    config: {
      path: "/data/recordings",
      default_recording: true,
      warning_used_percent: 80,
      high_used_percent: 85,
      critical_used_percent: 95
    },
    credentials_configured: true
  },
  {
    id: "target-archive-01",
    type: "rclone" as const,
    role: "archive" as const,
    name: "NAS Cloud Tier",
    enabled: true,
    config: {
      remote: "openlist",
      base_path: "archive",
      default_archive: true,
      provider: "openlist_webdav"
    },
    credentials_configured: true
  }
]

const mockPolicies = [
  {
    id: "policy-global-01",
    name: "Global Default Policy",
    scope_type: "GLOBAL" as const,
    scope_id: null,
    ordinary_keep_days: 14,
    event_keep_days: 30,
    manual_keep_days: 90,
    mode: "BEST_EFFORT" as const,
    require_archive_before_delete: true,
    enabled: true
  },
  {
    id: "policy-camera-01",
    name: "Server Room High Retention",
    scope_type: "CAMERA" as const,
    scope_id: "cam-01",
    ordinary_keep_days: 60,
    event_keep_days: 180,
    manual_keep_days: 365,
    mode: "HARD" as const,
    require_archive_before_delete: true,
    enabled: true
  }
]

const mockCameras = [
  {
    id: "cam-01",
    name: "01-Server Room Entrance",
    enabled: true,
    maintenance: false,
    retired_at: null,
    location: "Server Room",
    storage_label: null,
    adapter_type: "manual_rtsp",
    time_sync_mode: "monitor",
    ptz_capable: false
  }
]

vi.mock("../api/storage", () => ({
  listStorageTargets: vi.fn(() => Promise.resolve(mockTargets)),
  listRetentionPolicies: vi.fn(() => Promise.resolve(mockPolicies)),
  testStorageTarget: vi.fn((id: string) =>
    Promise.resolve({
      ok: true,
      type: id === "target-local-01" ? "local" : "rclone",
      detail: "Ready and healthy",
      free_bytes: 720 * 1024 * 1024 * 1024,
      total_bytes: 4000 * 1024 * 1024 * 1024,
      used_bytes: 3280 * 1024 * 1024 * 1024,
      used_percent: 82.0,
      capacity_level: "normal",
      warning_percent: 80,
      high_percent: 85,
      critical_percent: 95
    })
  ),
  createStorageTarget: vi.fn(),
  updateStorageTarget: vi.fn(),
  deleteStorageTarget: vi.fn(),
  switchRecordingTarget: vi.fn(),
  createRetentionPolicy: vi.fn(),
  updateRetentionPolicy: vi.fn(),
  deleteRetentionPolicy: vi.fn()
}))

vi.mock("../api/cameras", () => ({
  listCameras: vi.fn(() => Promise.resolve(mockCameras))
}))

vi.mock("../stores/auth", () => ({
  useAuthStore: () => ({
    hasPermission: () => true
  })
}))

vi.mock("vue-i18n", () => ({
  useI18n: () => ({
    t: (key: string, args?: Record<string, unknown>) => {
      if (key === "storage.title") return "Storage"
      if (key === "storage.days" && args?.count !== undefined) {
        return `${args.count} 天`
      }
      return key
    },
    te: () => false
  })
}))

describe("StorageView (UniFi Protect Style)", () => {
  it("renders storage header and subtab pills", async () => {
    const wrapper = mount(StorageView, {
      global: {
        stubs: { UiIcon: true }
      }
    })
    await flushPromises()

    expect(wrapper.text()).toContain("存储管理 (Storage)")
    expect(wrapper.find(".unifi-subtabs-pill").exists()).toBe(true)
    expect(wrapper.findAll(".unifi-subtab-btn").length).toBe(2)
  })

  it("renders local NVMe target with watermark markers and capacity bar", async () => {
    const wrapper = mount(StorageView, {
      global: {
        stubs: { UiIcon: true }
      }
    })
    await flushPromises()

    const localCard = wrapper.findAll(".unifi-target-card").at(0)
    expect(localCard?.text()).toContain("本地高速录像缓存池 (NVMe Main SSD)")
    expect(localCard?.find(".unifi-watermark-bar-track").exists()).toBe(true)
    expect(localCard?.findAll(".unifi-watermark-marker").length).toBe(3)
    expect(localCard?.text()).toContain("警戒水位: 80%")
    expect(localCard?.text()).toContain("高水位: 85%")
    expect(localCard?.text()).toContain("极值水位: 95%")
  })

  it("renders WebDAV archive target with service protocol details", async () => {
    const wrapper = mount(StorageView, {
      global: {
        stubs: { UiIcon: true }
      }
    })
    await flushPromises()

    const archiveCard = wrapper.findAll(".unifi-target-card").at(1)
    expect(archiveCard?.text()).toContain("WebDAV 在线存储池 (NAS Cloud Tier)")
    expect(archiveCard?.text()).toContain("WebDAV (OpenList / Alist / NAS)")
    expect(archiveCard?.text()).toContain("前端无感等同于本地")
  })

  it("switches to retention policies tab and displays structured table", async () => {
    const wrapper = mount(StorageView, {
      global: {
        stubs: { UiIcon: true }
      }
    })
    await flushPromises()

    const subtabButtons = wrapper.findAll(".unifi-subtab-btn")
    await subtabButtons[1].trigger("click")
    await flushPromises()

    expect(wrapper.find(".unifi-retention-table").exists()).toBe(true)
    const rows = wrapper.findAll(".unifi-retention-table tbody tr")
    expect(rows.length).toBe(2)
    expect(rows[0].text()).toContain("Global Default Policy")
    expect(rows[0].text()).toContain("14 天")
    expect(rows[0].text()).toContain("30 天")
    expect(rows[0].text()).toContain("90 天")
    expect(rows[0].text()).toContain("BEST_EFFORT")

    expect(rows[1].text()).toContain("Server Room High Retention")
    expect(rows[1].text()).toContain("01-Server Room Entrance")
    expect(rows[1].text()).toContain("60 天")
    expect(rows[1].text()).toContain("180 天")
    expect(rows[1].text()).toContain("365 天")
    expect(rows[1].text()).toContain("HARD")
  })
})
