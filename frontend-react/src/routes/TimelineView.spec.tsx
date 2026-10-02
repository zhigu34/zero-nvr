import { QueryClient } from "@tanstack/react-query"
import { fireEvent, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { TimelineView } from "./TimelineView"
import { renderWithRouter } from "../test-utils"
import { CAMS, SYSTEM } from "../lib/queries"
import type { CameraSummary } from "../api/cameras"
import type { PlaybackTimelineView } from "../api/playback"

/**
 * The timeline screen's contract story: two endpoints with a hard 2–9 camera
 * window between them, detail levels whose names do not describe them, and no
 * server-side cap on either range or marker count. Most of what follows is a
 * refusal to let the page quietly paper over one of those.
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
    width: 1920,
    height: 1080,
    fps: 25,
    audio_codec: null,
    connectivity_status: "online",
    last_probe_at: null,
    last_online_at: null,
  }
}

function track(cameraId: string, over: Partial<PlaybackTimelineView> = {}): PlaybackTimelineView {
  return {
    camera_id: cameraId,
    detail: "hour",
    range: { start_at: "2026-10-02T00:00:00.000Z", end_at: "2026-10-03T00:00:00.000Z" },
    segments: [
      {
        id: "s1",
        playback_ref: "s1",
        start_at: "2026-10-02T01:00:00.000Z",
        end_at: "2026-10-02T02:00:00.000Z",
        availability: "local",
      },
    ],
    recording_ranges: [],
    gaps: [
      {
        start_at: "2026-10-02T02:00:00.000Z",
        end_at: "2026-10-02T03:00:00.000Z",
        reason: "source_lost",
      },
    ],
    events: [
      {
        id: "e1",
        marker_type: "aggregate",
        category: "person",
        label: null,
        start_at: "2026-10-02T01:30:00.000Z",
        end_at: "2026-10-02T01:35:00.000Z",
        count: 4,
        category_counts: { person: 4 },
        label_counts: {},
      },
    ],
    ...over,
  }
}

type Call = { url: string; method: string; body: unknown }

function stubApi(cameras: CameraSummary[], tracks: PlaybackTimelineView[]) {
  const calls: Call[] = []
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? "GET"
      calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : null })

      if (url.includes("/playback/timeline")) {
        return json(tracks)
      }
      if (/\/cameras\/[^/]+\/timeline/.test(url)) {
        const id = url.match(/\/cameras\/([^/]+)\/timeline/)?.[1] ?? ""
        return json(tracks.find((t) => t.camera_id === id) ?? null)
      }
      if (url.includes("/api/v1/cameras")) return json(cameras)
      return json({})
    }),
  )
  return calls
}

function json(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  })
}

const TZ = "UTC"

function renderView(cameras: CameraSummary[]) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  client.setQueryData(CAMS.list(false), cameras)
  client.setQueryData(SYSTEM.settings, {
    general: {
      system_name: "NVR",
      display_timezone: TZ,
      camera_ntp_servers: [],
    },
    time: {
      recording_timezone: TZ,
      managed_camera_ntp_mode: "manual",
      managed_camera_ntp_servers: [],
    },
    runtime: {},
  })
  return renderWithRouter(<TimelineView />, { client })
}

/** Pin the window to 00:00–04:00 UTC so click fractions are deterministic. */
async function useFixedRange() {
  fireEvent.click(await screen.findByRole("button", { name: "自定义" }))
  fireEvent.change(await screen.findByLabelText("自定义开始时间"), {
    target: { value: "2026-10-02T00:00" },
  })
  fireEvent.change(await screen.findByLabelText("自定义结束时间"), {
    target: { value: "2026-10-02T04:00" },
  })
}

/**
 * Camera names are prefixes of each other once there are more than ten
 * ("机位1" is inside "机位10"), so these are matched exactly rather than by
 * a regex built from the name.
 */
async function selectCameras(names: string[]) {
  for (const name of names) {
    fireEvent.click(await screen.findByRole("button", { name }))
  }
}

/**
 * jsdom gives every element a zero-sized rect, and `TimelineTrack` refuses to
 * translate a click it cannot measure — so a real click has to be staged.
 */
function stubTrackGeometry() {
  const original = Element.prototype.getBoundingClientRect
  Element.prototype.getBoundingClientRect = function () {
    return { x: 0, y: 0, top: 0, left: 0, right: 1000, bottom: 40, width: 1000, height: 40, toJSON: () => ({}) } as DOMRect
  }
  return () => {
    Element.prototype.getBoundingClientRect = original
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("机位选择", () => {
  it("asks for a selection before it asks the backend for anything", async () => {
    const calls = stubApi([camera("c1", "前门")], [])
    renderView([camera("c1", "前门")])
    expect(await screen.findByText("选择机位以查看时间轴")).toBeTruthy()
    expect(calls.filter((c) => c.url.includes("timeline"))).toHaveLength(0)
  })

  it("uses the single-camera endpoint for one camera", async () => {
    const calls = stubApi([camera("c1", "前门")], [track("c1")])
    renderView([camera("c1", "前门")])
    await selectCameras(["前门"])
    await waitFor(() =>
      expect(calls.some((c) => c.url.includes("/cameras/c1/timeline"))).toBe(true),
    )
    expect(calls.some((c) => c.method === "POST")).toBe(false)
  })

  it("collapses 2–9 cameras into one aligned request", async () => {
    const cams = [camera("c1", "前门"), camera("c2", "车库"), camera("c3", "后门")]
    const calls = stubApi(cams, cams.map((c) => track(c.id)))
    renderView(cams)
    await selectCameras(["前门", "车库", "后门"])

    // One request per selection change is expected; what must not happen is
    // one request *per camera*. The last call has to carry all three.
    await waitFor(() => {
      const posts = calls.filter((c) => c.method === "POST")
      expect(posts.at(-1)?.body).toMatchObject({ camera_ids: ["c1", "c2", "c3"] })
    })
    // The endpoint rejects fewer than 2, and rejects a camelCase key outright.
    expect(calls.filter((c) => c.url.includes("/cameras/c1/timeline"))).toHaveLength(1)
    expect(calls.filter((c) => c.url.includes("/cameras/c2/timeline"))).toHaveLength(0)
  })

  it("refuses to select past the endpoint's 9-camera limit", async () => {
    const cams = Array.from({ length: 11 }, (_, i) => camera(`c${i}`, `机位${i}`))
    stubApi(cams, [])
    renderView(cams)
    await selectCameras(cams.slice(0, 9).map((c) => c.name))

    const tenth = await screen.findByRole("button", { name: "机位9" })
    expect(tenth).toHaveProperty("disabled", true)
    expect(await screen.findByText(/已达对齐接口上限 9 台/)).toBeTruthy()
  })
})

describe("粒度与范围", () => {
  it("labels the detail levels by bucket size, not by their misleading names", async () => {
    stubApi([camera("c1", "前门")], [])
    renderView([camera("c1", "前门")])
    const select = await screen.findByLabelText("事件粒度")
    // `day` buckets hourly and `hour` every five minutes
    // (`timeline.py:414-418`); showing the raw tokens would be a lie.
    expect(select.textContent).toContain("1 小时（按 1 小时分桶）")
    expect(select.textContent).toContain("5 分钟（按 5 分钟分桶）")
    expect(select.textContent).toContain("逐个事件（每个事件一个标记）")
  })

  it("coarsens the granularity when the range widens", async () => {
    stubApi([camera("c1", "前门")], [])
    renderView([camera("c1", "前门")])
    const select = (await screen.findByLabelText("事件粒度")) as HTMLSelectElement

    fireEvent.click(await screen.findByRole("button", { name: "最近 7 天" }))
    await waitFor(() => expect(select.value).toBe("day"))

    fireEvent.click(await screen.findByRole("button", { name: "今天" }))
    await waitFor(() => expect(select.value).toBe("hour"))
  })

  it("warns before a per-event request over a wide range", async () => {
    stubApi([camera("c1", "前门")], [])
    renderView([camera("c1", "前门")])
    fireEvent.click(await screen.findByRole("button", { name: "最近 7 天" }))
    fireEvent.change(await screen.findByLabelText("事件粒度"), {
      target: { value: "minute" },
    })
    // The backend has no LIMIT, so this is the only place the cost is stated.
    expect(await screen.findByText("当前组合可能很慢")).toBeTruthy()
  })

  it("sends the detail token and the range the contract expects", async () => {
    const calls = stubApi([camera("c1", "前门")], [track("c1")])
    renderView([camera("c1", "前门")])
    await selectCameras(["前门"])
    await waitFor(() =>
      expect(calls.some((c) => c.url.includes("/timeline"))).toBe(true),
    )
    const call = calls.find((c) => c.url.includes("/timeline"))!
    expect(call.url).toContain("detail=")
    expect(call.url).toMatch(/[?&]from=/)
    expect(call.url).toMatch(/[?&]to=/)
  })
})

describe("轨道内容", () => {
  it("renders a track per camera with its real counts", async () => {
    const cams = [camera("c1", "前门"), camera("c2", "车库")]
    stubApi(cams, cams.map((c) => track(c.id)))
    renderView(cams)
    await selectCameras(["前门", "车库"])

    await screen.findAllByRole("slider", { name: "回放时间轴" })
    expect(screen.getAllByText(/1 段 · 4 事件 · 1 处空缺/).length).toBe(2)
    expect(screen.getAllByText("前门").length).toBe(2)
    expect(screen.getAllByText("车库").length).toBe(2)
  })

  it("keeps a gap labelled by its reason rather than as a black bar", async () => {
    stubApi([camera("c1", "前门")], [track("c1")])
    renderView([camera("c1", "前门")])
    await selectCameras(["前门"])
    await screen.findByRole("slider", { name: "回放时间轴" })
    // The reason points at a different operator action than a generic gap.
    expect(
      document.querySelector('[data-gap-reason="source_lost"]'),
    ).toBeTruthy()
  })

  it("reports coverage at a clicked moment instead of guessing", async () => {
    stubApi([camera("c1", "前门")], [track("c1")])
    renderView([camera("c1", "前门")])
    await useFixedRange()
    await selectCameras(["前门"])
    const trackEl = await screen.findByRole("slider", { name: "回放时间轴" })
    const restore = stubTrackGeometry()
    try {
      // 00:00–04:00 with a 1000px track: the 02:00–03:00 gap is 50–75%.
      fireEvent.click(trackEl, { clientX: 600, clientY: 10 })
    } finally {
      restore()
    }

    expect(await screen.findByText("无录像")).toBeTruthy()
    // The reason points at a different operator action than a generic gap.
    expect(screen.getByText("摄像机信号丢失")).toBeTruthy()
  })

  it("opens playback at the clicked camera and moment", async () => {
    stubApi([camera("c1", "前门")], [track("c1")])
    renderView([camera("c1", "前门")])
    await useFixedRange()
    await selectCameras(["前门"])
    const trackEl = await screen.findByRole("slider", { name: "回放时间轴" })
    const restore = stubTrackGeometry()
    try {
      // 00:00–04:00: the 01:00–02:00 segment is 25–50%.
      fireEvent.click(trackEl, { clientX: 300, clientY: 10 })
    } finally {
      restore()
    }
    fireEvent.click(await screen.findByRole("button", { name: /在回放中打开/ }))

    // The deep link carries both halves; a playback page opened on the wrong
    // camera is worse than no link at all.
    expect(
      screen.getByRole("button", { name: /在回放中打开/ }),
    ).toBeTruthy()
  })
})
