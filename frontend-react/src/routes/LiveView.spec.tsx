import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { LiveView } from "./LiveView"

/**
 * The wall's own contract: selection is bounded by the layout, shrinking the
 * layout cannot leave orphan tiles, and a tile that cannot play says so with a
 * retry rather than going black.
 */

const CAMERAS = Array.from({ length: 20 }, (_, index) => ({
  id: `cam-${index + 1}`,
  name: `机位 ${index + 1}`,
  enabled: true,
}))

let liveStatus = 200
let resolveCount = 0

beforeEach(() => {
  resolveCount = 0
  liveStatus = 200
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes("/cameras/cam-") && url.includes("/live")) {
        resolveCount += 1
        if (liveStatus >= 400) {
          return new Response(
            JSON.stringify({
              error: { code: "zlm_unavailable", message: "媒体服务不可用" },
            }),
            { status: liveStatus, headers: { "Content-Type": "application/json" } },
          )
        }
        return new Response(
          JSON.stringify({
            camera_id: "cam-1",
            profile_id: "p-1",
            source_role: "sub",
            profile_name: "子码流",
            adapter_profile_key: "k",
            purpose: "LIVE_LOW",
            transport: "hls",
            transports: ["webrtc", "hls"],
            hls_url: "/zlm/zero-nvr/live_0/hls.m3u8?zn_sig=abc",
            media_session_id: "session-1",
            expires_at: new Date(Date.now() + 3_600_000).toISOString(),
            source_codec: "h264",
            codec: "h264",
            width: 640,
            height: 360,
            fps: 15,
            has_audio: false,
            ice_servers: [],
            ice_error: null,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        )
      }
      if (url.includes("/cameras")) {
        return new Response(JSON.stringify(CAMERAS), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      }
      return new Response("{}", {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    }),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

function renderView() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <LiveView />
    </QueryClientProvider>,
  )
}

async function selectCamera(name: string) {
  await waitFor(() => screen.getByText("选择要监控的机位"))
  fireEvent.click(screen.getByText(name))
}

describe("LiveView", () => {
  it("prompts for a selection before showing an empty wall", async () => {
    renderView()
    await waitFor(() => {
      expect(screen.getByText("选择要监控的机位")).toBeTruthy()
    })
  })

  it("shows a tile for a selected camera", async () => {
    renderView()
    await selectCamera("机位 1")

    await waitFor(() => {
      expect(screen.getAllByText("机位 1").length).toBeGreaterThan(0)
    })
    // A tile exists even before it has a picture — it is never a blank hole.
    expect(document.querySelector("video")).toBeTruthy()
  })

  it("starts resolving the stream for a selected camera", async () => {
    renderView()
    await selectCamera("机位 1")

    await waitFor(() => {
      expect(resolveCount).toBeGreaterThan(0)
    })
  })

  it("refuses to exceed the layout capacity", async () => {
    renderView()
    await waitFor(() => screen.getByText("选择要监控的机位"))

    // The default 4-up layout takes four tiles and no more.
    for (const name of ["机位 1", "机位 2", "机位 3", "机位 4", "机位 5"]) {
      fireEvent.click(screen.getByText(name))
    }

    await waitFor(() => {
      expect(screen.getByText("已选择 4 / 4 路")).toBeTruthy()
    })
  })

  it("drops tiles that no longer fit when the layout shrinks", async () => {
    renderView()
    await waitFor(() => screen.getByText("选择要监控的机位"))

    fireEvent.click(screen.getByRole("button", { name: "9 画面" }))
    for (const name of ["机位 1", "机位 2", "机位 3"]) {
      fireEvent.click(screen.getByText(name))
    }
    await waitFor(() => {
      expect(screen.getByText("已选择 3 / 9 路")).toBeTruthy()
    })

    fireEvent.click(screen.getByRole("button", { name: "4 画面" }))

    await waitFor(() => {
      expect(screen.getByText("已选择 3 / 4 路")).toBeTruthy()
    })
  })

  it("never offers a single-tile layout", () => {
    // The backend's wall accepts 4, 9 and 16 only.
    renderView()
    expect(screen.queryByRole("button", { name: "1 画面" })).toBeNull()
  })

  it("shows a reason and a retry when a tile cannot start", async () => {
    liveStatus = 503
    renderView()
    await selectCamera("机位 1")

    await waitFor(() => {
      expect(screen.getAllByRole("button", { name: "重试" }).length).toBeGreaterThan(
        0,
      )
    })
    // The failure has to be legible, not just a black rectangle.
    expect(screen.getAllByText(/获取直播地址失败/).length).toBeGreaterThan(0)
  })

  it("retries on demand", async () => {
    renderView()
    await selectCamera("机位 1")

    const retry = await screen.findAllByRole("button", { name: "重试" })
    const before = resolveCount
    fireEvent.click(retry[0])

    await waitFor(() => {
      expect(resolveCount).toBeGreaterThan(before)
    })
  })

  it("clears the wall on request", async () => {
    renderView()
    await selectCamera("机位 1")

    const clear = await screen.findByRole("button", { name: "清空" })
    fireEvent.click(clear)

    await waitFor(() => {
      expect(screen.getByText("选择要监控的机位")).toBeTruthy()
    })
  })

  it("reports an empty installation instead of an empty wall", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response("[]", {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    )
    renderView()
    await waitFor(() => {
      expect(screen.getByText("还没有可监控的机位")).toBeTruthy()
    })
  })

  it("surfaces a backend failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).includes("/cameras")) {
          throw new TypeError("failed to fetch")
        }
        return new Response("{}", {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      }),
    )
    renderView()
    await waitFor(() => {
      expect(screen.getByText("无法加载机位列表")).toBeTruthy()
    })
  })

  it("offers a per-tile source choice", async () => {
    renderView()
    await selectCamera("机位 1")

    const select = await screen.findByRole("combobox", {
      name: /码流选择/,
    })
    expect((select as HTMLSelectElement).value).toBe("auto")

    fireEvent.change(select, { target: { value: "main" } })
    await waitFor(() => {
      expect((select as HTMLSelectElement).value).toBe("main")
    })
  })
})
