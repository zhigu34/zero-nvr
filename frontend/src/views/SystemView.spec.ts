import { flushPromises, mount } from "@vue/test-utils"
import { describe, expect, it, vi } from "vitest"

import SystemView from "./SystemView.vue"

const mockSystemInfo = {
  version: "1.4.2",
  commit: "abc1234",
  build_time: "2026-09-29T12:00:00Z",
  environment: "production",
  database_backend: "sqlite_wal"
}

const mockSystemHealth = {
  status: "OK",
  components: {
    database: { status: "OK", message: "SQLite WAL active" },
    storage: {
      status: "OK",
      message: "Pool operational",
      details: {
        target_details: [
          {
            id: "target-1",
            name: "NVMe Main SSD",
            level: "NORMAL",
            used_percent: 65,
            warning_percent: 80,
            high_percent: 85,
            critical_percent: 95
          }
        ]
      }
    },
    zlm: { status: "OK", message: "ZLMediaKit 6 streams ingesting" }
  }
}

const mockSystemSettings = {
  general: {
    system_name: "zero-nvr-production-01"
  },
  time: {
    recording_timezone: "Asia/Shanghai",
    managed_camera_ntp_mode: "manual" as const,
    managed_camera_ntp_servers: ["pool.ntp.org", "time.apple.com"]
  },
  runtime: {
    prebuffer_fragment_seconds: 4,
    prebuffer_buffer_seconds: 30,
    turn_credential_ttl_seconds: 1200,
    playback_cache_mib: 512,
    playback_cache_ttl_seconds: 86400,
    playback_restore_lock_ttl_seconds: 3600,
    live_transcode_max_derivatives: 3,
    live_transcode_cpu_threads: 4,
    live_transcode_video_bitrate_kbps: 4096,
    live_transcode_idle_ttl_seconds: 30,
    live_transcode_lease_ttl_seconds: 60,
    live_transcode_startup_timeout_seconds: 5
  }
}

const mockUpdateInfo = {
  status: "UP_TO_DATE",
  latest_version: "1.4.2"
}

const mockCameras = [
  {
    id: "cam-01",
    name: "01-正门入口大堂",
    enabled: true,
    maintenance: false,
    retired_at: null,
    location: "Lobby",
    storage_label: null,
    adapter_type: "manual_rtsp",
    time_sync_mode: "monitor",
    ptz_capable: false
  }
]

const mockCameraClockHealth = {
  status: "OK",
  checked_at: "2026-09-29T16:00:00Z",
  total_devices: 1,
  ok: 1,
  degraded: 0,
  error: 0,
  results: [
    {
      device_id: "cam-01",
      name: "01-正门入口大堂",
      status: "OK",
      quality: "good",
      date_time_type: "NTP",
      timezone: "Asia/Shanghai",
      camera_utc_at: "2026-09-29T16:00:00Z",
      offset_ms: 4,
      uncertainty_ms: 1,
      rtt_ms: 12,
      error_code: null
    }
  ]
}

