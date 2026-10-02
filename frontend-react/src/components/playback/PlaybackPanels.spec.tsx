import { QueryClient } from "@tanstack/react-query"
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { PlaybackActionPanel } from "./PlaybackActionPanel"
import { PlaybackDiagnosticsPanel } from "./PlaybackDiagnosticsPanel"
import { renderWithProviders } from "../../test-utils"
import { FILES, POLICIES, RECORDINGS } from "../../lib/queries"
import type { RecordingTriggerView } from "../../api/recordingTriggers"
import type { RecordingProtectionView } from "../../api/protections"
import type { ExportView } from "../../api/exports"
import type { RecordingPolicyView, RecordingRuntime } from "../../api/recordingPolicies"

/**
 * The two playback panels, tested against the traps their contracts document.
 *
 * Both panels exist because of write paths that fail in ways a status code
 * cannot express: a trigger that keeps recording until someone ends it, a
 * protection that silently stops retention from cleaning anything, and a
 * runtime whose `null` means "nobody could look" rather than "nothing is
 * happening". So most of what is asserted below is a *statement about what the
 * panel refuses to say* — a 409 discovered by clicking, a millisecond-scaled
 * pre-roll, an empty range for an open-ended trigger, or an unobservable
 * camera drawn as an offline one.
 */

const CAMERA = "cam-1"

/* -------------------------------------------------------------------------- */
/* Fixtures                                                                   */
/* -------------------------------------------------------------------------- */

function trigger(over: Partial<RecordingTriggerView> = {}): RecordingTriggerView {
  return {
    id: "trig-1",
    camera_id: CAMERA,
    type: "MANUAL",
    source: "api",
    requested_at: "2026-10-01T09:00:00Z",
    pre_roll_seconds: 10,
    post_roll_seconds: 30,
    pre_roll_status: "degraded",
    pre_roll_available_seconds: 4.5,
    planned_start_at: "2026-10-01T08:59:50Z",
    planned_end_at: null,
    state: "ACTIVE",
    reason: "现场调试",
    correlation_id: "corr-1",
    ...over,
  }
}

function protection(over: Partial<RecordingProtectionView> = {}): RecordingProtectionView {
  return {
    id: "prot-1",
    camera_id: CAMERA,
    started_at: "2026-10-01T09:00:00Z",
    ended_at: "2026-10-01T10:00:00Z",
    reason: "误删排查",
    created_by: "alice",
    expires_at: null,
    created_at: "2026-10-01T08:59:00Z",
    updated_at: "2026-10-01T08:59:00Z",
    ...over,
  }
}

function runtime(over: Partial<RecordingRuntime> = {}): RecordingRuntime {
  return {
    desired_mode: "prebuffer",
    recording: true,
    stream_online: true,
    changed: false,
    assumed_existing_mode: false,
    observed_at: "2026-10-01T09:00:00Z",
    blockers: [],
    ...over,
  }
}

function policy(over: Partial<RecordingPolicyView> = {}): RecordingPolicyView {
  return {
    id: "pol-1",
    camera_id: CAMERA,
    baseline_mode: "schedule",
    schedule: {},
    schedule_timezone: null,
    event_recording_enabled: true,
    event_filter: {},
    segment_target_seconds: 300,
    pre_roll_seconds: 10,
    post_roll_seconds: 30,
    storage_target_id: null,
    retention_policy_id: null,
    enabled: true,
    runtime: null,
    ...over,
  }
}

function exportJob(over: Partial<ExportView> = {}): ExportView {
  return {
    id: "exp-1",
    camera_id: CAMERA,
    requested_by: "alice",
    start_at: "2026-10-01T09:00:00Z",
    end_at: "2026-10-01T09:30:00Z",
    requested_duration_ms: 1_800_000,
    format: "mp4",
    codec_mode: "auto",
    gap_policy: "skip",
    state: "COMPLETED",
    size_bytes: 1024,
    actual_duration_ms: 1_790_000,
    selected_segment_count: 6,
    metadata: {},
    error_code: null,
    expires_at: "2026-10-08T09:00:00Z",
    started_at: "2026-10-01T09:00:05Z",
    completed_at: "2026-10-01T09:00:20Z",
    created_at: "2026-10-01T09:00:01Z",
    ...over,
  }
}

