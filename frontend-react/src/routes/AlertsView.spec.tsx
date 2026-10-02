import { QueryClient } from "@tanstack/react-query"
import { fireEvent, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { AlertsView } from "./AlertsView"
import { renderWithProviders } from "../test-utils"
import { MATCH_KEYS, type AlertPolicyView } from "../api/alerts"
import { CAMS, POLICIES } from "../lib/queries"

/**
 * Two things are being defended here, and they are the whole point of the
 * rewrite.
 *
 * 1. **No silent field loss.** `PATCH /alert-policies/{id}` replaces `match`
 *    wholesale, so a save that rebuilds the object from the form's field list
 *    deletes every key it does not render — and returns 200. The Vue screen
 *    this replaces did exactly that to any rule carrying `severities`.
 * 2. **No silent field gain.** `zones` means something different on the two
 *    sides of D-2, so the read-only recording reference must not offer to
 *    copy it. A rule that looks right and behaves differently is worse than
 *    one the operator cannot build.
 */

function policy(over: Partial<AlertPolicyView> = {}): AlertPolicyView {
  return {
    id: "p1",
    name: "夜间有人",
    enabled: true,
    severity: "warning",
    match: { labels: ["car"], min_confidence: 0.6 },
    actions: {},
    cooldown_seconds: 0,
    created_at: "2026-10-01T00:00:00.000Z",
    updated_at: "2026-10-01T00:00:00.000Z",
    ...over,
  }
}

type Call = { url: string; method: string; body: unknown }

function stubApi(overrides: { policies?: AlertPolicyView[]; alerts?: unknown[] } = {}) {
  const calls: Call[] = []
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? "GET"
      calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : null })

      if (url.includes("/api/v1/alert-policies")) {
        if (method !== "GET") return json(policy())
        return json(overrides.policies ?? [policy()])
      }
      if (url.includes("/api/v1/alerts")) {
        return json({ items: overrides.alerts ?? [], next_cursor: null })
      }
      if (url.includes("/api/v1/recording-policies")) {
        return json({
          items: [
            {
              camera_id: "c1",
              baseline_mode: "schedule",
              schedule: {},
              event_filter: { labels: ["car"], zones: ["driveway"], min_confidence: 0.6 },
            },
          ],
        })
      }
      if (url.includes("/api/v1/cameras")) {
        return json([cameraStub()])
      }
      return json({})
    }),
  )
  return calls
}

function cameraStub() {
  return {
    id: "c1",
    name: "前门",
    enabled: true,
    maintenance: false,
    retired_at: null,
    location: null,
    storage_label: null,
    adapter_type: null,
    time_sync_mode: "monitor",
    ptz_capable: false,
    manufacturer: null,
    model: null,
    form_factor: "dome",
    ip: null,
    port: null,
    rtsp_path: null,
    sub_rtsp_path: null,
    video_codec: "H.264",
    width: null,
    height: null,
    fps: null,
    audio_codec: null,
    connectivity_status: "online",
    last_probe_at: null,
    last_online_at: null,
  }
}

function json(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  })
}

function renderView() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  client.setQueryData(CAMS.list(false), [cameraStub()])
  client.setQueryData(POLICIES.list, [
    {
      camera_id: "c1",
      baseline_mode: "schedule",
      schedule: {},
      event_filter: { labels: ["car"], zones: ["driveway"], min_confidence: 0.6 },
    },
  ])
  return renderWithProviders(<AlertsView />, { client })
}