vi.mock("../api/system", () => ({
  getSystemInfo: vi.fn(() => Promise.resolve(mockSystemInfo)),
  getSystemHealth: vi.fn(() => Promise.resolve(mockSystemHealth)),
  getSystemSettings: vi.fn(() => Promise.resolve(mockSystemSettings)),
  getUpdateInfo: vi.fn(() => Promise.resolve(mockUpdateInfo)),
  getCameraClockHealth: vi.fn(() => Promise.resolve(mockCameraClockHealth)),
  patchSystemSettings: vi.fn(() => Promise.resolve(mockSystemSettings)),
  applyCameraNtpSettings: vi.fn(() => Promise.resolve({ success: true, updated_count: 1 })),
  listAuditEvents: vi.fn(() =>
    Promise.resolve({
      items: [
        {
          id: "audit-1",
          action: "RECORDING_LOCK",
          resource_type: "recording",
          actor_name: "admin",
          source_ip: "192.168.1.50",
          result: "SUCCESS",
          occurred_at: "2026-09-29T14:32:15Z",
          reason: "Manual lock"
        }
      ],
      next_cursor: null
    })
  ),
  listNotificationTargets: vi.fn(() => Promise.resolve([])),
  listNotificationDeliveries: vi.fn(() => Promise.resolve([])),
  getFrigateProvider: vi.fn(() => Promise.resolve({ enabled: false, base_url: "" })),
  listBackups: vi.fn(() => Promise.resolve([])),
  listBackupPolicies: vi.fn(() => Promise.resolve([]))
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
    locale: { value: "zh-CN" },
    t: (key: string, args?: Record<string, unknown>) => {
      const translations: Record<string, string> = {
        "system.main.title": "系统与运维设置",
        "system.main.navOverview": "系统概览与资源",
        "system.main.navValidation": "生产就绪度预检",
        "system.main.general": "基础参数与网络",
        "system.main.time": "时钟与 NTP 策略",
        "system.main.navUsers": "用户权限 (RBAC)",
        "system.main.navApiTokens": "API 服务令牌",
        "system.main.navOidc": "单点登录 (OIDC / SSO)",
        "system.main.notifications": "通知渠道 (Apprise)",
        "system.main.navAlertRules": "告警规则与防风暴",
        "system.main.aiFrigate": "Frigate AI 引擎配置",
        "system.main.backup": "备份与 RecoveryKit",
        "system.main.audit": "安全审计日志",
        "system.main.overview": "系统概览与健康遥测",
        "system.main.coreHealth": "核心守护进程、资源水线、媒体入流状态与数据库健康",
        "system.main.overallHealth": "整体健康状态",
        "system.main.version": "核心版本",
        "system.main.database": "持久化数据库",
        "system.main.updates": "系统更新",
        "system.main.components": "核心组件健康状态",
        "system.main.liveHealth": "实时心跳遥测与健康诊断",
        "system.main.refresh": "刷新",
        "system.main.activeBackend": "活跃引擎",
        "system.main.systemName": "NVR 实例主机名",
        "system.main.systemNameHint": "用于日志、外部客户端标识与多实例集群辨别",
        "system.main.saveGeneral": "保存配置变更",
        "system.main.runtimeTuning": "运行时性能调优",
        "system.main.runtimeHint": "针对高负载、弱网回放与实时转码的流缓冲优化",
        "system.main.eventPrebuffer": "事件录制预录缓存 (Prebuffer)",
        "system.main.eventPrebufferHint": "内存回环切片保留时间",
        "system.main.fragmentSeconds": "切片长度 (秒)",
        "system.main.bufferSeconds": "预录深度 (秒)",
        "system.main.tmpfsHint": "建议挂载 tmpfs 以减少闪存写入磨损",
        "system.main.turnCredentials": "WebRTC TURN 凭证时效",
        "system.main.turnHint": "动态派发 HMAC 临时凭据",
        "system.main.credentialTtl": "凭证有效期 (秒)",
        "system.main.playbackCacheLimit": "回放缓存上限 (MiB)",
        "system.main.playbackCacheTtl": "缓存保留周期 (秒)",
        "system.main.restoreLockTtl": "冷归档锁定防抖 (秒)",
        "system.main.compatTranscode": "转码与多码流衍生",
        "system.main.compatTranscodeHint": "H.265/H.264 动态衍生",
        "system.main.maxDerivatives": "最大并发衍生数",
        "system.main.cpuThreads": "CPU 编码线程池"
      }
      return translations[key] || (args?.name ? String(args.name) : key)
    },
    te: () => false
  })
}))