/* -------------------------------------------------------------------------- */
/* Harness                                                                    */
/* -------------------------------------------------------------------------- */

type Call = {
  method: string
  url: string
  body: unknown
  headers: Record<string, string>
}

type WriteFailure = {
  status: number
  code: string
  message: string
  details?: Record<string, unknown> | null
}

let calls: Call[] = []
/** Set by a test to make the next write fail with a specific backend envelope. */
let failure: WriteFailure | null = null
/** Held open by a test that needs a write to still be in flight. */
let hold: Promise<void> | null = null

afterEach(() => {
  calls = []
  failure = null
  hold = null
  vi.unstubAllGlobals()
})

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

function headersOf(headers: HeadersInit | undefined): Record<string, string> {
  if (!headers) return {}
  return Object.fromEntries(
    Object.entries(headers as Record<string, string>).map(([key, value]) => [
      key,
      String(value),
    ]),
  )
}

interface Seed {
  triggers?: RecordingTriggerView[]
  protections?: RecordingProtectionView[]
  policies?: RecordingPolicyView[]
  exports?: ExportView[]
}

function renderPanel(seed: Seed = {}) {
  const triggers = seed.triggers ?? []
  const protections = seed.protections ?? []
  const policies = seed.policies ?? [policy()]
  const exports = seed.exports ?? []

  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  client.setQueryData(RECORDINGS.triggers(CAMERA), triggers)
  client.setQueryData(FILES.protections(CAMERA), protections)
  client.setQueryData(POLICIES.list, policies)
  client.setQueryData(FILES.exports(""), {
    pages: [{ items: exports, next_cursor: null }],
    pageParams: [undefined],
  })

  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? "GET"
      calls.push({
        method,
        url,
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
        headers: headersOf(init?.headers),
      })

      if (method !== "GET") {
        if (hold) await hold
        if (failure) {
          return json(
            {
              error: {
                code: failure.code,
                message: failure.message,
                details: failure.details ?? null,
              },
            },
            failure.status,
          )
        }
        if (url.includes("/stop")) {
          return json(trigger({ state: "COMPLETED", planned_end_at: "2026-10-01T09:00:30Z" }))
        }
        if (url.includes("recording-triggers")) return json(trigger())
        if (url.includes("recording-protections")) return json(protection())
        return json({})
      }

      // Refetches after a write land here; the cache is re-seeded with the same
      // fixtures so an assertion is about the request, not about the mock.
      if (url.includes("recording-triggers")) return json(triggers)
      if (url.includes("recording-protections")) return json(protections)
      if (url.includes("recording-policies")) return json({ items: policies })
      if (url.includes("exports")) return json({ items: exports, next_cursor: null })
      return json({})
    }),
  )

  return renderWithProviders(<PlaybackActionPanel cameraId={CAMERA} />, { client })
}

function renderDiagnostics(seed: Seed, children?: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  client.setQueryData(POLICIES.list, seed.policies ?? [])

  vi.stubGlobal(
    "fetch",
    vi.fn(async () => json({ items: seed.policies ?? [] })),
  )

  return renderWithProviders(
    <>
      {children}
      <PlaybackDiagnosticsPanel cameraId={CAMERA} />
    </>,
    { client },
  )
}

function panel() {
  return screen.getByTestId("playback-action-panel")
}

function writeCalls(fragment: string, method?: string) {
  return calls.filter(
    (call) => call.url.includes(fragment) && (!method || call.method === method),
  )
}

function triggerRow(id: string) {
  const list = screen.getByRole("list", { name: "触发记录列表" })
  const row = list.querySelector(`[data-trigger-id="${id}"]`)
  if (!row) throw new Error(`no trigger row for ${id}`)
  return within(row as HTMLElement)
}

function protectionRow(id: string) {
  const list = screen.getByRole("list", { name: "保护区间列表" })
  const row = list.querySelector(`[data-protection-id="${id}"]`)
  if (!row) throw new Error(`no protection row for ${id}`)
  return within(row as HTMLElement)
}

function createButton() {
  return screen.getByRole("button", { name: "触发手动录制" }) as HTMLButtonElement
}

