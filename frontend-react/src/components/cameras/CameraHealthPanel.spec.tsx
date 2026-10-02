import { QueryClient } from "@tanstack/react-query"
import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { CameraHealthPanel, HEALTH_STATE_COLOR } from "./CameraHealthPanel"
import { renderWithProviders } from "../../test-utils"
import {
  HEALTH_LAYER_LABEL,
  HEALTH_LAYER_ORDER,
  HEALTH_STATE_LABEL,
  type CameraCapabilityHealth,
  type CameraHealthLayer,
  type HealthState,
} from "../../api/cameras"

/**
 * 这份测试里最重要的一条不是「六个层都画出来了」，而是：
 *
 * **`control` / `ptz` / `clock` 停在 unknown 时，界面必须说「该层不采集实时观测」。**
 *
 * 后端的能力健康投影只能从已存的配置事实推导状态，证明不了实时的媒体/录制运行时
 * 健康（`cameras/capability_health.py:45-49`），而这三个层的投影函数里**没有 healthy
 * 分支**。所以它们卡在 unknown 不是「还在观察」，是一个永远不会被消除的状态。一个
 * 只把它画成灰色「未知」的界面，恰好在这里骗人 —— 它暗示后端还在收集证据，而
 * 后端根本不会收集。`media` 的 unknown 则相反，确实可能变成正常，所以不能带这句。
 */

const CAMERA_ID = "c1"
const UNPROVABLE_NOTE = /该层不采集实时观测/

function layer(
  state: HealthState,
  reason: string | null = null,
  details: Record<string, unknown> = {},
): CameraHealthLayer {
  return { state, reason, details }
}

/** Every layer waiting on something — the shape a fresh camera actually has. */
function healthOf(overrides: Partial<CameraCapabilityHealth> = {}): CameraCapabilityHealth {
  return {
    camera_id: CAMERA_ID,
    control: layer("unknown", "awaiting_control_observation"),
    media: layer("unknown", "awaiting_media_observation"),
    recording: layer("unknown", "awaiting_recording_observation"),
    events: layer("unknown", "event_subscription_unobserved"),
    ptz: layer("unknown", "awaiting_ptz_observation"),
    clock: layer("unknown", "clock_not_measured"),
    ...overrides,
  }
}

/** Not named `Response`: that would shadow the global the fetch stub builds. */
type HealthResponse =
  | CameraCapabilityHealth
  | { status: number; code: string; message: string }

let response: HealthResponse | null = null
let requests: string[] = []

afterEach(() => {
  response = null
  requests = []
  vi.unstubAllGlobals()
})

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

/**
 * `pending` never settles the request: a resolved promise settles inside the same
 * act() as the render, so the loading branch would be gone before any assertion
 * could read it.
 */
function renderPanel(
  source: HealthResponse | "pending",
  enabled = true,
) {
  if (source !== "pending") response = source

  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      requests.push(url)
      if (source === "pending") return new Promise<never>(() => {})
      if (response && "status" in response) {
        return json(
          { error: { code: response.code, message: response.message } },
          response.status,
        )
      }
      return json(response)
    }),
  )

  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })

  return renderWithProviders(
    <CameraHealthPanel cameraId={CAMERA_ID} enabled={enabled} />,
    { client },
  )
}

async function renderLoaded(health: CameraCapabilityHealth, enabled = true) {
  renderPanel(health, enabled)
  await screen.findByText("能力健康")
}

function layerRow(label: string) {
  return screen.getByRole("group", { name: `健康层 ${label}` })
}

function healthRequests() {
  return requests.filter((url) => url.includes("/health"))
}

/* -------------------------------------------------------------------------- */

describe("能力健康 · 六个层与顺序", () => {
  it("六个层全部渲染，顺序按 HEALTH_LAYER_ORDER", async () => {
    await renderLoaded(healthOf())

    expect(screen.getAllByRole("group")).toHaveLength(HEALTH_LAYER_ORDER.length)
    expect(screen.getAllByRole("group").map((node) => node.getAttribute("aria-label"))).toEqual(
      HEALTH_LAYER_ORDER.map((key) => `健康层 ${HEALTH_LAYER_LABEL[key]}`),
    )
  })

  it("显示顺序是契约里的分诊顺序，不是对象的键顺序", async () => {
    await renderLoaded(healthOf())

    const labels = screen
      .getAllByRole("group")
      .map((node) => node.getAttribute("aria-label"))
    // `clock` 排最后、`control` 排最前；payload 里的字段顺序是相反的。
    expect(labels?.[0]).toBe("健康层 控制")
    expect(labels?.[labels.length - 1]).toBe("健康层 时钟")
  })

  it("只读 /cameras/{id}/health 这一个端点", async () => {
    await renderLoaded(healthOf())
    expect(healthRequests()).toHaveLength(1)
  })
})

