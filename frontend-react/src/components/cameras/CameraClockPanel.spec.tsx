import { QueryClient } from "@tanstack/react-query"
import { screen, waitFor, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { CameraClockPanel } from "./CameraClockPanel"
import { renderWithProviders } from "../../test-utils"
import type { CameraClock, TimeSyncMode } from "../../api/cameras"

/**
 * 摄像机时钟偏差。
 *
 * 核心断言只有一条：**四种「没有漂移数据」的原因必须给出四句不同的话**。Vue
 * 那版只检查 `offset_ms === null` 然后拿 `time_sync_mode` 拼一句
 * （`CamerasView.vue:481-497`），把「设备没这个能力」「操作员主动忽略」「还没测」
 * 说成了同一件事——其中「不支持」被说成「待测」最糟，一台手动 RTSP 摄像机永远
 * 不可能有漂移数据。
 *
 * 第五条（读失败）不在简报的四分支里，但后端能产生：一次真实的失败测量会存下
 * `health="critical"` + `offset_ms=None` + `error_code`（`system/api.py:1337-1350`、
 * `:1479-1492`、`:1506-1519`）。它和「尚未测量」必须分开，所以一并断言。
 */

const MEASURED_AT = "2026-03-04T05:06:07.000Z"

function clock(overrides: Partial<CameraClock> = {}): CameraClock {
  return {
    camera_id: "c1",
    // Distinguishes "no device record" from "device is not ONVIF" — the two
    // `unsupported` branches (`cameras/api.py:1424-1431` vs `:1437-1447`).
    device_id: "dev-1",
    health: "unknown",
    quality: "unknown",
    sync_mode: "monitor",
    measured_at: null,
    offset_ms: null,
    uncertainty_ms: null,
    rtt_ms: null,
    device_timezone: null,
    device_time_source: null,
    error_code: null,
    ...overrides,
  }
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

function renderPanel(
  options: {
    body?: unknown
    status?: number
    /** Request that never settles, to hold the panel in its loading state. */
    pending?: boolean
    syncMode?: TimeSyncMode
  } = {},
) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => {
      if (options.pending) return new Promise<Response>(() => {})
      return json(options.body ?? {}, options.status ?? 200)
    }),
  )

  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return renderWithProviders(
    <CameraClockPanel cameraId="c1" syncMode={options.syncMode ?? "monitor"} />,
    { client },
  )
}

/** A `KeyValue` row, scoped by its label, so equal values stay unambiguous. */
function row(label: string): HTMLElement {
  return screen.getByText(label).parentElement as HTMLElement
}

const UNSUPPORTED = "该设备不支持读取时钟"
const IGNORED = "该通道已设为忽略时钟"
const UNMEASURED = "尚未测量"
const UNREADABLE = "读取设备时钟失败"

/** Every "no drift number" reason this panel can report. */
const NO_DRIFT_TITLES = [UNSUPPORTED, IGNORED, UNMEASURED, UNREADABLE]

/* -------------------------------------------------------------------------- */