/**
 * The value cell of a definition row, found through its label.
 *
 * A `KeyValue` renders the label and the value as siblings, so this is how a
 * test says "the stream row says X" without matching the same word somewhere
 * else on the panel — `正在录制` is both a verdict message and a cell value.
 */
function valueOf(
  scope: { getByText: (text: string) => HTMLElement },
  label: string,
) {
  return scope.getByText(label).nextElementSibling?.textContent
}

async function confirmDialog() {
  return screen.findByRole("alertdialog")
}

/* -------------------------------------------------------------------------- */
/* Manual trigger                                                              */
/* -------------------------------------------------------------------------- */

describe("回放操作 · 手动触发", () => {
  it("事件录制未开启时按钮禁用并说明原因，不发任何请求", async () => {
    renderPanel({ policies: [policy({ event_recording_enabled: false })] })

    // `policy.enabled` and `policy.event_recording_enabled` must both be true or
    // the POST is a 409 (`triggers.py:79-88`). Saying so on the button is the
    // whole point: the operator should not have to click to learn it.
    expect(createButton().disabled).toBe(true)
    expect(
      panel().textContent,
    ).toContain("该机位只按计划录制（未开启事件录制），无法手动触发。")

    fireEvent.click(createButton())
    expect(writeCalls("recording-triggers", "POST")).toHaveLength(0)
  })

  it("没有配置策略的机位同样不能触发，且不把它说成「正在读取」", async () => {
    renderPanel({ policies: [] })
    expect(createButton().disabled).toBe(true)
    expect(panel().textContent).toContain("该机位没有配置录制策略")
    fireEvent.click(createButton())
    expect(writeCalls("recording-triggers", "POST")).toHaveLength(0)
  })

  it("成功触发带上 body 和 Idempotency-Key 头", async () => {
    renderPanel()
    fireEvent.change(screen.getByLabelText("触发原因"), { target: { value: " 现场调试 " } })
    fireEvent.click(createButton())

    await waitFor(() => {
      expect(writeCalls("recording-triggers", "POST")).toHaveLength(1)
    })
    const sent = writeCalls("recording-triggers", "POST")[0]
    // Trimmed before it leaves: the string is stored on the trigger row and a
    // trailing space is not something to discover in the list later.
    expect(sent.body).toEqual({ reason: "现场调试" })
    // Without this header every call creates a new ACTIVE row
    // (`triggers.py:289-290`).
    expect(sent.headers["Idempotency-Key"]).toMatch(/^manual-cam-1-/)
  })

  it("同一原因重试复用同一个幂等键，换一个原因则换键", async () => {
    failure = { status: 500, code: "internal_error", message: "boom" }
    renderPanel()
    fireEvent.change(screen.getByLabelText("触发原因"), { target: { value: "现场调试" } })

    fireEvent.click(createButton())
    await waitFor(() => expect(writeCalls("recording-triggers", "POST")).toHaveLength(1))
    fireEvent.click(createButton())
    await waitFor(() => expect(writeCalls("recording-triggers", "POST")).toHaveLength(2))

    // A different reason is a different intent, so it must not be deduplicated
    // against the first one.
    fireEvent.change(screen.getByLabelText("触发原因"), { target: { value: "换了个原因" } })
    fireEvent.click(createButton())
    await waitFor(() => expect(writeCalls("recording-triggers", "POST")).toHaveLength(3))

    const keys = writeCalls("recording-triggers", "POST").map(
      (call) => call.headers["Idempotency-Key"],
    )
    expect(keys[0]).toBe(keys[1])
    expect(keys[2]).not.toBe(keys[0])
  })

  it("连点两次只发一次请求——重复触发无法在列表里分辨", async () => {
    let release = () => {}
    hold = new Promise<void>((resolve) => {
      release = resolve
    })
    renderPanel()

    const button = createButton()
    fireEvent.click(button)
    fireEvent.click(button)
    fireEvent.click(button)

    await waitFor(() => expect(writeCalls("recording-triggers", "POST")).toHaveLength(1))
    act(() => release())
    await waitFor(() => expect(createButton().disabled).toBe(false))
    expect(writeCalls("recording-triggers", "POST")).toHaveLength(1)
  })

  it("503 且已落库：说清不要重试，不提供自动重试，也不会自己再发一次", async () => {
    // The row is committed before the enqueue (`api.py:984-993`), so this 503
    // means the trigger exists. A retry would create a second one.
    failure = {
      status: 503,
      code: "recording_task_queue_unavailable",
      message: "queue down",
      details: { trigger_persisted: true, trigger_id: "trig-9" },
    }
    renderPanel()
    fireEvent.click(createButton())

    const callout = await within(panel()).findByText("触发已创建，但任务队列不可用")
    expect(within(panel()).getByText(/请不要重复触发/)).toBeTruthy()
    // The id comes out of `details.trigger_id`, so the operator can find the row
    // the queue will pick up.
    expect(within(panel()).getByText(/记录已经落库（trig-9）/)).toBeTruthy()
    expect(callout).toBeTruthy()

    // Locked, not retried.
    expect(createButton().disabled).toBe(true)
    expect(screen.queryByRole("button", { name: /重试/ })).toBeNull()
    expect(panel().textContent).toContain("上一次触发已经落库")

    await new Promise((resolve) => setTimeout(resolve, 120))
    expect(writeCalls("recording-triggers", "POST")).toHaveLength(1)

    // The only way forward is acknowledging it locally, which sends nothing.
    fireEvent.click(screen.getByRole("button", { name: "我已在列表中核对" }))
    await waitFor(() => expect(createButton().disabled).toBe(false))
    expect(writeCalls("recording-triggers", "POST")).toHaveLength(1)
  })
})

