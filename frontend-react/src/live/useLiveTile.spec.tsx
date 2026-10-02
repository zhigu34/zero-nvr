import { act, render, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { useLiveTile, type UseLiveTile } from "./useLiveTile"
import type { HlsLike } from "./hlsAttachment"
import {
  PREVIEW_WALL_RESOLUTION,
  type CameraLiveStreamView,
} from "../api/live"

/**
 * The behaviour worth protecting here is session lifetime. Keeping a media
 * session alive does not re-sign the HLS URL, so a wall left open long enough
 * used to report healthy keepalives while every tile went dark at the 30
 * minute signature boundary. The tile has to re-resolve before that point.
 */

const HOUR = 3_600_000

interface Harness {
  calls: string[]
  released: string[]
  hls: HlsLike & { emit: (type: string, payload: unknown) => void }
  current: UseLiveTile
}

let harness: Harness

function fakeHls() {
  const handlers = new Map<string, (event: unknown) => void>()
  const hls = {
    handlers,
    on(event: string, handler: (payload: unknown) => void) {
      handlers.set(event, handler)
    },
    destroy: vi.fn(),
    loadSource: vi.fn(),
    attachMedia: vi.fn(),
    startLoad: vi.fn(),
    stopLoad: vi.fn(),
    recoverMediaError: vi.fn(),
    emit(type: string, payload: unknown) {
      handlers.get(type)?.(payload)
    },
  } as unknown as HlsLike & { emit: (type: string, payload: unknown) => void }
  return hls
}

function descriptor(
  over: Partial<CameraLiveStreamView> = {},
): CameraLiveStreamView {
  return {
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
    // Defaults to a signature that has effectively just been issued, so the
    // renewal timers are far in the future unless a test says otherwise.
    expires_at: new Date(Date.now() + HOUR).toISOString(),
    source_codec: "h264",
    codec: "h264",
    width: 640,
    height: 360,
    fps: 15,
    has_audio: false,
    ice_servers: [],
    ice_error: null,
    compatibility: null,
    compatibility_lease_id: null,
    compatibility_acceleration: null,
    ...over,
  }
}

let nextDescriptor: CameraLiveStreamView
let fetchError: Error | null = null

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  harness = { calls: [], released: [], hls: fakeHls(), current: null as never }
  nextDescriptor = descriptor()
  fetchError = null

  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes("/live/session/")) {
        if (url.includes("keepalive")) {
          harness.calls.push("keepalive")
          return new Response(
            JSON.stringify({ expires_at: new Date(Date.now() + HOUR).toISOString() }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          )
        }
        harness.released.push(url)
        return new Response(null, { status: 204 })
      }
      if (url.includes("/live")) {
        harness.calls.push("resolve")
        if (fetchError) throw fetchError
        return new Response(JSON.stringify(nextDescriptor), {
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
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

function Tile({ cameraId = "cam-1" }: { cameraId?: string | null }) {
  harness.current = useLiveTile({
    cameraId,
    createHls: () => harness.hls,
    capabilities: {
      webrtc: true,
      webrtcH264: true,
      hls: true,
      hlsH264: true,
    },
  })
  const { state, videoRef, retryNow } = harness.current
  return (
    <div>
      <video ref={videoRef} data-testid="video" />
      <span data-testid="state">{state.kind}</span>
      {state.kind === "unavailable" ? (
        <>
          <span data-testid="reason">{state.reason}</span>
          <button onClick={retryNow}>重试</button>
        </>
      ) : null}
    </div>
  )
}

describe("useLiveTile", () => {
  it("reaches a playing state once a frame arrives", async () => {
    render(<Tile />)
    await waitFor(() => expect(screen.getByTestId("state").textContent).toBe("starting"))

    // The media element is what decides "playing"; the gate cannot assume it.
    act(() => {
      const video = screen.getByTestId("video")
      Object.defineProperty(video, "readyState", { value: 4, configurable: true })
      video.dispatchEvent(new Event("canplay"))
    })

    await waitFor(() =>
      expect(screen.getByTestId("state").textContent).toBe("playing"),
    )
    expect(harness.hls.loadSource).toHaveBeenCalledWith(
      "/zlm/zero-nvr/live_0/hls.m3u8?zn_sig=abc",
    )
  })

  it("does not call the backend when there is no camera", async () => {
    render(<Tile cameraId={null} />)
    await act(async () => {
      await Promise.resolve()
    })
    expect(harness.calls).not.toContain("resolve")
  })

  it("names the reason when no first frame arrives", async () => {
    render(<Tile />)
    await waitFor(() => expect(screen.getByTestId("state").textContent).toBe("starting"))

    await act(async () => {
      await vi.advanceTimersByTimeAsync(6_100)
    })

    await waitFor(() => {
      expect(screen.getByTestId("state").textContent).toBe("unavailable")
    })
    // Silence here is the black tile this whole path exists to prevent.
    expect(screen.getByTestId("reason").textContent).toContain("未收到画面")
  })

  it("offers a retry that runs immediately", async () => {
    fetchError = new Error("boom")
    render(<Tile />)

    await waitFor(() => {
      expect(screen.getByTestId("state").textContent).toBe("unavailable")
    })

    fetchError = null
    const before = harness.calls.filter((c) => c === "resolve").length
    act(() => {
      screen.getByRole("button", { name: "重试" }).click()
    })

    await waitFor(() => {
      expect(
        harness.calls.filter((c) => c === "resolve").length,
      ).toBeGreaterThan(before)
    })
  })

  it("re-resolves before the HLS signature lapses", async () => {
    // Signature valid for ten minutes: the tile has to refresh it well before
    // that, because a keepalive alone will not.
    nextDescriptor = descriptor({
      expires_at: new Date(Date.now() + 10 * 60 * 1000).toISOString(),
    })
    render(<Tile />)

    await waitFor(() => expect(screen.getByTestId("state").textContent).toBe("starting"))
    const initial = harness.calls.filter((c) => c === "resolve").length

    await act(async () => {
      await vi.advanceTimersByTimeAsync(8 * 60 * 1000)
    })

    await waitFor(() => {
      expect(
        harness.calls.filter((c) => c === "resolve").length,
      ).toBeGreaterThan(initial)
    })
  })

  it("renews the media session without disturbing playback", async () => {
    nextDescriptor = descriptor({
      expires_at: new Date(Date.now() + 4 * 60 * 1000).toISOString(),
    })
    render(<Tile />)
    await waitFor(() => expect(screen.getByTestId("state").textContent).toBe("starting"))

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3 * 60 * 1000)
    })

    expect(harness.calls).toContain("keepalive")
  })

  it("releases the previous session when re-resolving", async () => {
    nextDescriptor = descriptor({
      expires_at: new Date(Date.now() + 5 * 60 * 1000).toISOString(),
    })
    render(<Tile />)
    await waitFor(() => expect(screen.getByTestId("state").textContent).toBe("starting"))

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3 * 60 * 1000)
    })

    // Holding a lease on a stream nobody watches is how the media server runs
    // out of sessions on a long-lived wall.
    expect(harness.released.length).toBeGreaterThan(0)
    expect(harness.released[0]).toContain("session-1")
  })

  it("releases the session on unmount", async () => {
    const { unmount } = render(<Tile />)
    await waitFor(() => expect(screen.getByTestId("state").textContent).toBe("starting"))

    unmount()
    await act(async () => {
      await Promise.resolve()
    })

    expect(harness.released.some((url) => url.includes("session-1"))).toBe(true)
  })

  it("reports a fast-preview fallback for a source it cannot play", async () => {
    nextDescriptor = descriptor({ codec: "h265", source_codec: "h265" })
    render(<Tile />)

    await waitFor(() => {
      expect(screen.getByTestId("reason").textContent).toContain("快速预览")
    })
    // No playback is attempted at all, so there is nothing to go black.
    expect(harness.hls.loadSource).not.toHaveBeenCalled()
  })

  it("recovers on its own after a transient resolve failure", async () => {
    fetchError = new Error("network down")
    render(<Tile />)

    await waitFor(() => {
      expect(screen.getByTestId("state").textContent).toBe("unavailable")
    })
    const failed = harness.calls.filter((c) => c === "resolve").length

    fetchError = null
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_000)
    })

    await waitFor(() => {
      expect(harness.calls.filter((c) => c === "resolve").length).toBeGreaterThan(
        failed,
      )
    })
  })
})

describe("preview wall resolution table", () => {
  it("matches what the server actually schedules", () => {
    // Hard-coded on the client today (G-13); asserted so a backend change
    // has to be made deliberately in both places.
    expect(PREVIEW_WALL_RESOLUTION[4]).toEqual({ width: 640, fps: 5 })
  })
})