describe("摄像机时钟 · 没有漂移数据的四种原因必须分开", () => {
  const cases: {
    what: string
    syncMode: TimeSyncMode
    payload: CameraClock
    mine: string
    // The backend branch this reproduces.
    backend: string
  }[] = [
    {
      what: "设备不支持读时钟",
      syncMode: "monitor",
      payload: clock({ health: "unsupported", quality: "unknown" }),
      mine: UNSUPPORTED,
      backend: "cameras/api.py:1424-1431（无 device_id）与 :1437-1447（设备非 ONVIF）",
    },
    {
      what: "操作员主动忽略",
      syncMode: "ignore",
      payload: clock({ health: "unknown", sync_mode: "ignore" }),
      mine: IGNORED,
      backend: "cameras/api.py:1449-1456",
    },
    {
      what: "尚未测量",
      syncMode: "monitor",
      payload: clock({ health: "unknown", quality: "unknown" }),
      mine: UNMEASURED,
      backend: "cameras/api.py:1465-1472",
    },
    {
      what: "测了但读失败",
      syncMode: "manage_ntp",
      payload: clock({
        health: "critical",
        measured_at: MEASURED_AT,
        error_code: "camera_clock_check_failed",
      }),
      mine: UNREADABLE,
      backend: "system/api.py:1479-1492",
    },
  ]

  for (const { what, syncMode, payload, mine, backend } of cases) {
    it(`${what}说的是自己那一句，不是别的三句（${backend}）`, async () => {
      renderPanel({ body: payload, syncMode })

      expect(await screen.findByText(mine)).toBeTruthy()
      for (const other of NO_DRIFT_TITLES.filter((t) => t !== mine)) {
        expect(screen.queryByText(other)).toBeNull()
      }
    })
  }

  it("不支持读时钟不等于「待测」——换个配置也不会有数据", async () => {
    renderPanel({ body: clock({ health: "unsupported" }) })

    await screen.findByText(UNSUPPORTED)
    // Vue 的 "Managed NTP · 待测" 就是这一句，它暗示等一下就会好。
    expect(screen.queryByText(/待测/)).toBeNull()
  })

  it("unsupported 优先于 ignore：后端先判能力，再判模式", async () => {
    // `cameras/api.py:1424-1447` 在 `:1449` 之前返回，所以一台非 ONVIF 且被设为
    // 忽略的通道，说的是「不支持」。顺序反了就说错了。
    renderPanel({ body: clock({ health: "unsupported" }), syncMode: "ignore" })

    expect(await screen.findByText(UNSUPPORTED)).toBeTruthy()
    expect(screen.queryByText(IGNORED)).toBeNull()
  })

  it("「尚未测量」与「读取失败」不是同一件事", async () => {
    renderPanel({ body: clock({ health: "unknown" }) })
    expect(await screen.findByText(UNMEASURED)).toBeTruthy()
    expect(screen.queryByText(UNREADABLE)).toBeNull()
  })
})

/* -------------------------------------------------------------------------- */

describe("摄像机时钟 · 有读数时照实显示", () => {
  it("偏差带符号，不确定度与往返延迟各自成行", async () => {
    renderPanel({
      body: clock({
        health: "healthy",
        quality: "good",
        measured_at: MEASURED_AT,
        offset_ms: 120,
        uncertainty_ms: 15,
        rtt_ms: 30,
        device_timezone: "Asia/Shanghai",
        device_time_source: "manual",
      }),
    })

    expect(await screen.findByText("+120 ms")).toBeTruthy()
    expect(within(row("不确定度")).getByText("15 ms")).toBeTruthy()
    expect(within(row("往返延迟")).getByText("30 ms")).toBeTruthy()
    expect(within(row("设备时区")).getByText("Asia/Shanghai")).toBeTruthy()
    expect(within(row("设备时间来源")).getByText("manual")).toBeTruthy()
    expect(within(row("测量质量")).getByText("良好")).toBeTruthy()
    // Localized, and not the raw ISO string.
    expect(within(row("测量时间")).getByText(/2026/)).toBeTruthy()
    expect(screen.queryByText(MEASURED_AT)).toBeNull()
  })

  it("负偏差带负号", async () => {
    renderPanel({
      body: clock({ health: "warning", quality: "degraded", measured_at: MEASURED_AT, offset_ms: -250 }),
    })

    expect(await screen.findByText("-250 ms")).toBeTruthy()
    // 「偏差或延迟偏大」来自 health=warning，不是因为 -250 越过了某个阈值。
    expect(screen.getByText("偏差或延迟偏大")).toBeTruthy()
    expect(within(row("测量质量")).getByText("下降")).toBeTruthy()
  })

  it("不确定度或延迟缺失时写「—」，不编一个数字", async () => {
    renderPanel({
      body: clock({ health: "healthy", measured_at: MEASURED_AT, offset_ms: 0 }),
    })

    expect(await screen.findByText("+0 ms")).toBeTruthy()
    expect(within(row("不确定度")).getByText("—")).toBeTruthy()
    expect(within(row("往返延迟")).getByText("—")).toBeTruthy()
    expect(within(row("设备时区")).getByText("—")).toBeTruthy()
  })
})

