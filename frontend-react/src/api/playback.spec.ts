import { afterEach, describe, expect, it, vi } from "vitest"

import {
  MAX_ALIGNED_CAMERAS,
  MIN_ALIGNED_CAMERAS,
  availabilityLabel,
  gapReasonLabel,
  getAlignedTimeline,
  listCameraRecordings,
  resolveSegmentPlayback,
  GAP_REASON_LABEL,
  type PlaybackResolve,
  type TimelineGapReason,
} from "./playback"
import {
  PREVIEW_FRAME_HEADER_BYTES,
  PREVIEW_WALL_RESOLUTION,
  PREVIEW_WALL_SLOTS,
  describeLiveSource,
  getCameraLiveStream,
  parsePreviewFrame,
  ptzMove,
  type CameraLiveStreamView,
} from "./live"

/**
 * Media contracts have the sharpest edges in the whole API surface: a
 * millisecond/second mix-up seeks a thousand times too far, and a missing
 * discriminant turns a restore-in-progress into a permanently black tile.
 * These pin the wire shape and the unit scales.
 */

function captureFetch() {
  const calls: { url: string; body: unknown }[] = []
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({
        url: String(input),
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      })
      return new Response("{}", {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    }),
  )
  return calls
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("recording segment paging", () => {
  it("is cursor paginated and never sends a page index", async () => {
    const calls = captureFetch()
    await listCameraRecordings("cam-1", {
      from: "2026-10-01T00:00:00Z",
      cursor: "eyJzdGFydGVkX2F0IjoiLi4uIn0",
      limit: 50,
    })

    expect(calls[0].url).toContain("cursor=")
    expect(calls[0].url).toContain("limit=50")
    expect(calls[0].url).not.toContain("page=")
    expect(calls[0].url).not.toContain("offset=")
  })
})

describe("POST /recordings/{id}/playback/resolve", () => {
  it("sends offset in milliseconds, not seconds", async () => {
    const calls = captureFetch()
    await resolveSegmentPlayback("seg-1", 90_000)

    // A 90-second offset inside a 5-minute segment. Sending 90 instead would
    // seek to 90ms and look like a broken player.
    expect(calls[0].body).toEqual({ offset_ms: 90_000 })
  })
})

describe("PlaybackResolve is a discriminated union", () => {
  it("exposes url and offset_ms only on the playable branch", () => {
    const playable: PlaybackResolve = {
      status: "playable",
      segment_id: "seg-1",
      segment_start_at: "2026-10-01T00:00:00Z",
      offset_ms: 0,
      transport: "mp4",
      url: "/api/v1/recordings/seg-1/media",
      expires_at: "2026-10-01T00:05:00Z",
      codec: "h264",
    }

    if (playable.status !== "playable") throw new Error("unreachable")
    expect(playable.url).toContain("/media")
    expect(playable.offset_ms).toBe(0)
  })

  it("carries a retry hint while a remote restore is running", () => {
    const pending: PlaybackResolve = {
      status: "pending",
      reason: "remote_restore_required",
      segment_id: "seg-9",
      retry_after_ms: 2_000,
    }

    if (pending.status !== "pending") throw new Error("unreachable")
    // The backend exposes no progress, so polling on a fixed cadence is the
    // whole contract.
    expect(pending.retry_after_ms).toBeGreaterThan(0)
    expect(pending.reason).toBe("remote_restore_required")
  })

  it("distinguishes a real gap from a restore in progress", () => {
    const gap: PlaybackResolve = {
      status: "gap",
      reason: "purged",
      previous_at: "2026-10-01T00:00:00Z",
      next_at: "2026-10-01T01:00:00Z",
    }

    // A gap is terminal for that instant; a pending restore is not. Collapsing
    // them is how a purged segment ends up polling forever.
    expect(gap.status).toBe("gap")
    expect(gap.next_at).toBeTruthy()
  })
})

describe("aligned timeline", () => {
  it("posts camera ids as a body array", async () => {
    const calls = captureFetch()
    await getAlignedTimeline({
      cameraIds: ["cam-1", "cam-2"],
      from: "2026-10-01T00:00:00Z",
      to: "2026-10-01T06:00:00Z",
      detail: "hour",
    })

    expect(calls[0].url).toContain("/playback/timeline")
    expect(calls[0].body).toMatchObject({
      camera_ids: ["cam-1", "cam-2"],
      detail: "hour",
    })
  })

  it("caps the batch below the layout slot count", () => {
    // A 16-tile wall cannot be fetched in one aligned call, so the UI has to
    // split it and accept that the two halves are not cross-aligned.
    expect(MAX_ALIGNED_CAMERAS).toBe(9)
    expect(MIN_ALIGNED_CAMERAS).toBe(2)
    expect(PREVIEW_WALL_SLOTS).toContain(16)
  })
})

