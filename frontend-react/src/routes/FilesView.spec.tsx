import { QueryClient } from "@tanstack/react-query"
import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { FilesView } from "./FilesView"
import { renderWithRouter } from "../test-utils"
import { CAMS, SYSTEM } from "../lib/queries"
import { ApiError } from "../api/client"
import type { ExportView, ExportShareCreated } from "../api/exports"
import type { RecordingSegmentView } from "../api/playback"
import type { RecordingProtectionView } from "../api/protections"

/**
 * This screen is where the old file page's assumptions meet the real contract,
 * so most of what is asserted here is a refusal: no fabricated progress, no
 * download before the file exists, no share on an unfinished job, no
 * re-submission into a job the queue will never pick up.
 */

const CAMERA = { id: "cam-1", name: "前门人行入口" }

/**
 * Far enough out that the fixture does not silently turn into an "expired"
 * case on a machine whose clock has moved past the date these were written.
 */
const FUTURE = "2099-01-01T00:00:00.000Z"
const PAST = "2000-01-01T00:00:00.000Z"

function segment(over: Partial<RecordingSegmentView> = {}): RecordingSegmentView {
  return {
    id: "seg-1",
    camera_id: "cam-1",
    stream_profile_id: null,
    start_at: "2026-10-01T02:00:00.000Z",
    end_at: "2026-10-01T02:15:00.000Z",
    duration_ms: 15 * 60 * 1000,
    timing_status: "FINAL",
    timing_source: "NORMALIZED",
    recording_reasons: ["event"],
    size_bytes: 32 * 1024 * 1024,
    codec: "H.264",
    container: "mp4",
    integrity_status: "OK",
    completion_reason: null,
    created_at: "2026-10-01T02:15:00.000Z",
    ...over,
  }
}

function job(over: Partial<ExportView> = {}): ExportView {
  return {
    id: "exp-1",
    camera_id: "cam-1",
    requested_by: "user-1",
    start_at: "2026-10-01T02:00:00.000Z",
    end_at: "2026-10-01T03:00:00.000Z",
    requested_duration_ms: 60 * 60 * 1000,
    format: "mp4",
    codec_mode: "auto",
    gap_policy: "skip",
    state: "RUNNING",
    size_bytes: null,
    actual_duration_ms: null,
    selected_segment_count: null,
    metadata: {},
    error_code: null,
    expires_at: FUTURE,
    started_at: "2026-10-01T03:00:01.000Z",
    completed_at: null,
    created_at: "2026-10-01T03:00:00.000Z",
    ...over,
  }
}

function protection(over: Partial<RecordingProtectionView> = {}): RecordingProtectionView {
  return {
    id: "prot-1",
    camera_id: "cam-1",
    started_at: "2026-10-01T01:00:00.000Z",
    ended_at: "2026-10-01T03:00:00.000Z",
    reason: "取证",
    created_by: "user-1",
    expires_at: null,
    created_at: "2026-10-01T00:00:00.000Z",
    updated_at: "2026-10-01T00:00:00.000Z",
    ...over,
  }
}

type Posted = { body: unknown; idempotencyKey: string | null }

const SHARE_CREATED: ExportShareCreated = {
  id: "share-1",
  export_id: "exp-1",
  expires_at: FUTURE,
  revoked_at: null,
  max_downloads: 5,
  download_count: 0,
  last_download_at: null,
  password_protected: true,
  created_at: "2026-10-01T03:00:00.000Z",
  token: "tok-abc",
  download_path: "/api/v1/shared/exports/tok-abc/download",
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

function stubApi(
  overrides: {
    segments?: RecordingSegmentView[]
    protections?: RecordingProtectionView[]
    jobs?: ExportView[]
    shares?: unknown[]
    /** Thrown by successive POST /exports calls, in order. */
    createErrors?: unknown[]
  } = {},
) {
  const posts: Posted[] = []
  const queue = [...(overrides.createErrors ?? [])]

  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? "GET"
      const headers = (init?.headers ?? {}) as Record<string, string>

      if (method === "POST" && url.endsWith("/api/v1/exports")) {
        posts.push({
          body: init?.body ? JSON.parse(String(init.body)) : null,
          idempotencyKey: headers["Idempotency-Key"] ?? null,
        })
        const next = queue.shift()
        if (next) throw next
        return json(job({ state: "PENDING" }))
      }
      if (method === "POST" && url.includes("/shares")) return json(SHARE_CREATED)
      if (url.includes("/recordings?")) {
        return json({ items: overrides.segments ?? [segment()], next_cursor: null })
      }
      if (url.includes("/recording-protections")) {
        return json(overrides.protections ?? [])
      }
      if (url.includes("/exports?")) {
        return json({ items: overrides.jobs ?? [], next_cursor: null })
      }
      if (url.includes("/shares")) return json(overrides.shares ?? [])
      if (url.includes("/api/v1/cameras")) return json([CAMERA])
      return json({})
    }),
  )
  return { posts }
}

