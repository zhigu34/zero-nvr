import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { PlaybackView } from "./PlaybackView"

/**
 * The playback screen is where a unit-tested status machine meets a real
 * network. These assert the seams: that the timeline's gap reasons survive
 * into the UI, that the transport controls actually drive the clock, and that
 * a failed resolve produces a retryable tile rather than a black one.
 */

const HOUR = 3_600_000

const CAMERAS = [
  { id: "cam-1", name: "前门人行入口", enabled: true },
  { id: "cam-2", name: "后院周界", enabled: true },
]

let resolveResponse: unknown = {
  status: "playable",
  segment_id: "s1",
  segment_start_at: new Date().toISOString(),
  offset_ms: 0,
  transport: "mp4",
  url: "/api/v1/recordings/s1/media",
  expires_at: new Date().toISOString(),
  codec: "h264",
}

let resolveCalls: string[] = []

function timelineBody() {
  const to = Date.now()
  // The single-camera endpoint returns one view, not a list; the batched
  // `/playback/timeline` is the one that returns an array.
  return {
    camera_id: "cam-1",
    detail: "minute",
    range: {
      start_at: new Date(to - 2 * HOUR).toISOString(),
      end_at: new Date(to).toISOString(),
    },
    segments: [
      {
        id: "s1",
        playback_ref: "s1",
        start_at: new Date(to - 2 * HOUR).toISOString(),
        end_at: new Date(to - HOUR).toISOString(),
        availability: "local",
      },
    ],
    recording_ranges: [],
    gaps: [
      {
        start_at: new Date(to - HOUR).toISOString(),
        end_at: new Date(to).toISOString(),
        reason: "storage_failure",
      },
    ],
    events: [],
  }
}

beforeEach(() => {
  resolveCalls = []
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.includes("/playback/resolve")) {
        resolveCalls.push(url)
        if (resolveResponse instanceof Error) throw resolveResponse
        return new Response(JSON.stringify(resolveResponse), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      }
      if (url.includes("/timeline")) {
        return new Response(JSON.stringify(timelineBody()), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      }
      if (url.includes("/cameras")) {
        return new Response(JSON.stringify(CAMERAS), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      }
      void init
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
      <PlaybackView />
    </QueryClientProvider>,
  )
}

describe("PlaybackView", () => {
  it("shows a loading state before the camera list arrives", () => {
    renderView()
    expect(screen.getByText("正在加载机位列表…")).toBeTruthy()
  })

  it("defaults to the first camera once the list loads", async () => {
    renderView()
    await waitFor(() => {
      const select = screen.getByRole("combobox") as HTMLSelectElement
      expect(select.value).toBe("cam-1")
    })
  })

  it("tells the user when there is nothing to play back", async () => {
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
      expect(screen.getByText("还没有可回放的机位")).toBeTruthy()
    })
  })

  it("surfaces a backend failure instead of an empty screen", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).includes("/cameras")) throw new TypeError("failed to fetch")
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

  it("renders the timeline with its gap reasons intact", async () => {
    renderView()
    await waitFor(() => {
      const gap = document.querySelector('[data-gap-reason="storage_failure"]')
      expect(gap).toBeTruthy()
      expect(gap!.getAttribute("title")).toContain("存储故障")
    })
  })

  it("resolves playback for the selected camera", async () => {
    renderView()
    await waitFor(() => {
      expect(resolveCalls.length).toBeGreaterThan(0)
    })
    expect(resolveCalls[0]).toContain("/cameras/cam-1/playback/resolve")
  })

  it("offers a retry when the resolve fails, and retries when pressed", async () => {
    resolveResponse = new TypeError("failed to fetch")
    renderView()

    const retry = await screen.findByRole("button", { name: "重试" })
    // A failed tile must state a reason, not just go dark.
    expect(screen.getByText(/无法连接后端/)).toBeTruthy()

    resolveResponse = {
      status: "playable",
      segment_id: "s1",
      segment_start_at: new Date().toISOString(),
      offset_ms: 0,
      transport: "mp4",
      url: "/api/v1/recordings/s1/media",
      expires_at: new Date().toISOString(),
      codec: "h264",
    }
    const before = resolveCalls.length
    fireEvent.click(retry)

    await waitFor(() => {
      expect(resolveCalls.length).toBeGreaterThan(before)
    })
  })

  it("shows the restore cadence while the archive is being pulled back", async () => {
    resolveResponse = {
      status: "pending",
      reason: "remote_restore_required",
      segment_id: "s9",
      retry_after_ms: 2_000,
    }
    renderView()

    await waitFor(() => {
      expect(screen.getByText("约 2 秒后重试")).toBeTruthy()
    })
  })

  it("labels a gap by its backend reason rather than as a black bar", async () => {
    resolveResponse = {
      status: "gap",
      reason: "purged",
      previous_at: new Date(Date.now() - HOUR).toISOString(),
      next_at: null,
    }
    renderView()

    await waitFor(() => {
      expect(screen.getByText("已按保留策略清理")).toBeTruthy()
    })
  })

  it("toggles playback", async () => {
    renderView()
    await waitFor(() => screen.getByRole("combobox"))

    const play = screen.getByRole("button", { name: "播放" })
    fireEvent.click(play)
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "暂停" })).toBeTruthy()
    })

    fireEvent.click(screen.getByRole("button", { name: "暂停" }))
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "播放" })).toBeTruthy()
    })
  })

  it("mutes audio above 4x because it is unintelligible", async () => {
    renderView()
    await waitFor(() => screen.getByRole("combobox"))

    fireEvent.click(screen.getByRole("button", { name: "8×" }))

    await waitFor(() => {
      expect(screen.getByText(/已静音/)).toBeTruthy()
    })
  })

  it("does not claim to mute below 4x", async () => {
    renderView()
    await waitFor(() => screen.getByRole("combobox"))

    fireEvent.click(screen.getByRole("button", { name: "2×" }))

    await waitFor(() => {
      expect(screen.queryByText(/已静音/)).toBeNull()
    })
  })

  it("seeks when the timeline is clicked", async () => {
    renderView()
    await waitFor(() => {
      expect(document.querySelector('[data-testid="playhead"]')).toBeTruthy()
    })

    const before = resolveCalls.length
    const track = screen.getByRole("slider")
    track.getBoundingClientRect = () =>
      ({ left: 0, width: 1000, top: 0, height: 44 }) as DOMRect
    fireEvent.click(track, { clientX: 500 })

    await waitFor(() => {
      expect(resolveCalls.length).toBeGreaterThan(before)
    })
  })

  it("steps the playhead with the transport buttons", async () => {
    renderView()
    await waitFor(() => screen.getByRole("combobox"))

    const before = resolveCalls.length
    fireEvent.click(screen.getByRole("button", { name: "前进 30 秒" }))

    await waitFor(() => {
      expect(resolveCalls.length).toBeGreaterThan(before)
    })
  })
})