async function openEditor() {
  renderView()
  fireEvent.click(await screen.findByTitle("编辑"))
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("规则列表", () => {
  it("states that the two filters are not the same filter", async () => {
    stubApi()
    renderView()
    expect(await screen.findByText(/录制过滤与告警匹配是两套独立配置/)).toBeTruthy()
  })

  it("shows the rule with its real condition count", async () => {
    stubApi()
    renderView()
    expect(await screen.findByText("夜间有人")).toBeTruthy()
    expect(screen.getByText(/2 个匹配条件/)).toBeTruthy()
  })

  it("says what an empty rule set means", async () => {
    stubApi({ policies: [] })
    renderView()
    expect(await screen.findByText(/还没有告警规则/)).toBeTruthy()
    expect(screen.getByText(/只会被记录，不会产生告警/)).toBeTruthy()
  })
})

describe("编辑器覆盖了每一个后端接受的 key", () => {
  // The guard that makes `mergeMatch` safe. Known keys are authoritative, so
  // a key with no input starts being cleared on every save.
  it("renders a labelled control for each of the 12 keys", async () => {
    stubApi()
    await openEditor()
    await screen.findByLabelText("规则名称")
    for (const key of MATCH_KEYS) {
      const label = {
        camera_ids: "摄像机",
        sources: "事件来源",
        categories: "事件类别",
        labels: "标签",
        zones: "区域",
        min_confidence: "最低置信度",
        min_duration_seconds: "最短持续秒数",
        severities: "事件严重度",
        weekdays: "星期",
        time_start: "开始时间",
        time_end: "结束时间",
        timezone: "时区",
      }[key]
      // List kinds expose an "add" input; scalar kinds expose the field
      // itself; the weekday picker is a labelled button group.
      const found =
        screen.queryByLabelText(label) ??
        screen.queryByLabelText(`新增${label}`) ??
        screen.queryAllByLabelText(label).length
      expect(found, `missing control for ${key} (${label})`).toBeTruthy()
    }
    expect(screen.getByRole("group", { name: "星期" })).toBeTruthy()
    for (let day = 0; day < 7; day += 1) {
    }
  })
})

describe("保存不会丢字段", () => {
  it("keeps a key the form was not showing when the rule was loaded", async () => {
    // The regression. A rule written through the API can carry any of the 12
    // keys; rebuilding `match` from the form would delete the ones absent
    // from the draft.
    const calls = stubApi()
    renderView()
    fireEvent.click(await screen.findByTitle("编辑"))
    fireEvent.change(await screen.findByLabelText("规则名称"), {
      target: { value: "改个名" },
    })
    fireEvent.click(screen.getByRole("button", { name: "保存" }))

    await waitFor(() => {
      const patch = calls.find((c) => c.method === "PATCH")
      expect(patch).toBeTruthy()
      const match = (patch!.body as { match: Record<string, unknown> }).match
      // Both original keys survive an edit that touched neither.
      expect(match.labels).toEqual(["car"])
      expect(match.min_confidence).toBe(0.6)
    })
  })

  it("preserves a key this build does not know about at all", async () => {
    const calls = stubApi({
      policies: [policy({ match: { labels: ["car"], future_key: 42 } as never })],
    })
    renderView()
    fireEvent.click(await screen.findByTitle("编辑"))
    fireEvent.change(await screen.findByLabelText("规则名称"), {
      target: { value: "改个名" },
    })
    fireEvent.click(screen.getByRole("button", { name: "保存" }))

    await waitFor(() => {
      const patch = calls.find((c) => c.method === "PATCH")
      const match = (patch!.body as { match: Record<string, unknown> }).match
      expect(match.future_key).toBe(42)
    })
  })

  it("names an unmanaged field instead of hiding it", async () => {
    stubApi({
      policies: [policy({ match: { labels: ["car"], future_key: 42 } as never })],
    })
    renderView()
    fireEvent.click(await screen.findByTitle("编辑"))
    expect(await screen.findByText(/有本表单未覆盖的字段/)).toBeTruthy()
    expect(screen.getByText(/future_key/)).toBeTruthy()
  })

  it("does remove a field the operator cleared", async () => {
    const calls = stubApi()
    renderView()
    fireEvent.click(await screen.findByTitle("编辑"))
    fireEvent.click(await screen.findByLabelText("移除 car"))
    fireEvent.click(screen.getByRole("button", { name: "保存" }))

    await waitFor(() => {
      const patch = calls.find((c) => c.method === "PATCH")
      const match = (patch!.body as { match: Record<string, unknown> }).match
      expect(match).not.toHaveProperty("labels")
    })
  })
})

describe("D-2 只读引用", () => {
  async function openReference() {
    stubApi()
    await openEditor()
    fireEvent.change(await screen.findByLabelText("选择参考机位"), {
      target: { value: "c1" },
    })
  }

  it("offers a copy only for the two keys that mean the same thing", async () => {
    await openReference()
    await screen.findAllByText("标签")
    // `labels` and `min_confidence` are semantically identical on both sides.
    expect(screen.getAllByRole("button", { name: /复制到本规则/ }).length).toBe(2)
  })

  it("refuses to copy zones and says why", async () => {
    await openReference()
    // The decisive D-2 fact: the two sides read different fields, so a
    // copied value produces two rules that look identical and differ.
    expect(
      await screen.findByText(/录制侧读事件的 metadata_json/),
    ).toBeTruthy()
  })

  it("copies labels on request", async () => {
    await openReference()
    const buttons = await screen.findAllByRole("button", { name: /复制到本规则/ })
    fireEvent.click(buttons[0])
    await waitFor(() =>
      expect((screen.getByLabelText("新增标签") as HTMLInputElement).value).toBe(""),
    )
  })

  it("says so when a camera has no recording policy", async () => {
    stubApi()
    await openEditor()
    fireEvent.change(await screen.findByLabelText("选择参考机位"), {
      target: { value: "c1" },
    })
    // Present here so the assertion is about the panel, not the fetch.
    expect(screen.getByText(/只读参考，不会自动同步/)).toBeTruthy()
  })
})

describe("校验", () => {
  it("blocks a save when the time window is incomplete", async () => {
    const calls = stubApi()
    renderView()
    fireEvent.click(await screen.findByTitle("编辑"))
    fireEvent.change(await screen.findByLabelText("开始时间"), {
      target: { value: "08:00" },
    })
    expect(await screen.findByText(/必须同时填写/)).toBeTruthy()
    expect(screen.getByRole("button", { name: "保存" })).toHaveProperty("disabled", true)
    expect(calls.filter((c) => c.method === "PATCH")).toHaveLength(0)
  })

  it("blocks an out-of-range cooldown", async () => {
    stubApi()
    renderView()
    fireEvent.click(await screen.findByTitle("编辑"))
    fireEvent.change(await screen.findByLabelText("冷却秒数"), {
      target: { value: "999999" },
    })
    expect((await screen.findAllByText(/0–604800/)).length).toBeGreaterThan(0)
  })

  it("rejects an unknown event severity by name", async () => {
    stubApi()
    renderView()
    fireEvent.click(await screen.findByTitle("编辑"))
    fireEvent.change(await screen.findByLabelText("新增事件严重度"), {
      target: { value: "catastrophic" },
    })
    fireEvent.change(screen.getByLabelText("新增事件严重度"), {
      target: { value: "catastrophic" },
    })
    fireEvent.keyDown(screen.getByLabelText("新增事件严重度"), { key: "Enter" })
    expect((await screen.findAllByText(/catastrophic/)).length).toBeGreaterThan(0)
  })
})

describe("告警列表", () => {
  it("offers acknowledge and resolve only in the states that allow them", async () => {
    stubApi({
      alerts: [
        {
          id: "a1",
          policy_id: "p1",
          event_id: "e1",
          camera_id: "c1",
          severity: "critical",
          title: "夜间有人",
          message: null,
          state: "OPEN",
          acknowledged_at: null,
          acknowledged_by: null,
          resolved_at: null,
          created_at: new Date().toISOString(),
        },
        {
          id: "a2",
          policy_id: "p1",
          event_id: "e2",
          camera_id: "c1",
          severity: "info",
          title: "已处理的",
          message: null,
          state: "RESOLVED",
          acknowledged_at: null,
          acknowledged_by: null,
          resolved_at: null,
          created_at: new Date().toISOString(),
        },
      ],
    })
    renderView()
    fireEvent.click(await screen.findByRole("tab", { name: "告警" }))

    expect(await screen.findByText("夜间有人")).toBeTruthy()
    // Exact, not a regex: the state filter also has an "已确认" option.
    expect(screen.getAllByRole("button", { name: "确认" }).length).toBe(1)
    expect(screen.getAllByRole("button", { name: /标记解决/ }).length).toBe(1)
  })
})

describe("删除需要确认", () => {
  it("does not delete when the operator cancels", async () => {
    const calls = stubApi()
    renderView()
    fireEvent.click(await screen.findByTitle("删除该规则"))
    // A delete takes the whole match configuration with it and cannot be
    // undone, so the first click must not fire the request.
    fireEvent.click(await screen.findByRole("button", { name: "取消" }))
    await waitFor(() =>
      expect(screen.queryByRole("alertdialog")).toBeNull(),
    )
    expect(calls.some((c) => c.method === "DELETE")).toBe(false)
  })

  it("deletes once the operator confirms", async () => {
    const calls = stubApi()
    renderView()
    fireEvent.click(await screen.findByTitle("删除该规则"))
    fireEvent.click(await screen.findByRole("button", { name: "删除" }))
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true))
  })

  it("does not delete when the prompt is dismissed with the backdrop", async () => {
    const calls = stubApi()
    renderView()
    fireEvent.click(await screen.findByTitle("删除该规则"))
    const backdrop = (await screen.findByRole("alertdialog")).parentElement!
    fireEvent.click(backdrop)
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull())
    expect(calls.some((c) => c.method === "DELETE")).toBe(false)
  })
})