const SETTINGS = {
  general: {
    system_name: "NVR",
    display_timezone: "Asia/Shanghai",
    camera_ntp_servers: [],
  },
  time: {
    recording_timezone: "Asia/Shanghai",
    managed_camera_ntp_mode: "manual",
    managed_camera_ntp_servers: [],
  },
  runtime: {},
}

function renderView() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  client.setQueryData(CAMS.list(false), [CAMERA])
  client.setQueryData(SYSTEM.settings, SETTINGS)
  return renderWithRouter(<FilesView />, { client })
}

/** The router renders asynchronously, so the first interaction must wait. */
async function openExports() {
  fireEvent.click(await screen.findByRole("tab", { name: /导出与分享/ }))
}

async function setRange(start: string, end: string) {
  fireEvent.change(await screen.findByLabelText("开始时间"), { target: { value: start } })
  fireEvent.change(await screen.findByLabelText("结束时间"), { target: { value: end } })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("录像浏览", () => {
  it("lists the camera's segments with their real duration and codec", async () => {
    stubApi()
    renderView()
    expect(await screen.findByText("H.264")).toBeTruthy()
    expect(screen.getByText("15 分钟")).toBeTruthy()
    // The vocabulary is translated, not passed through as backend tokens.
    expect(screen.getByText("事件触发")).toBeTruthy()
    expect(screen.getByText("时间已校正")).toBeTruthy()
  })

  it("says so when a segment's time origin is still provisional", async () => {
    stubApi({
      segments: [segment({ timing_status: "PROVISIONAL", timing_source: "HOOK_RAW" })],
    })
    renderView()
    // ADR-0011: a file pulled for evidence must not look trustworthy when it
    // is not. Hiding this behind a normal-looking row is the thing to avoid.
    expect(await screen.findByText("时间为暂定值")).toBeTruthy()
    expect(screen.getByText("ZLM 原始戳")).toBeTruthy()
  })

  it("marks a segment protected when a protection window overlaps it", async () => {
    stubApi({ protections: [protection()] })
    renderView()
    await screen.findByText("H.264")
    expect(
      screen.getByTitle(/与保护时间窗重叠/),
    ).toBeTruthy()
  })

  it("leaves a segment unprotected when the window does not reach it", async () => {
    stubApi({
      protections: [
        protection({
          started_at: "2026-10-01T05:00:00.000Z",
          ended_at: "2026-10-01T06:00:00.000Z",
        }),
      ],
    })
    renderView()
    await screen.findByText("H.264")
    expect(screen.queryByTitle(/与保护时间窗重叠/)).toBeNull()
  })

  it("does not render a resolution or storage-location column", async () => {
    stubApi()
    renderView()
    await screen.findByText("H.264")
    // Neither field exists on the contract; a column here would be invented.
    expect(screen.queryByText("分辨率")).toBeNull()
    expect(screen.queryByText("存储位置")).toBeNull()
  })

  it("hands a segment's own bounds to the export form", async () => {
    stubApi()
    renderView()
    await screen.findByText("H.264")
    fireEvent.click(screen.getByTitle("以这段的时间范围创建导出"))

    // 02:00Z–02:15Z is 10:00–10:15 in Asia/Shanghai, the display zone.
    expect(await screen.findByLabelText("开始时间")).toHaveProperty(
      "value",
      "2026-10-01T10:00",
    )
    expect(screen.getByLabelText("结束时间")).toHaveProperty(
      "value",
      "2026-10-01T10:15",
    )
  })
})

describe("创建导出", () => {
  it("sends the range as UTC with the operator's own timezone applied", async () => {
    const { posts } = stubApi()
    renderView()
    await setRange("2026-10-01T10:00", "2026-10-01T11:00")
    await openExports()
    fireEvent.click(await screen.findByRole("button", { name: /创建导出/ }))

    await waitFor(() => expect(posts).toHaveLength(1))
    // 10:00 Asia/Shanghai is 02:00Z. A naive local-time parse would send the
    // wall clock straight through and export the wrong eight hours.
    expect(posts[0].body).toMatchObject({
      camera_id: "cam-1",
      start_at: "2026-10-01T02:00:00.000Z",
      end_at: "2026-10-01T03:00:00.000Z",
    })
  })

  it("reuses the key when a submit's outcome was unknown", async () => {
    // The case idempotency exists for: the request may or may not have
    // reached the server, so the retry has to be the *same* request. If it
    // landed, the backend returns that job instead of making a second one.
    const { posts } = stubApi({
      createErrors: [new TypeError("Failed to fetch")],
    })
    renderView()
    await openExports()
    fireEvent.click(await screen.findByRole("button", { name: /创建导出/ }))
    await waitFor(() => expect(posts).toHaveLength(1))

    fireEvent.click(screen.getByRole("button", { name: /创建导出/ }))
    await waitFor(() => expect(posts).toHaveLength(2))
    expect(posts[0].idempotencyKey).toBeTruthy()
    expect(posts[1].idempotencyKey).toBe(posts[0].idempotencyKey)
  })

  it("mints a new key once the range changes", async () => {
    const { posts } = stubApi()
    renderView()
    await setRange("2026-10-01T10:00", "2026-10-01T11:00")
    await openExports()
    fireEvent.click(await screen.findByRole("button", { name: /创建导出/ }))
    await waitFor(() => expect(posts).toHaveLength(1))

    await setRange("2026-10-01T10:00", "2026-10-01T12:00")
    fireEvent.click(screen.getByRole("button", { name: /创建导出/ }))
    await waitFor(() => expect(posts).toHaveLength(2))
    expect(posts[1].idempotencyKey).not.toBe(posts[0].idempotencyKey)
  })

  it("refuses a range longer than 7 days before any request is made", async () => {
    const { posts } = stubApi()
    renderView()
    await setRange("2026-10-01T10:00", "2026-10-20T10:00")
    expect((await screen.findAllByText(/单次导出最长 7 天/)).length).toBeGreaterThan(0)

    await openExports()
    expect(screen.getByRole("button", { name: /创建导出/ })).toHaveProperty(
      "disabled",
      true,
    )
    expect(posts).toHaveLength(0)
  })

  it("does not re-submit into a job the queue never picked up", async () => {
    const { posts } = stubApi({
      createErrors: [
        new ApiError(503, "export_task_queue_unavailable", "queue down", {
          export_persisted: true,
          export_id: "exp-stuck",
        }),
      ],
    })
    renderView()
    await openExports()
    fireEvent.click(await screen.findByRole("button", { name: /创建导出/ }))

    expect(await screen.findByText("导出已记录，但未开始处理")).toBeTruthy()
    expect(screen.getByText(/卡住的记录可在列表中取消/)).toBeTruthy()

    // The next submit is a genuinely new export. Reusing the key would hand
    // back the same stranded job with a 201 and nothing would ever run.
    fireEvent.click(screen.getByRole("button", { name: /创建导出/ }))
    await waitFor(() => expect(posts).toHaveLength(2))
    expect(posts[1].idempotencyKey).not.toBe(posts[0].idempotencyKey)
  })
})

describe("导出任务", () => {
  it("shows state, never an invented percentage", async () => {
    stubApi({ jobs: [job({ state: "RUNNING" })] })
    renderView()
    await openExports()
    expect(await screen.findByText("处理中")).toBeTruthy()
    // There is no progress field on ExportView.
    expect(screen.queryByRole("progressbar")).toBeNull()
    expect(screen.queryByText(/%$/)).toBeNull()
  })

  it("offers download only once the job is complete", async () => {
    stubApi({ jobs: [job({ state: "RUNNING" })] })
    renderView()
    await openExports()
    await screen.findByText("处理中")
    expect(screen.queryByRole("link", { name: /下载/ })).toBeNull()
  })

  it("points the download at the authenticated endpoint", async () => {
    stubApi({ jobs: [job({ state: "COMPLETED" })] })
    renderView()
    await openExports()
    const link = await screen.findByRole("link", { name: /下载/ })
    expect(link.getAttribute("href")).toBe("/api/v1/exports/exp-1/download")
  })

  it("withholds download once the file has expired", async () => {
    stubApi({ jobs: [job({ state: "COMPLETED", expires_at: PAST })] })
    renderView()
    await openExports()
    expect(await screen.findByRole("button", { name: /已过期/ })).toBeTruthy()
    expect(screen.queryByRole("link", { name: /下载/ })).toBeNull()
  })

  it("does not offer sharing for a job that has not finished", async () => {
    stubApi({ jobs: [job({ state: "FAILED", error_code: "ffmpeg_failed" })] })
    renderView()
    await openExports()
    expect(await screen.findByText("ffmpeg_failed")).toBeTruthy()
    expect(screen.queryByRole("button", { name: /分享/ })).toBeNull()
  })

  it("warns that a job queued for minutes will not start on its own", async () => {
    stubApi({ jobs: [job({ state: "PENDING", created_at: PAST })] })
    renderView()
    await openExports()
    expect(await screen.findByText("这条导出已排队很久")).toBeTruthy()
  })
})

describe("分享链接", () => {
  async function openSharePanel(overrides = {}) {
    stubApi({ jobs: [job({ state: "COMPLETED" })], ...overrides })
    renderView()
    await openExports()
    fireEvent.click(await screen.findByRole("button", { name: /分享/ }))
  }

  it("states that the link needs no login, rather than implying it is safe", async () => {
    await openSharePanel()
    expect(await screen.findByText("分享链接不需要登录即可下载")).toBeTruthy()
    expect(screen.getByText(/任何拿到链接的人都能下载这段录像/)).toBeTruthy()
  })

  it("shows the token once, as a full URL", async () => {
    await openSharePanel()
    fireEvent.click(await screen.findByRole("button", { name: /创建链接/ }))

    expect(await screen.findByText("链接已创建，仅此一次可见")).toBeTruthy()
    expect(
      screen.getByText(/\/api\/v1\/shared\/exports\/tok-abc\/download$/),
    ).toBeTruthy()
  })

  it("blocks a share whose ttl is outside the backend's bounds", async () => {
    await openSharePanel()
    fireEvent.change(await screen.findByLabelText("有效期小时数"), {
      target: { value: "900" },
    })
    expect(
      (await screen.findAllByText(/1–720/)).length,
    ).toBeGreaterThan(0)
    expect(screen.getByRole("button", { name: /创建链接/ })).toHaveProperty(
      "disabled",
      true,
    )
  })

  it("distinguishes a live share from a dead one", async () => {
    await openSharePanel({
      shares: [
        {
          id: "s1",
          export_id: "exp-1",
          expires_at: FUTURE,
          revoked_at: null,
          max_downloads: 3,
          download_count: 1,
          last_download_at: null,
          password_protected: true,
          created_at: PAST,
        },
        {
          id: "s2",
          export_id: "exp-1",
          expires_at: PAST,
          revoked_at: null,
          max_downloads: null,
          download_count: 0,
          last_download_at: null,
          password_protected: false,
          created_at: PAST,
        },
        {
          id: "s3",
          export_id: "exp-1",
          expires_at: FUTURE,
          revoked_at: PAST,
          max_downloads: null,
          download_count: 0,
          last_download_at: null,
          password_protected: false,
          created_at: PAST,
        },
      ],
    })

    // Queried by label, not by walking up to the nearest <ul>: the export job
    // list is also a <ul> and the share rows are nested inside one of its <li>s.
    const list = await screen.findByLabelText("分享链接列表")
    await waitFor(() => expect(within(list).getAllByRole("listitem")).toHaveLength(3))
    // The status line also carries "· 有密码", so this is a substring match.
    expect(within(list).getByText(/生效中/)).toBeTruthy()
    expect(within(list).getByText("已过期")).toBeTruthy()
    expect(within(list).getByText("已撤销")).toBeTruthy()
    expect(within(list).getByText(/已下载 1\/3 次/)).toBeTruthy()
  })
})