/* -------------------------------------------------------------------------- */

describe("摄像机时钟 · 健康判定只看 health", () => {
  it("health=healthy 时，偏差再大也不改判", async () => {
    renderPanel({
      body: clock({
        health: "healthy",
        quality: "good",
        measured_at: MEASURED_AT,
        offset_ms: 45_000,
        uncertainty_ms: 20,
        rtt_ms: 25,
      }),
    })

    // 数字照实显示……
    expect(await screen.findByText("+45000 ms")).toBeTruthy()
    // ……但结论仍是 healthy。Vue 的 `health === "healthy" || |offset| < 200`
    // （CamerasView.vue:488-496）在这里恰好也判正常，可它靠的是第一个分支，
    // 一旦 offset 小于 200 它就会把 critical 也判成正常。
    expect(screen.getByText("正常")).toBeTruthy()
    expect(screen.queryByText("偏差或延迟偏大")).toBeNull()
    expect(screen.queryByText("严重偏差")).toBeNull()
  })

  it("health=critical 时，偏差再小也不改判", async () => {
    renderPanel({
      body: clock({
        health: "critical",
        quality: "poor",
        measured_at: MEASURED_AT,
        offset_ms: -12,
        uncertainty_ms: 2,
        rtt_ms: 3,
      }),
    })

    expect(await screen.findByText("-12 ms")).toBeTruthy()
    // 反向的覆盖：Vue 这里是 `|offset| < 200` 命中，判「正常」。
    expect(screen.getByText("严重偏差")).toBeTruthy()
    expect(screen.queryByText("正常")).toBeNull()
    expect(screen.queryByText("偏差或延迟偏大")).toBeNull()
  })

  it("quality 是独立字段，不因为 health 正常就变成良好以外的样子", async () => {
    renderPanel({
      body: clock({
        health: "healthy",
        quality: "degraded",
        measured_at: MEASURED_AT,
        offset_ms: 8,
      }),
    })

    expect(await screen.findByText("正常")).toBeTruthy()
    expect(within(row("测量质量")).getByText("下降")).toBeTruthy()
  })
})

/* -------------------------------------------------------------------------- */

describe("摄像机时钟 · 错误码、加载中与失败", () => {
  it("error_code 有值才显示", async () => {
    renderPanel({
      body: clock({
        health: "critical",
        measured_at: MEASURED_AT,
        error_code: "camera_ntp_verify_mode_mismatch",
      }),
    })

    // 有 offset 的失败也会带 error_code（system/api.py:1409-1414）。
    expect(await screen.findByText("读取设备时钟失败")).toBeTruthy()
    expect(within(row("错误码")).getByText("camera_ntp_verify_mode_mismatch")).toBeTruthy()
  })

  it("没有 error_code 时不留一行空位", async () => {
    renderPanel({
      body: clock({
        health: "healthy",
        quality: "good",
        measured_at: MEASURED_AT,
        offset_ms: 5,
      }),
    })

    expect(await screen.findByText("+5 ms")).toBeTruthy()
    expect(screen.queryByText("错误码")).toBeNull()
  })

  it("加载中说的是「读取中…」", () => {
    renderPanel({ pending: true })

    expect(screen.getByText("读取中…")).toBeTruthy()
    // 还没有数据时不能提前给出任何一种结论。
    for (const title of NO_DRIFT_TITLES) {
      expect(screen.queryByText(title)).toBeNull()
    }
  })

  it("读失败时说清是哪里坏了，而不是当成「没有漂移数据」", async () => {
    renderPanel({
      body: { error: { code: "boom", message: "时钟服务未就绪" } },
      status: 503,
    })

    expect(await screen.findByText("无法读取摄像机时钟")).toBeTruthy()
    await waitFor(() => {
      expect(screen.getByText("时钟服务未就绪")).toBeTruthy()
    })
    for (const title of NO_DRIFT_TITLES) {
      expect(screen.queryByText(title)).toBeNull()
    }
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})