/* -------------------------------------------------------------------------- */
/* Trigger list                                                                */
/* -------------------------------------------------------------------------- */

describe("回放操作 · 触发记录", () => {
  it("开放中的触发和已结束的触发可区分，空的结束时间不是空区间", async () => {
    renderPanel({
      triggers: [
        trigger({ id: "trig-open", state: "ACTIVE", planned_end_at: null }),
        trigger({
          id: "trig-done",
          state: "COMPLETED",
          planned_end_at: "2026-10-01T09:00:30Z",
        }),
      ],
    })
    const list = await screen.findByRole("list", { name: "触发记录列表" })

    expect(triggerRow("trig-open").getByText("进行中")).toBeTruthy()
    // `planned_end_at === null` is an open-ended trigger, not a missing value.
    expect(valueOf(triggerRow("trig-open"), "结束时间")).toBe("开放中（无结束时间）")
    expect(triggerRow("trig-done").getByText("已结束")).toBeTruthy()
    expect(valueOf(triggerRow("trig-done"), "结束时间")).toMatch(/2026/)
    expect(valueOf(triggerRow("trig-done"), "结束时间")).not.toBe("开放中（无结束时间）")
    // No empty or dash-only range is standing in for the end time.
    expect(within(list).queryAllByText(/^—$/)).toHaveLength(0)
  })

  it("列表声明只到最近 100 条，不假装展示全部", async () => {
    renderPanel({ triggers: [trigger()] })
    await screen.findByRole("list", { name: "触发记录列表" })

    // Hard-capped at 100 server-side with no `limit` and no cursor
    // (`triggers.py:51-64`).
    expect(panel().textContent).toContain("只显示最近 100 条")
  })

  it("前录不足按秒报告，数字来自 pre_roll_available_seconds", async () => {
    renderPanel({
      triggers: [
        trigger({
          pre_roll_seconds: 10,
          pre_roll_available_seconds: 4.5,
          pre_roll_status: "degraded",
        }),
      ],
    })
    await screen.findByRole("list", { name: "触发记录列表" })

    // Seconds, not milliseconds. The Vue panel divided by 1000 and called the
    // result milliseconds, which reported a full pre-roll on a camera with
    // none (`recordingTriggers.ts` on `preRollShortfall`).
    expect(
      triggerRow("trig-1").getByText("前录 10 秒，实际可用 4.5 秒，缺 5.5 秒"),
    ).toBeTruthy()
    expect(triggerRow("trig-1").getByText("前录不足")).toBeTruthy()
  })

  it("未知的 state 和 type 照原样渲染，而不是消失", async () => {
    renderPanel({
      triggers: [
        trigger({ state: "PAUSED_BY_OPERATOR", type: "SCHEDULED_BATCH" }),
      ],
    })
    await screen.findByRole("list", { name: "触发记录列表" })

    const row = triggerRow("trig-1")
    expect(row.getByText("PAUSED_BY_OPERATOR")).toBeTruthy()
    expect(row.getByText(/SCHEDULED_BATCH/)).toBeTruthy()
  })

  it("只有可停止的触发才给结束按钮，并说清为什么不能停", async () => {
    renderPanel({
      triggers: [
        trigger({ id: "trig-open", state: "ACTIVE" }),
        trigger({ id: "trig-done", state: "COMPLETED", planned_end_at: "2026-10-01T09:00:30Z" }),
        trigger({ id: "trig-event", type: "EVENT", state: "ACTIVE" }),
      ],
    })
    await screen.findByRole("list", { name: "触发记录列表" })

    expect(triggerRow("trig-open").getByRole("button", { name: "结束" })).toBeTruthy()
    expect(triggerRow("trig-done").queryByRole("button", { name: "结束" })).toBeNull()
    // 409 `recording_trigger_not_manual` otherwise (`triggers.py:348-356`).
    expect(triggerRow("trig-event").getByText("只有手动触发可以手动结束。")).toBeTruthy()
  })

  it("结束前先确认，并说明后录的尾巴还会继续录", async () => {
    renderPanel({ triggers: [trigger({ post_roll_seconds: 45 })] })
    await screen.findByRole("list", { name: "触发记录列表" })

    fireEvent.click(triggerRow("trig-1").getByRole("button", { name: "结束" }))
    const dialog = await confirmDialog()
    // `planned_end_at = now + post_roll_seconds` (`triggers.py:368-372`), and a
    // second stop is a silent no-op — both belong in the prompt.
    expect(within(dialog).getByText(/45 秒的后录尾巴/)).toBeTruthy()
    expect(within(dialog).getByText(/再点一次结束不会有任何变化/)).toBeTruthy()
    expect(writeCalls("/stop", "POST")).toHaveLength(0)

    fireEvent.click(within(dialog).getByRole("button", { name: "结束录制" }))
    await waitFor(() => expect(writeCalls("/stop", "POST")).toHaveLength(1))
  })

  it("取消结束不会发出 stop 请求", async () => {
    renderPanel({ triggers: [trigger()] })
    await screen.findByRole("list", { name: "触发记录列表" })

    fireEvent.click(triggerRow("trig-1").getByRole("button", { name: "结束" }))
    const dialog = await confirmDialog()
    fireEvent.click(within(dialog).getByRole("button", { name: "取消" }))

    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull())
    expect(writeCalls("/stop", "POST")).toHaveLength(0)
  })
})

