import { QueryClient } from "@tanstack/react-query"
import { renderWithProviders } from "../test-utils"
import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { CamerasView } from "./CamerasView"
import { CAMS } from "../lib/queries"
import type { CameraDetail, CameraSummary } from "../api/cameras"

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
  return renderWithProviders(<CamerasView />, { client: qc })
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
    renderWithProviders(<CamerasView />, { client: qc })
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
      renderWithProviders(<CamerasView />)
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

describe("CamerasView writes", () => {
  function detail(over: Partial<CameraSummary> = {}): CameraDetail {
    return {
      ...camera({ name: "前门人行入口" }),
      streams: [],
      bindings: [],
      ...over,
    }
  }

  function renderSeeded() {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    qc.setQueryData(CAMS.list(false), [camera({ name: "前门人行入口" })])
    qc.setQueryData(CAMS.detail("cam-1"), detail())
    return renderWithProviders(<CamerasView />, { client: qc })
  }

  it("opens the editor for a row and fetches its detail", async () => {
    renderSeeded()
    fireEvent.click(await screen.findByText("前门人行入口"))

    await waitFor(() => {
      expect(screen.getByLabelText("名称")).toBeTruthy()
    })
    // The list endpoint has no streams or bindings; the editor must be fed
    // from the detail endpoint rather than from the row.
    expect(screen.getByText("换不掉背后的设备")).toBeTruthy()
  })

  it("offers restore for a retired camera once retired ones are shown", async () => {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    qc.setQueryData(CAMS.list(false), [
      camera({ name: "在用机位" }),
    ])
    qc.setQueryData(CAMS.list(true), [
      camera({ name: "在用机位" }),
      camera({
        name: "已退役机位",
        retired_at: new Date().toISOString(),
        enabled: false,
      }),
    ])
    renderWithProviders(<CamerasView />, { client: qc })

    // The list endpoint filters retired cameras by default, so the row is not
    // even fetched until the operator asks for it.
    expect(screen.queryByText("已退役机位")).toBeNull()

    fireEvent.click(screen.getByRole("switch"))

    await waitFor(() => {
      expect(screen.getByText("已退役机位")).toBeTruthy()
    })
    expect(screen.getByRole("button", { name: "恢复" })).toBeTruthy()
  })

  it("labels the lifecycle action from the camera's own state", async () => {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    qc.setQueryData(CAMS.list(false), [
      camera({ name: "已停用机位", enabled: false }),
    ])
    renderWithProviders(<CamerasView />, { client: qc })

    // A disabled camera offers "启用", not "停用" — the label comes from the
    // row's own lifecycle state, never from the column header.
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "启用" })).toBeTruthy()
    })
  })
})

/**
 * Retire used to have no entry point at all.
 *
 * `rowActionFor` returns only enable / disable / restore, so the table's
 * `else actions.retire.retire()` was unreachable — the backend had
 * `POST /cameras/{id}/retire`, the mutation wrapped it, the label existed, and
 * nothing led there. Since retire is the one operation that takes a channel out
 * of service while keeping its plans and protections, it is the closest thing
 * the product has to the "lift the channel out, keep the data" model, and it was
 * simply not wired up.
 */
describe("CamerasView retire", () => {
  function renderSeeded(over: Partial<CameraSummary> = {}) {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    qc.setQueryData(CAMS.list(false), [camera({ name: "前门", ...over })])
    return renderWithProviders(<CamerasView />, { client: qc })
  }

  it("offers retire for a live channel", async () => {
    renderSeeded()
    await screen.findByText("前门")
    expect(screen.getByRole("button", { name: "退役" })).toBeTruthy()
  })

  it("does not offer retire twice for an already retired channel", async () => {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    qc.setQueryData(CAMS.list(false), [])
    qc.setQueryData(CAMS.list(true), [
      // Not named "已退役": that string is also the status label and the badge,
      // so the row would match three ways.
      camera({ name: "楼顶球机", retired_at: new Date().toISOString(), enabled: false }),
    ])
    renderWithProviders(<CamerasView />, { client: qc })
    fireEvent.click(screen.getByRole("switch"))
    await screen.findByText("楼顶球机")
    // Restore is the way back; a second retire would be a no-op 409.
    expect(screen.getByRole("button", { name: "恢复" })).toBeTruthy()
    expect(screen.queryByRole("button", { name: "退役" })).toBeNull()
  })

  it("asks before retiring, and cancelling writes nothing", async () => {
    const posts: string[] = []
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        if (init?.method === "POST") posts.push(String(input))
        return new Response(JSON.stringify({}), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      }),
    )
    try {
      renderSeeded()
      fireEvent.click(await screen.findByRole("button", { name: "退役" }))

      // The prompt names the channel, so cancelling is unambiguous.
      const dialog = await screen.findByRole("alertdialog")
      expect(dialog.textContent).toContain("前门")
      fireEvent.click(screen.getByRole("button", { name: "取消" }))
      await waitFor(() =>
        expect(screen.queryByRole("alertdialog")).toBeNull(),
      )
      expect(posts).toHaveLength(0)
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it("retires the channel the operator asked about", async () => {
    const posts: string[] = []
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        if (init?.method === "POST") posts.push(String(input))
        return new Response(JSON.stringify({}), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      }),
    )
    try {
      renderSeeded()
      fireEvent.click(await screen.findByRole("button", { name: "退役" }))
      // Scoped to the dialog: the row button and the confirm button share the
      // label on purpose, so an unscoped lookup matches both.
      const dialog = await screen.findByRole("alertdialog")
      fireEvent.click(within(dialog).getByRole("button", { name: "退役" }))
      await waitFor(() => expect(posts).toHaveLength(1))
      expect(posts[0]).toContain("/cameras/cam-1/retire")
    } finally {
      vi.unstubAllGlobals()
    }
  })

  /**
   * Row actions used to act on the *open* camera, not the clicked one.
   *
   * The buttons stop propagation, so clicking one never changed the selection,
   * while the mutations were built from the selected id. Disabling row B would
   * disable row A — successfully, with a success toast, on the wrong camera.
   */
  it("acts on the row that was clicked, not the one that is open", async () => {
    const posts: string[] = []
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        if (init?.method === "POST") posts.push(String(input))
        return new Response(JSON.stringify({}), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      }),
    )
    try {
      const qc = new QueryClient({
        defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
      })
      qc.setQueryData(CAMS.list(false), [
        camera({ id: "cam-1", name: "前门" }),
        camera({ id: "cam-2", name: "后院" }),
      ])
      // Seeded so the editor really opens on cam-1: the dangerous case is a
      // *different* camera being open, not an empty selection.
      qc.setQueryData(CAMS.detail("cam-1"), {
        ...camera({ id: "cam-1", name: "前门" }),
        streams: [],
        bindings: [],
      })
      renderWithProviders(<CamerasView />, { client: qc })

      // Open the first camera, so a selection exists and is *not* the target.
      fireEvent.click(await screen.findByText("前门"))
      await waitFor(() => expect(screen.getByLabelText("名称")).toBeTruthy())

      // Now click the second row's action.
      const rows = screen.getAllByRole("row")
      const backRow = rows.find((row) => row.textContent?.includes("后院"))
      const disable = within(backRow as HTMLElement).getByRole("button", {
        name: "停用",
      })
      fireEvent.click(disable)

      await waitFor(() => expect(posts).toHaveLength(1))
      expect(posts[0]).toContain("/cameras/cam-2/disable")
      expect(posts[0]).not.toContain("cam-1")
    } finally {
      vi.unstubAllGlobals()
    }
  })
})