describe("gap reasons", () => {
  it("labels every reason the timeline can emit", () => {
    const emitted: TimelineGapReason[] = [
      "not_scheduled",
      "no_event",
      "source_lost",
      "runtime_restart",
      "storage_failure",
      "missing_media",
      "purged",
      "unknown",
    ]

    for (const reason of emitted) {
      expect(GAP_REASON_LABEL[reason]).toBeTruthy()
    }
    expect(Object.keys(GAP_REASON_LABEL).sort()).toEqual(
      [...emitted].sort()
    )
  })

  it("falls back rather than rendering a raw enum for an unknown reason", () => {
    expect(gapReasonLabel("a_reason_added_next_year")).toBe("原因未知")
  })

  it("labels segment availability distinctly", () => {
    expect(availabilityLabel("local")).toBe("本地")
    expect(availabilityLabel("cached_remote")).toBe("远端（已回源）")
  })
})

describe("GET /cameras/{id}/live", () => {
  it("does not send the quality parameter the backend ignores", async () => {
    const calls = captureFetch()
    await getCameraLiveStream("cam-1", { source: "sub" })

    expect(calls[0].url).toContain("source=sub")
    // Sending `quality=high` would make the UI look like it has a quality
    // control when `_select_live_stream` never reads it.
    expect(calls[0].url).not.toContain("quality")
  })

  it("treats hls_url as a same-origin relative path", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(
          JSON.stringify({
            camera_id: "cam-1",
            profile_id: "p-1",
            source_role: "sub",
            profile_name: "640x360",
            adapter_profile_key: "k",
            purpose: "LIVE_LOW",
            transport: "hls",
            transports: ["webrtc", "hls"],
            hls_url: "/zlm/zero-nvr/live_0/hls.m3u8?zn_exp=1&zn_sig=abc",
            media_session_id: "m-1",
            expires_at: "2026-10-01T00:30:00Z",
            has_audio: false,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      ),
    )

    const stream = await getCameraLiveStream("cam-1")
    // No origin to prepend: the vite proxy keeps it first-party so the media
    // request carries the session cookie.
    expect(stream.hls_url.startsWith("/zlm/")).toBe(true)
    expect(stream.hls_url).toContain("zn_sig=")
  })
})

describe("live source presentation", () => {
  const base: CameraLiveStreamView = {
    camera_id: "cam-1",
    profile_id: "p-1",
    source_role: "sub",
    profile_name: "子码流",
    adapter_profile_key: "k",
    purpose: "LIVE_LOW",
    transport: "hls",
    transports: ["webrtc", "hls"],
    hls_url: "/zlm/x/hls.m3u8",
    media_session_id: "m-1",
    expires_at: "2026-10-01T00:30:00Z",
    source_codec: "h265",
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
  }

  it("shows the real media path instead of an SD/HD label", () => {
    const text = describeLiveSource(base)
    expect(text).toContain("子码流")
    expect(text).toContain("640×360")
    expect(text).toContain("15fps")
  })

  it("marks a compatibility transcode as such", () => {
    const text = describeLiveSource({
      ...base,
      compatibility: "h264_transcode",
      compatibility_acceleration: "nvenc",
    })
    expect(text).toContain("兼容转码")
    expect(text).toContain("nvenc")
  })
})

describe("PTZ", () => {
  it("sends normalised axes", async () => {
    const calls = captureFetch()
    await ptzMove("cam-1", { pan: -0.5, tilt: 0.25 })

    // -1.0..1.0, not degrees and not 0-100.
    expect(calls[0].body).toEqual({ pan: -0.5, tilt: 0.25 })
  })
})

describe("preview wall frames", () => {
  function buildFrame(slot: number, subscriptionId: number, payload: number[]) {
    const buffer = new ArrayBuffer(
      PREVIEW_FRAME_HEADER_BYTES + payload.length,
    )
    const view = new DataView(buffer)
    view.setUint8(0, 0x01)
    view.setUint8(1, slot)
    view.setUint32(2, subscriptionId)
    new Uint8Array(buffer, PREVIEW_FRAME_HEADER_BYTES).set(payload)
    return buffer
  }

  it("decodes the magic byte, slot and big-endian subscription id", () => {
    const frame = parsePreviewFrame(buildFrame(7, 0x01020304, [0xff, 0xd8]))

    expect(frame).not.toBeNull()
    expect(frame!.slot).toBe(7)
    expect(frame!.subscriptionId).toBe(0x01020304)
    expect([...frame!.jpeg]).toEqual([0xff, 0xd8])
  })

  it("rejects anything that is not a frame", () => {
    expect(parsePreviewFrame(buildFrame(0, 0, []))).toBeNull()

    const notAFrame = new ArrayBuffer(8)
    new DataView(notAFrame).setUint8(0, 0x02)
    expect(parsePreviewFrame(notAFrame)).toBeNull()
  })

  it("keeps a resolution budget per layout", () => {
    expect(PREVIEW_WALL_RESOLUTION[4]).toEqual({ width: 640, fps: 5 })
    expect(PREVIEW_WALL_RESOLUTION[16]).toEqual({ width: 320, fps: 2 })
  })
})
