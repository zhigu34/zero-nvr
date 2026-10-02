import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { EventsView } from "./EventsView"

/**
 * Cursor ("load more") pagination is the part of this screen that breaks
 * silently: an offset-style implementation renders a correct first page and
 * a permanently-stuck "load more", which no screenshot would reveal.
 */

type Row = {
  id: string
  source: string
  camera_id: string | null
  category: string
  started_at: string
  ended_at: string | null
  confidence: number | null
  severity: string | null
  snapshot_ref: string | null
  metadata: Record<string, unknown>
  [k: string]: unknown
}

function row(id: string, over: Partial<Row> = {}): Row {
  return {
    id,
    source: "onvif",
    camera_id: null,
    category: "person",
    started_at: "2026-10-02T06:00:00Z",
    ended_at: "2026-10-02T06:00:30Z",
    confidence: 0.9,
    severity: null,
    snapshot_ref: null,
    metadata: {},
    ...over,
  }
}

let requestedUrls: string[] = []

function stubEventPages(pages: Row[][], cursors: (string | null)[]) {
  let call = 0
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      requestedUrls.push(url)
      if (url.includes("/cameras")) {
        return new Response("[]", {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      }
      const cursor = new URL(url, "http://x").searchParams.get("cursor")
      // A cursor points at the NEXT page, not the current one. Serving page
      // `indexOf(cursor) + 1` means a client that ignores or mis-sends the
      // cursor gets the wrong rows and the test fails.
      const idx = cursor === null ? 0 : cursors.indexOf(cursor) + 1
      const body = {
        items: pages[idx] ?? [],
        next_cursor: cursors[idx] ?? null,
      }
      call += 1
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    }),
  )
  return () => call
}

function client() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
}

function renderView(qc: QueryClient) {
  return render(
    <QueryClientProvider client={qc}>
      <EventsView />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  requestedUrls = []
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("EventsView cursor pagination", () => {
  it("loads only the first page initially and never sends page=2", async () => {
    stubEventPages([[row("e1"), row("e2")]], [null])
    renderView(client())
    await waitFor(() => expect(screen.getByRole("table")).toBeTruthy())
    const eventCalls = requestedUrls.filter((u) => u.includes("/events?"))
    expect(eventCalls).toHaveLength(1)
    expect(eventCalls[0]).not.toContain("page=")
    expect(eventCalls[0]).not.toContain("cursor=")
  })

  it("appends the next page when loading more, and the new rows actually appear", async () => {
    stubEventPages(
      [[row("e1", { category: "person" })], [row("e2", { category: "vehicle" })]],
      ["c2", null],
    )
    renderView(client())

    // Scope to the table: the category <select> also contains these labels.
    const table = () => screen.getByRole("table")
    await waitFor(() => expect(within(table()).getByText("人员")).toBeTruthy())

    fireEvent.click(await screen.findByRole("button", { name: "加载更多" }))

    await waitFor(() => expect(within(table()).getByText("车辆")).toBeTruthy())
    expect(requestedUrls.some((u) => u.includes("cursor=c2"))).toBe(true)
    // The first page is still on screen — appending, not replacing.
    expect(within(table()).getByText("人员")).toBeTruthy()
  })

  it("hides the load-more control at the end of the list", async () => {
    stubEventPages([[row("e1")]], [null])
    renderView(client())
    await waitFor(() => expect(screen.getByText(/已到末尾/)).toBeTruthy())
    expect(screen.queryByRole("button", { name: "加载更多" })).toBeNull()
  })
})

describe("EventsView camera-name join", () => {
  it("labels an event with no camera as 无关联机位", async () => {
    stubEventPages([[row("e1", { camera_id: null })]], [null])
    renderView(client())
    await screen.findByText("无关联机位")
  })

  it("shows a truncated id when the camera is not in the camera list", async () => {
    stubEventPages([[row("e1", { camera_id: "abcdef0123456789" })]], [null])
    renderView(client())
    // Must not be blank: a blank cell is indistinguishable from "not loaded".
    await screen.findByText(/未知机位 abcdef01/)
  })
})

describe("EventsView metadata rendering", () => {
  it("survives null and nested metadata values", async () => {
    stubEventPages(
      [
        [
          row("e1", {
            metadata: { zone_name: "前院", nested: { a: 1 }, empty: null },
          }),
        ],
      ],
      [null],
    )
    renderView(client())
    // The detail panel only exists once a row is selected. Click inside the
    // table: the category <select> has an <option> with the same label.
    const cell = await within(screen.getByRole("table")).findByText("人员")
    fireEvent.click(cell)
    await screen.findByText("前院")
    // Nested object is stringified, not dropped.
    expect(screen.getByText('{"a":1}')).toBeTruthy()
    // A null value renders as an em dash. Several other fields are null too,
    // so assert on presence rather than a unique match.
    expect(screen.getAllByText("—").length).toBeGreaterThan(0)
  })
})

describe("EventsView state derivation", () => {
  it("marks an event with ended_at=null as 进行中", async () => {
    stubEventPages([[row("e1", { ended_at: null })]], [null])
    renderView(client())
    await screen.findByText("进行中")
  })

  it("does not invent an acknowledged state the backend has no field for", async () => {
    stubEventPages([[row("e1", { ended_at: "2026-10-02T06:00:30Z" })]], [null])
    renderView(client())
    await screen.findByText("已结束")
    expect(screen.queryByText("已确认")).toBeNull()
  })
})

describe("EventsView failure state", () => {
  it("shows the error instead of an empty table", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              error: { code: "internal_error", message: "Internal server error.", details: {} },
            }),
            { status: 500, headers: { "Content-Type": "application/json" } },
          ),
      ),
    )
    renderView(client())
    await waitFor(() => expect(screen.getByText("加载失败")).toBeTruthy())
    expect(screen.queryByText("该条件下没有事件")).toBeNull()
  })
})
