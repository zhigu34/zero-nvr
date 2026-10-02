import { QueryClient } from "@tanstack/react-query"
import { fireEvent, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { SystemView } from "./SystemView"
import { renderWithProviders } from "../test-utils"
import { SYSTEM } from "../lib/queries"
import type { SystemSettings } from "../api/systemSettings"

/**
 * The page has one job beyond rendering: not letting the operator believe the
 * `general` group is a second place to set the timezone, and not letting them
 * believe setting the system timezone changes anything.
 */

const SETTINGS: SystemSettings = {
  general: {
    system_name: "小区 NVR",
    display_timezone: "Asia/Shanghai",
    camera_ntp_servers: ["ntp.aliyun.com"],
  },
  time: {
    recording_timezone: "Asia/Shanghai",
    managed_camera_ntp_mode: "manual",
    managed_camera_ntp_servers: ["ntp.aliyun.com"],
  },
  runtime: {
    prebuffer_fragment_seconds: 4,
    prebuffer_buffer_seconds: 60,
    turn_credential_ttl_seconds: 300,
    playback_cache_max_bytes: 512 * 1024 * 1024,
    playback_cache_ttl_seconds: 3600,
    playback_restore_lock_ttl_seconds: 600,
    live_transcode_max_derivatives: 2,
    live_transcode_idle_ttl_seconds: 30,
    live_transcode_lease_ttl_seconds: 60,
    live_transcode_startup_timeout_seconds: 10,
    live_transcode_cpu_threads: 2,
    live_transcode_video_bitrate_kbps: 2048,
  },
}

let patched: Record<string, unknown> | null = null

afterEach(() => {
  vi.unstubAllGlobals()
  patched = null
})

function renderView(overrides: Partial<SystemSettings> = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const settings = { ...SETTINGS, ...overrides }
  client.setQueryData(SYSTEM.settings, settings)
  client.setQueryData(SYSTEM.health, {
    status: "OK",
    components: {
      database: { status: "OK", message: "正常", details: {} },
      media: { status: "DEGRADED", message: "转码槽位紧张", details: {} },
    },
  })
  client.setQueryData(SYSTEM.clockHealth, {
    status: "ok",
    checked_at: "2026-10-01T00:00:00Z",
    total_devices: 2,
    ok: 1,
    degraded: 1,
    error: 0,
    results: [
      {
        device_id: "d1",
        name: "前门",
        offset_ms: 12,
        uncertainty_ms: 5,
        rtt_ms: 3,
        error_code: null,
      },
      {
        device_id: "d2",
        name: "后院",
        offset_ms: null,
        uncertainty_ms: null,
        rtt_ms: null,
        error_code: "clock_unreachable",
      },
    ],
  })

  vi.stubGlobal(
    "fetch",
    vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "PATCH") {
        patched = init.body ? JSON.parse(String(init.body)) : {}
        return new Response(JSON.stringify(SETTINGS), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      }
      return new Response("{}", {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    }),
  )

  return renderWithProviders(<SystemView />, { client })
}

describe("SystemView", () => {
  it("renders the three groups", async () => {
    renderView()
    await waitFor(() => {
      expect(screen.getByText("系统名称")).toBeTruthy()
    })
    expect(screen.getByText("录制时区")).toBeTruthy()
    expect(screen.getByText("运行时调优")).toBeTruthy()
  })

  it("shows the general timezone as a read-only mirror", async () => {
    renderView()
    await waitFor(() => {
      expect(screen.getByLabelText("显示时区（只读镜像）")).toBeTruthy()
    })
    const mirror = screen.getByLabelText(
      "显示时区（只读镜像）",
    ) as HTMLInputElement
    expect(mirror.readOnly).toBe(true)
    expect(mirror.value).toBe("Asia/Shanghai")
  })

  it("says the recording timezone setting does nothing", async () => {
    // This field exists and accepts a value, which is exactly why it needs a
    // label: without one, an operator assumes it changes when recordings cut.
    renderView()
    await waitFor(() => {
      expect(screen.getByText("该设置当前不生效")).toBeTruthy()
    })
    expect(screen.getByText(/schedule_timezone/)).toBeTruthy()
  })

  it("says the NTP mode follows the server list", async () => {
    renderView()
    await waitFor(() => {
      expect(screen.getByText(/自动切到「手动」/)).toBeTruthy()
    })
  })

  it("renders each runtime value in its own unit", async () => {
    renderView()
    await waitFor(() => {
      expect(screen.getByText("回放缓存上限")).toBeTruthy()
    })
    // A byte count displayed as "512 MiB", never as a number of seconds.
    // Shown twice on purpose: once under the field, once in the unit warning.
    expect(screen.getAllByText(/512 MiB/).length).toBeGreaterThan(0)
    expect(screen.queryByText(/512000000 秒/)).toBeNull()
  })

  it("blocks saving a value outside the backend range", async () => {
    renderView()
    await waitFor(() => {
      expect(screen.getByLabelText("转码 CPU 线程")).toBeTruthy()
    })

    fireEvent.change(screen.getByLabelText("转码 CPU 线程"), {
      target: { value: "99" },
    })

    await waitFor(() => {
      expect(screen.getByText(/转码 CPU 线程需在/)).toBeTruthy()
    })
    const save = screen.getByRole("button", { name: "保存" }) as HTMLButtonElement
    expect(save.disabled).toBe(true)
  })

  it("sends only the group that changed", async () => {
    renderView()
    await waitFor(() => {
      expect(screen.getByLabelText("系统名称")).toBeTruthy()
    })

    fireEvent.change(screen.getByLabelText("系统名称"), {
      target: { value: "新名字" },
    })
    fireEvent.click(screen.getByRole("button", { name: "保存" }))

    await waitFor(() => {
      expect(patched).not.toBeNull()
    })
    expect(patched).toEqual({ general: { system_name: "新名字" } })
    // The NTP list was not touched, so the mode is not rewritten.
    expect(patched).not.toHaveProperty("time")
  })

  it("sends the NTP mode alongside the list, because the backend couples them", async () => {
    renderView()
    await waitFor(() => {
      expect(screen.getByLabelText("托管 NTP 服务器")).toBeTruthy()
    })

    fireEvent.change(screen.getByLabelText("托管 NTP 服务器"), {
      target: { value: "" },
    })
    fireEvent.click(screen.getByRole("button", { name: "保存" }))

    await waitFor(() => {
      expect(patched).not.toBeNull()
    })
    // Clearing the list flips the mode to dhcp server-side
    // (`system/api.py:1086`); sending the list alone would rely on that.
    expect(patched).toMatchObject({
      time: {
        managed_camera_ntp_mode: "dhcp",
        managed_camera_ntp_servers: [],
      },
    })
  })

  it("sends only the runtime keys that moved", async () => {
    renderView()
    await waitFor(() => {
      expect(screen.getByLabelText("转码路数上限")).toBeTruthy()
    })

    fireEvent.change(screen.getByLabelText("转码路数上限"), {
      target: { value: "4" },
    })
    fireEvent.click(screen.getByRole("button", { name: "保存" }))

    await waitFor(() => {
      expect(patched).not.toBeNull()
    })
    expect(patched).toEqual({ runtime: { live_transcode_max_derivatives: 4 } })
  })

  it("keeps save disabled until something actually changes", async () => {
    renderView()
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "保存" })).toBeTruthy()
    })
    expect(
      (screen.getByRole("button", { name: "保存" }) as HTMLButtonElement).disabled,
    ).toBe(true)
  })

  it("shows component health with its own messages", async () => {
    renderView()
    await waitFor(() => {
      expect(screen.getByText("媒体服务")).toBeTruthy()
    })
    expect(screen.getByText("转码槽位紧张")).toBeTruthy()
  })

  it("shows per-device clock offsets and their failures", async () => {
    renderView()
    await waitFor(() => {
      expect(screen.getByText(/设备时钟/)).toBeTruthy()
    })
    expect(screen.getByText("12 ms")).toBeTruthy()
    // An unreachable device shows a dash, not a fabricated 0.
    expect(screen.getByText("—")).toBeTruthy()
  })

  it("surfaces a settings load failure", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    client.setQueryData(SYSTEM.settings, undefined)
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).includes("/system/settings")) {
          return new Response(
            JSON.stringify({ error: { code: "x", message: "内部错误" } }),
            { status: 500, headers: { "Content-Type": "application/json" } },
          )
        }
        return new Response("{}", {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      }),
    )

    renderWithProviders(<SystemView />, { client })

    await waitFor(() => {
      expect(screen.getByText("无法加载系统设置")).toBeTruthy()
    })
  })
})