/* -------------------------------------------------------------------------- */

describe("能力健康 · 状态翻译与颜色", () => {
  it("六种 HealthState 各自渲染出文案，颜色也落在元素上", async () => {
    await renderLoaded({
      camera_id: CAMERA_ID,
      control: layer("unsupported", "onvif_control_not_supported"),
      media: layer("degraded", "bound_stream_unavailable"),
      recording: layer("critical", "recording_media_offline"),
      events: layer("healthy"),
      ptz: layer("disabled", "camera_disabled"),
      clock: layer("unknown", "clock_not_measured"),
    })

    const cases: [string, HealthState][] = [
      ["控制", "unsupported"],
      ["媒体", "degraded"],
      ["录制", "critical"],
      ["事件", "healthy"],
      ["云台", "disabled"],
      ["时钟", "unknown"],
    ]

    for (const [label, state] of cases) {
      const badge = within(layerRow(label)).getByText(HEALTH_STATE_LABEL[state])
      expect(badge.className).toContain(HEALTH_STATE_COLOR[state])
    }
  })

  it("unknown 不和 unsupported / disabled 共用灰色", () => {
    // 「后端没有证据」和「这个设备没有这个能力」是两件事，画成同一个颜色等于
    // 把它们说成一件事。绿 / 黄 / 红 / 中性 / 灰 / 灰的分工锁在这里。
    expect(HEALTH_STATE_COLOR.healthy).toBe("text-status-online")
    expect(HEALTH_STATE_COLOR.degraded).toBe("text-status-degraded")
    expect(HEALTH_STATE_COLOR.critical).toBe("text-status-offline")
    expect(HEALTH_STATE_COLOR.unknown).toBe("text-status-unknown")
    expect(HEALTH_STATE_COLOR.unsupported).toBe("text-muted-foreground")
    expect(HEALTH_STATE_COLOR.disabled).toBe("text-muted-foreground")
    expect(HEALTH_STATE_COLOR.unknown).not.toBe(HEALTH_STATE_COLOR.unsupported)
  })
})

/* -------------------------------------------------------------------------- */

describe("能力健康 · reason 原样透传", () => {
  it("已收录的 reason 走翻译", async () => {
    await renderLoaded(healthOf({ ptz: layer("unsupported", "ptz_not_supported") }))
    expect(within(layerRow("云台")).getByText("设备不支持云台")).toBeTruthy()
  })

  it("未收录的 reason 原样显示，不被吞掉", async () => {
    await renderLoaded(healthOf({ media: layer("unknown", "awaiting_quantum_observation") }))
    // 新的 reason 是信息：它说明后端进入了一个前端还不知道的状态。
    expect(within(layerRow("媒体")).getByText("awaiting_quantum_observation")).toBeTruthy()
  })

  it("没有 reason 时不画空行", async () => {
    await renderLoaded(healthOf({ media: layer("healthy", null) }))
    // 既没有「—」也没有占位符：这一行只有层名和状态。
    expect(layerRow("媒体").textContent).toBe("媒体正常")
  })
})

/* -------------------------------------------------------------------------- */

describe("能力健康 · details 是开放字典", () => {
  it("键值原样渲染，不按固定键名解构", async () => {
    await renderLoaded(
      healthOf({
        media: layer("degraded", "bound_stream_unavailable", {
          purposes: ["RECORD", "LIVE_HIGH"],
          // 这个键不在任何词表里；出现时必须照样画出来，而不是被忽略。
          zlm_track_count: 0,
        }),
      }),
    )

    const media = layerRow("媒体")
    expect(within(media).getByText("purposes")).toBeTruthy()
    expect(within(media).getByText("RECORD、LIVE_HIGH")).toBeTruthy()
    expect(within(media).getByText("zlm_track_count")).toBeTruthy()
  })

  it("值为 null / undefined / 空数组 / 空对象 / 空串时不产生噪音行", async () => {
    await renderLoaded(
      healthOf({
        recording: layer("unknown", "awaiting_recording_observation", {
          a: null,
          b: undefined,
          c: [],
          d: {},
          e: "   ",
          f: "",
        }),
      }),
    )

    const recording = layerRow("录制")
    for (const key of ["a", "b", "c", "d", "e", "f"]) {
      expect(within(recording).queryByText(key)).toBeNull()
    }
    // 一个 key 都没剩下来：没有「无」，没有「—」，也没有一排空行。
    expect(recording.textContent).toBe("录制未知尚未观察到录制层状态")
  })

  it("数字、布尔和嵌套对象都给出可读文本", async () => {
    await renderLoaded(
      healthOf({
        clock: layer("degraded", "clock_not_measured", {
          offset_ms: 0,
          measured: false,
          source: { tz: "UTC", ntp: true },
        }),
      }),
    )

    const clock = layerRow("时钟")
    expect(within(clock).getByText("0")).toBeTruthy()
    expect(within(clock).getByText("false")).toBeTruthy()
    expect(within(clock).getByText("tz=UTC，ntp=true")).toBeTruthy()
  })
})