/* -------------------------------------------------------------------------- */
/* Protections                                                                 */
/* -------------------------------------------------------------------------- */

describe("回放操作 · 保护区间", () => {
  it("结束时间等于开始时间时不发请求——瞬时点不是区间", async () => {
    renderPanel()
    fireEvent.change(screen.getByLabelText("开始时间"), {
      target: { value: "2026-10-01T14:00" },
    })
    fireEvent.change(screen.getByLabelText("结束时间"), {
      target: { value: "2026-10-01T14:00" },
    })
    fireEvent.change(screen.getByLabelText("保护原因"), { target: { value: "误删排查" } })

    fireEvent.click(screen.getByRole("button", { name: "建立保护" }))

    // The window is half-open `[started_at, ended_at)` and the backend rejects
    // `end == start` outright (`protection.py:133-134`).
    expect(
      screen.getByText("结束时间必须晚于开始时间——保护区间是左闭右开的，瞬时点不算区间"),
    ).toBeTruthy()
    expect(writeCalls("recording-protections", "POST")).toHaveLength(0)
  })

  it("body 永远带齐四个字段，失效时间留空时是 null 而不是省略", async () => {
    renderPanel()
    fireEvent.change(screen.getByLabelText("开始时间"), {
      target: { value: "2026-10-01T14:00" },
    })
    fireEvent.change(screen.getByLabelText("结束时间"), {
      target: { value: "2026-10-01T15:00" },
    })
    fireEvent.change(screen.getByLabelText("保护原因"), { target: { value: " 误删排查 " } })

    fireEvent.click(screen.getByRole("button", { name: "建立保护" }))

    await waitFor(() => {
      expect(writeCalls("recording-protections", "POST")).toHaveLength(1)
    })
    const body = writeCalls("recording-protections", "POST")[0].body as Record<
      string,
      unknown
    >
    expect(Object.keys(body).sort()).toEqual([
      "ended_at",
      "expires_at",
      "reason",
      "started_at",
    ])
    // `PUT` replaces the whole object and assigns `expires_at` unconditionally
    // (`protection.py:234-237`); `null` here means "never expires", which is a
    // real state and not an omitted field.
    expect(body.expires_at).toBeNull()
    expect(body.reason).toBe("误删排查")
    // A `datetime-local` value is naive and the service rejects it with a hard
    // 422 `timezone_required` (`core/time.py:48-65`).
    expect(String(body.started_at)).toMatch(/Z$/)
    expect(String(body.ended_at)).toMatch(/Z$/)
  })

  it("填了失效时间时它被转换进 body，而不是原样送出去", async () => {
    renderPanel()
    fireEvent.change(screen.getByLabelText("开始时间"), {
      target: { value: "2099-10-01T14:00" },
    })
    fireEvent.change(screen.getByLabelText("结束时间"), {
      target: { value: "2099-10-01T15:00" },
    })
    fireEvent.change(screen.getByLabelText("保护原因"), { target: { value: "误删排查" } })
    fireEvent.change(screen.getByLabelText("失效时间"), {
      target: { value: "2099-10-02T14:00" },
    })

    fireEvent.click(screen.getByRole("button", { name: "建立保护" }))
    await waitFor(() => {
      expect(writeCalls("recording-protections", "POST")).toHaveLength(1)
    })
    const body = writeCalls("recording-protections", "POST")[0].body as Record<
      string,
      unknown
    >
    expect(String(body.expires_at)).toMatch(/Z$/)
  })

  it("创建按钮之前就说明保护会挡住保留清理", async () => {
    renderPanel()
    const note = screen.getByText("保护会挡住保留策略的清理")
    const button = screen.getByRole("button", { name: "建立保护" })

    // A window silently inflates disk: retention skips protected segments
    // (`storage/retention.py:364-380`), so this belongs before the click, not
    // in a success toast afterwards.
    expect(
      note.compareDocumentPosition(button) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
  })

  it("告警自动创建的保护与手动创建的能分辨", async () => {
    renderPanel({
      protections: [
        protection({ id: "prot-by-hand", created_by: "alice" }),
        protection({ id: "prot-by-alert", created_by: null }),
      ],
    })
    await screen.findByRole("list", { name: "保护区间列表" })

    // Alerts create protections on their own (`alerts/service.py:921-927`) and
    // `created_by` being null is the only evidence left.
    expect(protectionRow("prot-by-alert").getByText("由告警自动创建")).toBeTruthy()
    expect(protectionRow("prot-by-hand").getByText("由 alice 创建")).toBeTruthy()
    expect(protectionRow("prot-by-hand").queryByText("由告警自动创建")).toBeNull()
    expect(protectionRow("prot-by-alert").getByText("永不过期")).toBeTruthy()
  })

  it("已过期的保护仍留在列表里，但标成已失效", async () => {
    renderPanel({
      protections: [
        protection({ id: "prot-old", expires_at: "2020-01-01T00:00:00Z" }),
      ],
    })
    await screen.findByRole("list", { name: "保护区间列表" })
    expect(protectionRow("prot-old").getByText("已失效")).toBeTruthy()
  })

  it("撤销保护要确认；取消不发 DELETE", async () => {
    renderPanel({ protections: [protection()] })
    await screen.findByRole("list", { name: "保护区间列表" })

    fireEvent.click(protectionRow("prot-1").getByTitle("撤销保护"))
    const dialog = await confirmDialog()
    expect(within(dialog).getByText(/此操作不可撤销/)).toBeTruthy()
    expect(within(dialog).getByText(/重新变成可被保留策略清理/)).toBeTruthy()

    fireEvent.click(within(dialog).getByRole("button", { name: "取消" }))
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull())
    expect(writeCalls("recording-protections", "DELETE")).toHaveLength(0)
  })

  it("确认后才发 DELETE", async () => {
    renderPanel({ protections: [protection()] })
    await screen.findByRole("list", { name: "保护区间列表" })

    fireEvent.click(protectionRow("prot-1").getByTitle("撤销保护"))
    const dialog = await confirmDialog()
    fireEvent.click(within(dialog).getByRole("button", { name: "撤销保护" }))

    await waitFor(() => {
      expect(writeCalls("recording-protections", "DELETE")).toHaveLength(1)
    })
    expect(writeCalls("recording-protections", "DELETE")[0].url).toContain("prot-1")
  })
})

