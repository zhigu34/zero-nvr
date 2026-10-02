import { QueryClient } from "@tanstack/react-query"
import { fireEvent, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { SchedulesView } from "./SchedulesView"
import { renderWithProviders } from "../test-utils"
import { CAMS, POLICIES } from "../lib/queries"
import type { CameraSummary } from "../api/cameras"
import type {
  RecordingPolicyView,
  RecordingRuntime,
} from "../api/recordingPolicies"

/**
 * The page's whole reason to exist is the gap between "saved" and
 * "recording". These assert that what the operator reads comes from
 * `runtime`, not from the fact that a form was submitted.
 */

function camera(id: string, name: string): CameraSummary {
  return {
    id,
    name,
    enabled: true,
    maintenance: false,
    retired_at: null,
    location: null,
    storage_label: null,
    adapter_type: "onvif",
    time_sync_mode: "ignore",
    ptz_capable: false,
    manufacturer: null,
    model: null,
    form_factor: "box",
    ip: null,
    port: null,
    rtsp_path: null,
    sub_rtsp_path: null,
    video_codec: "h264",
    width: 1920,
    height: 1080,
    fps: 25,
    audio_codec: null,
    connectivity_status: "online",
    last_probe_at: null,
    last_online_at: null,
  }
}

function runtime(over: Partial<RecordingRuntime> = {}): RecordingRuntime {
  return {
    desired_mode: "persistent",
    recording: true,
    stream_online: true,
    changed: false,
    assumed_existing_mode: false,
    observed_at: "2026-10-01T00:00:00Z",
    blockers: [],
    ...over,
  }
}

function policy(over: Partial<RecordingPolicyView> = {}): RecordingPolicyView {
  return {
    id: "pol-1",
    camera_id: "cam-1",
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
    runtime: runtime(),
    ...over,
  }
}

function seed(
  cameras: CameraSummary[],
  policies: RecordingPolicyView[] = [],
): QueryClient {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  client.setQueryData(CAMS.list(false), cameras)
  client.setQueryData(POLICIES.list, policies)
  return client
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("SchedulesView", () => {
  it("lists cameras that have no policy at all", async () => {
    // `GET /recording-policies` only returns configured policies. Showing
    // just those would make an unconfigured camera invisible rather than
    // obviously unset.
    renderWithProviders(<SchedulesView />, {
      client: seed([camera("cam-1", "前门"), camera("cam-2", "后院")]),
    })

    await waitFor(() => {
      expect(screen.getByText("前门")).toBeTruthy()
    })
    expect(screen.getByText("后院")).toBeTruthy()
    expect(screen.getAllByText("未配置").length).toBe(2)
  })

  it("reports a policy whose runtime says it is recording", async () => {
    renderWithProviders(<SchedulesView />, {
      client: seed([camera("cam-1", "前门")], [policy()]),
    })

    await waitFor(() => {
      expect(screen.getByTestId("status-recording")).toBeTruthy()
    })
  })

  it("shows the swallowed stream-offline reason instead of claiming success", async () => {
    renderWithProviders(<SchedulesView />, {
      client: seed(
        [camera("cam-1", "前门")],
        [
          policy({
            runtime: runtime({
              recording: false,
              stream_online: false,
              blockers: ["recording_stream_offline"],
            }),
          }),
        ],
      ),
    })

    await waitFor(() => {
      expect(screen.getByText(/码流离线/)).toBeTruthy()
    })
  })

  /**
   * `null` means the runtime cannot be observed. Drawing it as "未录制"
   * would send the operator after a fault that may not exist.
   */
  it("distinguishes unobservable from not-recording in the table", async () => {
    renderWithProviders(<SchedulesView />, {
      client: seed(
        [camera("cam-1", "前门")],
        [policy({ runtime: runtime({ recording: null, stream_online: null }) })],
      ),
    })

    await waitFor(() => {
      expect(screen.getByTestId("status-unobservable")).toBeTruthy()
    })
    expect(screen.queryByText("未在录制")).toBeNull()
  })

  it("counts recording and problem cameras separately", async () => {
    renderWithProviders(<SchedulesView />, {
      client: seed(
        [camera("cam-1", "A"), camera("cam-2", "B")],
        [
          policy(),
          policy({
            camera_id: "cam-2",
            runtime: runtime({ recording: false, blockers: ["recording_storage_unavailable"] }),
          }),
        ],
      ),
    })

    await waitFor(() => {
      expect(screen.getByTestId("status-recording")).toBeTruthy()
    })
    expect(screen.getByTestId("status-not_recording")).toBeTruthy()
    // The stat card is the at-a-glance version of the same judgement.
    expect(screen.getByText("未录制 / 不可观测")).toBeTruthy()
  })

  it("opens the editor with the current values", async () => {
    renderWithProviders(<SchedulesView />, {
      client: seed(
        [camera("cam-1", "前门")],
        [policy({ segment_target_seconds: 600, pre_roll_seconds: 30 })],
      ),
    })

    fireEvent.click(await screen.findByText("前门"))

    await waitFor(() => {
      expect(screen.getByLabelText("目标分段（秒）")).toBeTruthy()
    })
    expect(
      (screen.getByLabelText("目标分段（秒）") as HTMLInputElement).value,
    ).toBe("600")
    // Seconds on the policy side, rendered in the unit the field is in.
    expect(screen.getAllByText("10 分钟").length).toBeGreaterThan(0)
  })

  it("requires a timezone in schedule mode before it will save", async () => {
    renderWithProviders(<SchedulesView />, {
      client: seed([camera("cam-1", "前门")], [policy({ baseline_mode: "disabled" })]),
    })

    fireEvent.click(await screen.findByText("前门"))
    fireEvent.change(await screen.findByLabelText("录制模式"), {
      target: { value: "schedule" },
    })

    await waitFor(() => {
      expect(screen.getByText("按计划录制至少需要一个时段")).toBeTruthy()
    })
    const save = screen.getByRole("button", { name: "保存" }) as HTMLButtonElement
    expect(save.disabled).toBe(true)
  })

  it("explains that retention days live elsewhere", async () => {
    renderWithProviders(<SchedulesView />, {
      client: seed([camera("cam-1", "前门")], [policy()]),
    })

    fireEvent.click(await screen.findByText("前门"))

    await waitFor(() => {
      expect(screen.getByText("保留天数不在此处配置")).toBeTruthy()
    })
    // The page must not invent a number the endpoint does not carry.
    expect(screen.queryByText(/保留\s*\d+\s*天/)).toBeNull()
  })

  it("explains that the system timezone setting does nothing", async () => {
    renderWithProviders(<SchedulesView />, {
      client: seed([camera("cam-1", "前门")], [policy()]),
    })

    fireEvent.click(await screen.findByText("前门"))

    await waitFor(() => {
      expect(screen.getByText("系统级时区设置当前不生效")).toBeTruthy()
    })
  })

  it("shows the weekly schedule readably", async () => {
    renderWithProviders(<SchedulesView />, {
      client: seed(
        [camera("cam-1", "前门")],
        [
          policy({
            baseline_mode: "schedule",
            schedule_timezone: "Asia/Shanghai",
            schedule: {
              weekly: [{ days: [0, 1, 2, 3, 4], start: "22:00", end: "06:00" }],
            },
          }),
        ],
      ),
    })

    await waitFor(() => {
      expect(screen.getByText(/周一、周二、周三、周四、周五/)).toBeTruthy()
    })
  })

  it("surfaces a load failure instead of an empty table", async () => {
    const client = seed([camera("cam-1", "前门")])
    client.removeQueries({ queryKey: POLICIES.list })
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).includes("recording-policies")) {
          return new Response(
            JSON.stringify({ error: { code: "x", message: "内部错误" } }),
            { status: 500, headers: { "Content-Type": "application/json" } },
          )
        }
        return new Response("[]", {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      }),
    )

    renderWithProviders(<SchedulesView />, { client })

    await waitFor(() => {
      expect(screen.getByText("无法加载录制计划")).toBeTruthy()
    })
  })

  /**
   * The regression this guards is silent and it is **four fields wide**.
   *
   * `PUT /cameras/{id}/recording-policy` replaces the whole policy, and every
   * optional field in `RecordingPolicyPut` has a non-nullable default
   * (`recordings/schemas.py:123-134`). Omitting a key therefore does not mean
   * "leave it alone" — the server writes the default. A body built from the
   * fields the form renders would, in one save:
   *
   * | field | default | effect |
   * |---|---|---|
   * | `event_recording_enabled` | `False` | event-triggered recording switched off |
   * | `event_filter` | `{}` | the operator's filter cleared |
   * | `storage_target_id` | `null` | a pinned target unpinned |
   * | `retention_policy_id` | `null` | the retention policy unbound |
   *
   * …all of it answered with HTTP 200. The fixture below sets **all four** to
   * non-default values on purpose: the default `policy()` fixture has
   * `event_filter: {}` and the rest already at their defaults, which would let
   * every one of these bugs pass.
   */
  it("carries all four non-rendered policy fields through a save", async () => {
    const saved: Record<string, unknown>[] = []
    const carrying = policy({
      event_recording_enabled: true,
      event_filter: { labels: ["person", "car"], min_confidence: 0.6 },
      storage_target_id: "3f1c0a2e-6b6d-4a1f-9c33-2b0d5e7a1c44",
      retention_policy_id: "8d2e1b7a-4c5f-4e6a-b8d9-1a2b3c4d5e6f",
    })

    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        if (init?.method === "PUT" && String(input).includes("recording-policy")) {
          saved.push(JSON.parse(String(init.body)))
          return new Response(JSON.stringify(carrying), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          })
        }
        return new Response("[]", {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      }),
    )

    renderWithProviders(<SchedulesView />, {
      client: seed([camera("cam-1", "前门")], [carrying]),
    })

    fireEvent.click(await screen.findByText("前门"))
    // Touch one field the form *does* own, so the save is a real delta.
    fireEvent.change(await screen.findByLabelText("目标分段（秒）"), {
      target: { value: "450" },
    })
    fireEvent.click(screen.getByRole("button", { name: "保存" }))

    await waitFor(() => {
      expect(saved).toHaveLength(1)
    })
    // `labels` arrives sorted: the form normalises on the way out and
    // `validate_event_filter` sorts again server-side
    // (`recordings/policy.py:238-241`), so order is not a meaningful
    // difference — but the count and the members are.
    expect(saved[0]).toMatchObject({
      // the field the form owns
      segment_target_seconds: 450,
      // the two the event-filter form now owns, round-tripped
      event_recording_enabled: true,
      storage_target_id: "3f1c0a2e-6b6d-4a1f-9c33-2b0d5e7a1c44",
      retention_policy_id: "8d2e1b7a-4c5f-4e6a-b8d9-1a2b3c4d5e6f",
    })
    expect(saved[0].event_filter).toEqual({
      labels: ["car", "person"],
      min_confidence: 0.6,
    })
  })

  it("sends the schema defaults for a policy that never set them", async () => {
    // The other half of the contract: the fallback must not invent values for
    // a camera that has none, and must not resurrect a cleared one.
    const saved: Record<string, unknown>[] = []
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        if (init?.method === "PUT" && String(input).includes("recording-policy")) {
          saved.push(JSON.parse(String(init.body)))
          return new Response(JSON.stringify(policy()), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          })
        }
        return new Response("[]", {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      }),
    )

    renderWithProviders(<SchedulesView />, {
      client: seed([camera("cam-1", "前门")], [policy()]),
    })

    fireEvent.click(await screen.findByText("前门"))
    await screen.findByLabelText("目标分段（秒）")
    fireEvent.click(screen.getByRole("button", { name: "保存" }))

    await waitFor(() => {
      expect(saved).toHaveLength(1)
    })
    expect(saved[0]).toMatchObject({
      event_recording_enabled: false,
      event_filter: {},
      storage_target_id: null,
      retention_policy_id: null,
    })
  })

  it("exposes the event filter, which had no UI at all", async () => {
    // G-46: before the fix this page submitted a body with no `event_filter`
    // and no `event_recording_enabled`, so the operator could neither see nor
    // keep what was configured.
    renderWithProviders(<SchedulesView />, {
      client: seed(
        [camera("cam-1", "前门")],
        [
          policy({
            event_recording_enabled: true,
            event_filter: { labels: ["person", "car"], zones: ["driveway"] },
          }),
        ],
      ),
    })

    fireEvent.click(await screen.findByText("前门"))
    const toggle = await screen.findByLabelText("按事件触发录像")
    expect((toggle as HTMLInputElement).checked).toBe(true)
    // The stored values come back verbatim — the form shows what is on the
    // policy rather than a re-ordered version of it. Normalising to sorted
    // happens on the way out, and the server sorts again.
    expect(
      (screen.getByLabelText("事件标签") as HTMLInputElement).value,
    ).toBe("person, car")
    expect(
      (screen.getByLabelText("区域") as HTMLInputElement).value,
    ).toBe("driveway")
  })

  it("states the zones divergence instead of leaving the operator to guess", async () => {
    // D-2. "录了但没告警" looks like a bug and is not one; the form says so
    // where the zone field actually is.
    renderWithProviders(<SchedulesView />, {
      client: seed(
        [camera("cam-1", "前门")],
        [policy({ event_recording_enabled: true })],
      ),
    })

    fireEvent.click(await screen.findByText("前门"))
    await screen.findByLabelText("区域")
    expect(screen.getByText(/只匹配/)).toBeTruthy()
    expect(screen.getByText(/主区域/)).toBeTruthy()
  })

  it("edits the filter and saves the result", async () => {
    const saved: Record<string, unknown>[] = []
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        if (init?.method === "PUT" && String(input).includes("recording-policy")) {
          saved.push(JSON.parse(String(init.body)))
          return new Response(
            JSON.stringify(
              policy({
                event_recording_enabled: true,
                event_filter: { labels: ["truck"], min_confidence: 0.4 },
              }),
            ),
            { status: 200, headers: { "Content-Type": "application/json" } },
          )
        }
        return new Response("[]", {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      }),
    )

    renderWithProviders(<SchedulesView />, {
      client: seed([camera("cam-1", "前门")], [policy()]),
    })

    fireEvent.click(await screen.findByText("前门"))
    fireEvent.click(await screen.findByLabelText("按事件触发录像"))
    fireEvent.change(screen.getByLabelText("事件标签"), {
      target: { value: "truck, bus" },
    })
    fireEvent.change(screen.getByLabelText("最低置信度"), {
      target: { value: "0.4" },
    })
    fireEvent.click(screen.getByRole("button", { name: "保存" }))

    await waitFor(() => {
      expect(saved).toHaveLength(1)
    })
    expect(saved[0]).toMatchObject({
      event_recording_enabled: true,
      event_filter: { labels: ["bus", "truck"], min_confidence: 0.4 },
    })
    // Untouched keys must not appear — the backend rejects unknown keys.
    expect(saved[0].event_filter).not.toHaveProperty("zones")
  })

  it("lets an empty filter be saved, because it means record-everything", async () => {
    const saved: Record<string, unknown>[] = []
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        if (init?.method === "PUT" && String(input).includes("recording-policy")) {
          saved.push(JSON.parse(String(init.body)))
          return new Response(
            JSON.stringify(policy({ event_recording_enabled: true })),
            { status: 200, headers: { "Content-Type": "application/json" } },
          )
        }
        return new Response("[]", {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      }),
    )

    renderWithProviders(<SchedulesView />, {
      client: seed([camera("cam-1", "前门")], [policy()]),
    })

    fireEvent.click(await screen.findByText("前门"))
    fireEvent.click(await screen.findByLabelText("按事件触发录像"))

    // The empty-filter note appears…
    await waitFor(() => {
      expect(screen.getByText("未设置任何条件：事件触发录像将记录全部事件")).toBeTruthy()
    })
    // …and does not block the save.
    const save = screen.getByRole("button", { name: "保存" }) as HTMLButtonElement
    expect(save.disabled).toBe(false)
    fireEvent.click(save)

    await waitFor(() => {
      expect(saved).toHaveLength(1)
    })
    expect(saved[0]).toMatchObject({
      event_recording_enabled: true,
      event_filter: {},
    })
  })
})