/* -------------------------------------------------------------------------- */

describe("能力健康 · 不谎报：无法证明正常就说无法证明", () => {
  it("control / ptz / clock 处于 unknown 时说明它不采集实时观测", async () => {
    await renderLoaded(healthOf())

    for (const label of ["控制", "云台", "时钟"]) {
      expect(within(layerRow(label)).getByText(UNPROVABLE_NOTE)).toBeTruthy()
    }
  })

  it("media / recording / events 的 unknown 不带这句话", async () => {
    await renderLoaded(healthOf())

    // 这三层在 HEALTHY_POSSIBLE_LAYERS 里，unknown 确实可能变成正常；把
    // 「永远不会正常」的话说给它们听是另一种撒谎。
    for (const label of ["媒体", "录制", "事件"]) {
      expect(within(layerRow(label)).queryByText(UNPROVABLE_NOTE)).toBeNull()
    }
    expect(screen.getAllByText(UNPROVABLE_NOTE)).toHaveLength(3)
  })

  it("这三层不在 unknown 时不说这句", async () => {
    await renderLoaded(
      healthOf({
        control: layer("unsupported", "onvif_control_not_supported"),
        ptz: layer("unsupported", "ptz_not_supported"),
        clock: layer("unsupported", "device_clock_not_supported"),
      }),
    )

    // 「不支持」是后端能证明的事实，reason 已经说清楚了，不需要再补观测说明。
    expect(screen.queryAllByText(UNPROVABLE_NOTE)).toHaveLength(0)
  })

  it("同一个未知的 reason 落在非 unknown 状态上也不触发说明", async () => {
    await renderLoaded(
      healthOf({ control: layer("degraded", "awaiting_control_observation") }),
    )
    expect(within(layerRow("控制")).queryByText(UNPROVABLE_NOTE)).toBeNull()
  })
})

/* -------------------------------------------------------------------------- */

describe("能力健康 · 加载与失败", () => {
  it("请求在飞时显示读取中，且不画任何层", () => {
    renderPanel("pending")

    expect(screen.getByText("读取中…")).toBeTruthy()
    expect(screen.queryByRole("group")).toBeNull()
  })

  it("读取失败给出错误 Callout，不退化成「六层全部未知」", async () => {
    renderPanel({ status: 403, code: "forbidden", message: "缺少 camera.read 权限" })

    expect(await screen.findByText("无法读取能力健康")).toBeTruthy()
    expect(screen.getByText("缺少 camera.read 权限")).toBeTruthy()
    // 这是本次最需要守住的分界：没读到 ≠ 后端说不知道。
    expect(screen.queryAllByText("未知")).toHaveLength(0)
    expect(screen.queryByRole("group")).toBeNull()
  })

  it("失败后可以重试", async () => {
    renderPanel({ status: 500, code: "internal", message: "服务端异常" })
    await screen.findByText("无法读取能力健康")

    response = healthOf()
    fireEvent.click(screen.getByRole("button", { name: "重试" }))

    await waitFor(() => {
      expect(screen.getByText("能力健康")).toBeTruthy()
    })
    expect(healthRequests().length).toBeGreaterThan(1)
  })
})

/* -------------------------------------------------------------------------- */

describe("能力健康 · 通道停用不是错误", () => {
  it("enabled=false 时仍然读接口，并如实显示 disabled + camera_disabled", async () => {
    await renderLoaded(
      healthOf({
        control: layer("disabled", "camera_disabled"),
        media: layer("disabled", "camera_disabled"),
        recording: layer("disabled", "camera_disabled"),
        events: layer("disabled", "camera_disabled"),
        ptz: layer("disabled", "camera_disabled"),
        clock: layer("disabled", "camera_disabled"),
      }),
      false,
    )

    // 停用时后端报的是一串有意义的 disabled 事实（`capability_health.py:74-87`）。
    // 关掉这个请求等于把一个状态换成空白。
    expect(healthRequests()).toHaveLength(1)
    expect(screen.getAllByText("已停用").length).toBeGreaterThan(0)
    expect(screen.getAllByText("通道已停用").length).toBeGreaterThan(0)
  })

  it("停用不额外加错误横幅", async () => {
    await renderLoaded(healthOf({ clock: layer("disabled", "camera_disabled") }), false)

    expect(screen.getByText("该通道已停用")).toBeTruthy()
    expect(screen.queryByText("无法读取能力健康")).toBeNull()
    expect(screen.queryByText("读取中…")).toBeNull()
  })

  it("enabled=true 时不出现停用说明", async () => {
    await renderLoaded(healthOf(), true)
    expect(screen.queryByText("该通道已停用")).toBeNull()
  })
})