/* -------------------------------------------------------------------------- */
/* Composed history                                                            */
/* -------------------------------------------------------------------------- */

describe("回放操作 · 操作历史", () => {
  it("由保护与导出两个列表本地合成，并声明它不是审计日志", async () => {
    renderPanel({
      protections: [protection({ created_at: "2026-10-01T08:00:00Z" })],
      exports: [exportJob({ created_at: "2026-10-01T07:00:00Z" })],
    })
    const list = await screen.findByRole("list", { name: "操作历史列表" })

    const items = within(list).getAllByRole("listitem")
    expect(items).toHaveLength(2)
    expect(within(list).getByText("建立保护")).toBeTruthy()
    expect(within(list).getByText("创建导出任务")).toBeTruthy()
    // The Vue version filtered the protections list client-side and called it
    // history. It is still not an audit trail, and the panel says so.
    expect(panel().textContent).toContain("不是审计日志")
  })

  it("只收本机位的导出任务", async () => {
    renderPanel({
      protections: [],
      exports: [
        exportJob({ id: "exp-mine", camera_id: CAMERA }),
        exportJob({ id: "exp-other", camera_id: "cam-2" }),
      ],
    })
    const list = await screen.findByRole("list", { name: "操作历史列表" })
    expect(within(list).getByText("exp-mine")).toBeTruthy()
    expect(within(list).queryByText("exp-other")).toBeNull()
  })
})

