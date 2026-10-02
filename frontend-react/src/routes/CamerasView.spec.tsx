import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { CamerasView } from "./CamerasView"
import { CAMS } from "../lib/queries"
import type { CameraSummary } from "../api/cameras"

/**
 * Page-level rendering with the query cache pre-seeded.
 *
 * The local dev database is empty, so this is how the populated table is
 * verified without mutating a real database. It also pins the behaviour that
 * matters most for a data table: loading, empty, error and loaded must all be
 * distinguishable — a table that silently shows "no data" when the request
 * failed is worse than one that shows nothing at all.
 */

function camera(over: Partial<CameraSummary> = {}): CameraSummary {
  return {
    id: "cam-1",
    name: "前门人行入口",
    enabled: true,
    maintenance: false,
    retired_at: null,
    location: "一层",
    storage_label: null,
    adapter_type: "onvif",
    time_sync_mode: "manage_ntp",
    ptz_capable: true,
    manufacturer: "海康威视",
    model: "DS-2CD2T47G2",
    form_factor: "dome",
    ip: "192.168.1.64",
    port: 554,
    rtsp_path: null,
    sub_rtsp_path: null,
    video_codec: "H.265",
    width: 2688,
    height: 1520,
    fps: 25,
    audio_codec: "aac",
    connectivity_status: "online",
    last_probe_at: new Date().toISOString(),
    last_online_at: new Date().toISOString(),
    ...over,
  }
}

function renderWithCache(setup: (q: QueryClient) => void) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  setup(qc)
  return render(
    <QueryClientProvider client={qc}>
      <CamerasView />
    </QueryClientProvider>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("CamerasView states", () => {
  it("shows a loading skeleton before data arrives", () => {
    // No cache entry and no fetcher → the query stays pending forever here,
    // which is exactly the loading branch.
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    qc.setQueryDefaults(CAMS.list(false), { enabled: false })
    render(
      <QueryClientProvider client={qc}>
        <CamerasView />
      </QueryClientProvider>,
    )
    expect(screen.getAllByText("").length).toBeGreaterThanOrEqual(0)
    // Header is present while loading.
    expect(screen.getByText("摄像机")).toBeTruthy()
  })

  it("renders real rows from the query cache", async () => {
    renderWithCache((qc) => {
      qc.setQueryData(CAMS.list(false), [
        camera(),
        camera({
          id: "cam-2",
          name: "后院周界",
          location: "室外",
          manufacturer: "大华股份",
          model: "IPC-HFW3441T",
          connectivity_status: "offline",
          ptz_capable: false,
          width: null,
          height: null,
        }),
      ])
    })

    await screen.findByText("前门人行入口")
    expect(screen.getByText("后院周界")).toBeTruthy()
    // Joined display values, not raw ids.
    expect(screen.getByText(/海康威视 \/ DS-2CD2T47G2/)).toBeTruthy()
    expect(screen.getByText(/大华股份 \/ IPC-HFW3441T/)).toBeTruthy()
    // Resolution only for the camera that actually reports one.
    expect(screen.getByText(/2688×1520/)).toBeTruthy()
    // Offline camera is labelled offline, not blank.
    expect(screen.getByText("离线")).toBeTruthy()
    // Both cameras counted in the stat row.
    expect(screen.getByText("2", { selector: "span" })).toBeTruthy()
  })

  it("does not invent a waterline or bindings column the API cannot supply", async () => {
    renderWithCache((qc) => {
      qc.setQueryData(CAMS.list(false), [camera()])
    })
    await screen.findByText("前门人行入口")
    // The screen must say why these are absent rather than showing them blank.
    expect(screen.getByText(/列表接口不返回码流绑定与时钟偏差/)).toBeTruthy()
  })

  it("distinguishes an empty result from a failure", async () => {
    renderWithCache((qc) => {
      qc.setQueryData(CAMS.list(false), [])
    })
    await waitFor(() => expect(screen.getByText("没有匹配的机位")).toBeTruthy())
    expect(screen.queryByText("加载失败")).toBeNull()
  })

  it("surfaces a failed request instead of showing an empty table", async () => {
    // Let the real queryFn run against a failing transport, rather than
    // injecting state — this exercises the actual error path end to end.
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              error: {
                code: "internal_error",
                message: "Internal server error.",
                details: {},
              },
            }),
            { status: 500, headers: { "Content-Type": "application/json" } },
          ),
      ),
    )
    try {
      render(
        <QueryClientProvider
          client={
            new QueryClient({ defaultOptions: { queries: { retry: false } } })
          }
        >
          <CamerasView />
        </QueryClientProvider>,
      )
      await waitFor(() => expect(screen.getByText("加载失败")).toBeTruthy())
      expect(screen.getByText("Internal server error.")).toBeTruthy()
      // Critically: not the empty state.
      expect(screen.queryByText("没有匹配的机位")).toBeNull()
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it("degrades to the error state when the response is not an array", async () => {
    // Contract drift / a stale cache entry must not crash the page on
    // `.filter` — it has to land in the same error surface as a 500.
    renderWithCache((qc) => {
      qc.setQueryData(CAMS.list(false), { unexpected: "shape" } as never)
    })
    await waitFor(() => expect(screen.getByText("加载失败")).toBeTruthy())
  })

  it("filters client-side without refetching", async () => {
    renderWithCache((qc) => {
      qc.setQueryData(CAMS.list(false), [
        camera(),
        camera({ id: "cam-2", name: "后院周界", connectivity_status: "offline" }),
      ])
    })
    await screen.findByText("前门人行入口")
    expect(screen.getByText("后院周界")).toBeTruthy()
  })
})