describe("SystemView (UniFi Protect Style)", () => {
  it("renders 12 navigation rail items with footer and active indicator", async () => {
    const wrapper = mount(SystemView, {
      global: {
        stubs: {
          UiIcon: true,
          SystemAccessControlPanel: true,
          SystemApiTokensPanel: true,
          SystemOidcPanel: true,
          SystemReleaseValidationPanel: true,
          SystemRecoveryKitPanel: true,
          SystemAlertRulesPanel: true,
          SystemSecretStorePanel: true
        }
      }
    })
    await flushPromises()

    expect(wrapper.find(".system-workspace").exists()).toBe(true)
    expect(wrapper.find(".system-nav").exists()).toBe(true)
    expect(wrapper.find(".system-nav__title").text()).toContain("系统与运维设置 (Settings)")

    const navButtons = wrapper.findAll(".system-nav button")
    expect(navButtons.length).toBe(12)
    expect(navButtons[0].text()).toContain("系统概览与资源")
    expect(navButtons[0].classes()).toContain("system-nav__active")

    const footer = wrapper.find(".system-nav__footer")
    expect(footer.text()).toContain("zero-nvr Core v1.4.2")
    expect(footer.text()).toContain("生产就绪 (Production)")
  })

  it("renders system overview cards with healthy orb and components", async () => {
    const wrapper = mount(SystemView, {
      global: {
        stubs: {
          UiIcon: true,
          SystemAccessControlPanel: true,
          SystemApiTokensPanel: true,
          SystemOidcPanel: true,
          SystemReleaseValidationPanel: true,
          SystemRecoveryKitPanel: true,
          SystemAlertRulesPanel: true,
          SystemSecretStorePanel: true
        }
      }
    })
    await flushPromises()

    expect(wrapper.find(".system-overview-grid").exists()).toBe(true)
    const cards = wrapper.findAll(".system-overview-card")
    expect(cards.length).toBe(4)
    expect(cards[0].find(".system-health-orb--ok").exists()).toBe(true)

    const healthComponents = wrapper.findAll(".health-component")
    expect(healthComponents.length).toBe(3)
  })

  it("switches to general settings tab and renders runtime tuning options", async () => {
    const wrapper = mount(SystemView, {
      global: {
        stubs: {
          UiIcon: true,
          SystemAccessControlPanel: true,
          SystemApiTokensPanel: true,
          SystemOidcPanel: true,
          SystemReleaseValidationPanel: true,
          SystemRecoveryKitPanel: true,
          SystemAlertRulesPanel: true,
          SystemSecretStorePanel: true
        }
      }
    })
    await flushPromises()

    const navButtons = wrapper.findAll(".system-nav button")
    const generalButton = navButtons.find((btn) => btn.text().includes("基础参数与网络"))
    expect(generalButton).toBeDefined()
    await generalButton!.trigger("click")
    await flushPromises()

    expect(wrapper.find(".system-content").text()).toContain("基础参数与网络")
    expect(wrapper.find("input[maxlength='128']").exists()).toBe(true)
    expect(wrapper.text()).toContain("运行时性能调优")
    expect(wrapper.text()).toContain("事件录制预录缓存 (Prebuffer)")
  })

  it("switches to validation panel and mounts SystemReleaseValidationPanel", async () => {
    const wrapper = mount(SystemView, {
      global: {
        stubs: {
          UiIcon: true,
          SystemAccessControlPanel: true,
          SystemApiTokensPanel: true,
          SystemOidcPanel: {
            template: `<div class="stub-oidc">SystemOidcPanel</div>`
          },
          SystemReleaseValidationPanel: {
            template: `<div class="stub-validation">SystemReleaseValidationPanel</div>`
          },
          SystemRecoveryKitPanel: true,
          SystemAlertRulesPanel: true,
          SystemSecretStorePanel: true
        }
      }
    })
    await flushPromises()

    const navButtons = wrapper.findAll(".system-nav button")
    const validationBtn = navButtons.find((btn) => btn.text().includes("生产就绪度预检"))
    expect(validationBtn).toBeDefined()
    await validationBtn!.trigger("click")
    await flushPromises()

    expect(wrapper.find(".stub-validation").exists()).toBe(true)
  })

  it("switches to time tab and displays NTP sync configuration and camera drift", async () => {
    const wrapper = mount(SystemView, {
      global: {
        stubs: {
          UiIcon: true,
          SystemAccessControlPanel: true,
          SystemApiTokensPanel: true,
          SystemOidcPanel: true,
          SystemReleaseValidationPanel: true,
          SystemRecoveryKitPanel: true,
          SystemAlertRulesPanel: true,
          SystemSecretStorePanel: true
        }
      }
    })
    await flushPromises()

    const navButtons = wrapper.findAll(".system-nav button")
    const timeButton = navButtons.find((btn) => btn.text().includes("时钟与 NTP 策略"))
    expect(timeButton).toBeDefined()
    await timeButton!.trigger("click")
    await flushPromises()

    expect(wrapper.find(".time-ntp-list").exists()).toBe(true)
    expect(wrapper.find(".camera-clock-health").exists()).toBe(true)
    expect(wrapper.find(".camera-clock-health").text()).toContain("+4 ms")
  })

  it("switches to audit log tab and displays audit trail toolbar", async () => {
    const wrapper = mount(SystemView, {
      global: {
        stubs: {
          UiIcon: true,
          SystemAccessControlPanel: true,
          SystemApiTokensPanel: true,
          SystemOidcPanel: true,
          SystemReleaseValidationPanel: true,
          SystemRecoveryKitPanel: true,
          SystemAlertRulesPanel: true,
          SystemSecretStorePanel: true
        }
      }
    })
    await flushPromises()

    const navButtons = wrapper.findAll(".system-nav button")
    const auditBtn = navButtons.find((btn) => btn.text().includes("安全审计日志"))
    expect(auditBtn).toBeDefined()
    await auditBtn!.trigger("click")
    await flushPromises()

    expect(wrapper.find(".audit-toolbar").exists()).toBe(true)
    expect(wrapper.find(".audit-list").exists()).toBe(true)
  })
})