/* -------------------------------------------------------------------------- */
/* Diagnostics                                                                 */
/* -------------------------------------------------------------------------- */

describe("回放诊断 · 本地媒体状态", () => {
  it("读得到播放器的真实状态，并说明偏差为什么读不到", async () => {
    const stage = (
      <div data-stage-state="ready">
        {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
        <video data-testid="media" />
      </div>
    )
    renderDiagnostics({ policies: [policy({ runtime: runtime() })] }, stage)

    const media = screen.getByTestId("media") as HTMLVideoElement
    expect(screen.queryByText(/当前页面没有找到媒体元素/)).toBeNull()

    act(() => {
      Object.defineProperty(media, "readyState", { value: 3, configurable: true })
      Object.defineProperty(media, "paused", { value: false, configurable: true })
      Object.defineProperty(media, "seeking", { value: true, configurable: true })
      Object.defineProperty(media, "playbackRate", { value: 2, configurable: true })
      Object.defineProperty(media, "currentTime", { value: 12.5, configurable: true })
      Object.defineProperty(media, "buffered", {
        value: {
          length: 2,
          start: (index: number) => (index === 0 ? 0 : 60),
          end: (index: number) => (index === 0 ? 30 : 75),
        },
        configurable: true,
      })
      fireEvent(media, new Event("timeupdate"))
    })

    expect(screen.getByText("可播放（3）")).toBeTruthy()
    expect(screen.getByText("12.500 秒")).toBeTruthy()
    expect(screen.getByText("2.000x")).toBeTruthy()
    expect(screen.getByText("2 段，共 45 秒")).toBeTruthy()
    expect(screen.getByText("就绪")).toBeTruthy()

    // The clock lives in a page-local ref (`hooks/useMasterClock.ts:28-32`), so
    // a panel given only `cameraId` cannot compute a real drift number.
    expect(screen.getByText("无法读取")).toBeTruthy()

    const paused = screen.getByText("暂停").parentElement?.textContent
    const seeking = screen.getByText("定位中").parentElement?.textContent
    expect(paused).toContain("否")
    expect(seeking).toContain("是")
  })

  it("没有媒体元素时说明找不到，而不是显示一组零", async () => {
    renderDiagnostics({ policies: [policy({ runtime: runtime() })] })
    expect(screen.getByText(/当前页面没有找到媒体元素/)).toBeTruthy()
  })

  it("挂载时不发任何诊断请求——后端没有这个接口", () => {
    renderDiagnostics({ policies: [policy({ runtime: runtime() })] })
    expect(calls).toHaveLength(0)
  })
})

describe("回放诊断 · 录制运行时的三态", () => {
  it("stream_online / recording 为 null 时是「无法观测」，不是离线也不是未录制", async () => {
    renderDiagnostics({
      policies: [policy({ runtime: runtime({ stream_online: null, recording: null }) })],
    })

    const panel = within(screen.getByTestId("playback-diagnostics-panel"))
    await screen.findByText("录制状态")
    // Collapsing null to false is the one thing this panel must never do: the
    // media runtime could not be observed, which is a different problem from
    // "not recording" (`recordingPolicies.ts:33-44`).
    expect(valueOf(panel, "码流在线")).toBe("无法观测")
    expect(valueOf(panel, "录制状态")).toBe("无法观测")
    expect(screen.queryByText("离线")).toBeNull()
    expect(screen.queryByText("未在录制")).toBeNull()
  })

  it("确认在录制时如实显示，不留「未知」", async () => {
    renderDiagnostics({
      policies: [policy({ runtime: runtime({ stream_online: true, recording: true }) })],
    })
    const panel = within(screen.getByTestId("playback-diagnostics-panel"))
    await screen.findByText("录制状态")
    expect(valueOf(panel, "录制状态")).toBe("正在录制")
    expect(valueOf(panel, "码流在线")).toBe("在线")
    expect(panel.queryByText("无法观测")).toBeNull()
  })

  it("确认没在录制时显示「未在录制」并带上线流离线", async () => {
    renderDiagnostics({
      policies: [
        policy({ runtime: runtime({ stream_online: false, recording: false, blockers: [] }) }),
      ],
    })
    const panel = within(screen.getByTestId("playback-diagnostics-panel"))
    await screen.findByText("录制状态")
    expect(valueOf(panel, "录制状态")).toBe("未在录制")
    expect(valueOf(panel, "码流在线")).toBe("离线")
  })

  it("blockers 里的未知代码原样渲染，不被吞掉", async () => {
    renderDiagnostics({
      policies: [
        policy({
          runtime: runtime({
            recording: false,
            blockers: ["recording_storage_capacity_critical", "brand_new_failure_mode"],
          }),
        }),
      ],
    })
    const list = await screen.findByRole("list", { name: "阻塞原因列表" })

    expect(within(list).getByText("存储容量已到临界水位")).toBeTruthy()
    // An unfamiliar code is a signal the backend gained a failure mode this
    // table has not caught up with, so the raw code stays visible.
    expect(within(list).getByText("录制被阻塞：brand_new_failure_mode")).toBeTruthy()
  })

  it("没有阻塞项时说明没有阻塞项", async () => {
    renderDiagnostics({ policies: [policy({ runtime: runtime() })] })
    await screen.findByText("阻塞原因")
    expect(screen.getByText("没有阻塞项。")).toBeTruthy()
    expect(screen.queryByRole("list", { name: "阻塞原因列表" })).toBeNull()
  })

  it("没有配置策略的机位是正常状态，不是错误", async () => {
    renderDiagnostics({ policies: [] })
    expect(await screen.findByText("该机位没有配置录制策略，因此没有运行时状态。")).toBeTruthy()
  })

  it("还没有观测到运行时时不把它说成「未在录制」", async () => {
    renderDiagnostics({ policies: [policy({ runtime: null })] })
    await screen.findByText("录制状态")
    expect(screen.getByText("尚未观测到录制状态")).toBeTruthy()
    expect(screen.getByText("尚未观测")).toBeTruthy()
    expect(screen.queryByText("未在录制")).toBeNull()
  })
})