describe("SystemView 的 tab 外壳", () => {
  it("设置读取失败时，通知渠道仍然可达", async () => {
    // 这是 tab 外壳放在 guard 之外的全部理由：「系统设置坏了」不应该同时意味着
    // 「看不到告警发不出去」——而投递记录恰恰是操作员最需要读的东西。
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).includes("/system/settings")) {
          return new Response(
            JSON.stringify({ error: { code: "x", message: "内部错误" } }),
            { status: 500, headers: { "Content-Type": "application/json" } },
          )
        }
        if (String(input).includes("/notification-targets")) {
          return new Response("[]", {
            status: 200,
            headers: { "Content-Type": "application/json" },
          })
        }
        return new Response("{}", {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      }),
    )

    renderWithProviders(<SystemView />, { client })
    await waitFor(() => {
      expect(screen.getByText("无法加载系统设置")).toBeTruthy()
    })

    fireEvent.click(screen.getByRole("tab", { name: /通知渠道/ }))
    expect(await screen.findByText("还没有通知目标")).toBeTruthy()
  })

  it("四个 tab 都在，且令牌不在这里", async () => {
    renderView()
    await waitFor(() => {
      expect(screen.getByText("系统名称")).toBeTruthy()
    })
    for (const name of ["系统设置", "通知渠道", "密钥环", "Frigate 集成"]) {
      expect(screen.getByRole("tab", { name: new RegExp(name) })).toBeTruthy()
    }
    // Personal tokens are the signed-in account's own resource and live on
    // /account (G-32); an admin page is the wrong place to imply otherwise.
    expect(screen.queryByRole("tab", { name: /令牌/ })).toBeNull()
  })
})
