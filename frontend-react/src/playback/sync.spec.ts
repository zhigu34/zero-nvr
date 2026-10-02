import { describe, expect, it } from "vitest"

import type { PlaybackTimelineView, SegmentAvailability } from "../api/playback"
import {
  blocksStrict,
  findNextPlayableTime,
  isStrictBarrierActive,
  resolveTileSyncState,
  strictBlockers,
  type TileSignals,
} from "./sync"

const idle: TileSignals = {
  loading: false,
  failure: null,
  buffering: false,
  mediaReady: false,
  resolveStatus: null,
}

describe("resolveTileSyncState", () => {
  it("reports a failure ahead of anything else in flight", () => {
    // A retry may be loading, but the operator still needs to see the tile is
    // broken rather than "working on it".
    expect(
      resolveTileSyncState({
        ...idle,
        failure: "resolve failed",
        loading: true,
        resolveStatus: "playable",
        mediaReady: true,
      }),
    ).toBe("unavailable")
  })

  it("walks the states in urgency order", () => {
    expect(resolveTileSyncState({ ...idle, loading: true })).toBe("resolving")
    expect(
      resolveTileSyncState({ ...idle, resolveStatus: "pending" }),
    ).toBe("pending")
    expect(resolveTileSyncState({ ...idle, resolveStatus: "gap" })).toBe("gap")
    expect(resolveTileSyncState({ ...idle, buffering: true })).toBe("buffering")
    expect(
      resolveTileSyncState({ ...idle, resolveStatus: "playable", mediaReady: true }),
    ).toBe("ready")
  })

  it("prefers a canonical gap over a transient buffer", () => {
    // The gap is a fact about the schedule; the buffer is incidental.
    expect(
      resolveTileSyncState({
        ...idle,
        resolveStatus: "gap",
        buffering: true,
      }),
    ).toBe("gap")
  })

  it("does not call a tile ready until it has painted a frame", () => {
    expect(
      resolveTileSyncState({ ...idle, resolveStatus: "playable" }),
    ).toBe("resolving")
  })

  it("defaults to resolving when nothing has resolved yet", () => {
    expect(resolveTileSyncState(idle)).toBe("resolving")
  })
})

describe("strict barrier", () => {
  it("treats a gap as a non-blocker", () => {
    // That camera will never have media at this instant; blocking on it would
    // freeze the wall permanently.
    expect(blocksStrict("gap")).toBe(false)
  })

  it("treats a ready tile as a non-blocker", () => {
    expect(blocksStrict("ready")).toBe(false)
  })

  it("blocks on every other state", () => {
    for (const state of ["unavailable", "resolving", "pending", "buffering"] as const) {
      expect(blocksStrict(state)).toBe(true)
    }
  })

  it("counts a camera that never reported as a blocker", () => {
    // Fail-closed: a tile that mounted late must not be assumed ready, since
    // "ready" is what releases the barrier.
    const blockers = strictBlockers(["a", "b", "c"], new Map([["a", "ready"]]))
    expect(blockers).toEqual(["b", "c"])
  })

  it("reports no blockers when everyone is ready or gapped", () => {
    const states = new Map([
      ["a", "ready" as const],
      ["b", "gap" as const],
    ])
    expect(strictBlockers(["a", "b"], states)).toEqual([])
  })

  it("only holds the barrier in multi-camera strict playback", () => {
    const args = {
      multiCamera: true,
      strictMode: true,
      playbackRequested: true,
      blockers: ["a"],
    }
    expect(isStrictBarrierActive(args)).toBe(true)

    expect(isStrictBarrierActive({ ...args, multiCamera: false })).toBe(false)
    expect(isStrictBarrierActive({ ...args, strictMode: false })).toBe(false)
    // Paused intent means there is nothing to hold back.
    expect(isStrictBarrierActive({ ...args, playbackRequested: false })).toBe(false)
    expect(isStrictBarrierActive({ ...args, blockers: [] })).toBe(false)
  })
})

describe("findNextPlayableTime", () => {
  function range(
    start: string,
    end: string,
    availability: SegmentAvailability = "local",
  ) {
    return { start_at: start, end_at: end, availability }
  }

  function timeline(
    id: string,
    recordingRanges: ReturnType<typeof range>[],
  ): PlaybackTimelineView {
    return {
      camera_id: id,
      detail: "minute",
      range: {
        start_at: "2026-10-01T00:00:00Z",
        end_at: "2026-10-01T06:00:00Z",
      },
      segments: [],
      recording_ranges: recordingRanges,
      gaps: [],
      events: [],
    }
  }

  const at = (iso: string) => new Date(iso).getTime()

  it("does not skip while any camera still has media", () => {
    // Cutting the shared clock here would abandon a working camera.
    const result = findNextPlayableTime(
      [
        timeline("a", [range("2026-10-01T00:00:00Z", "2026-10-01T02:00:00Z")]),
        timeline("b", [range("2026-10-01T03:00:00Z", "2026-10-01T04:00:00Z")]),
      ],
      at("2026-10-01T00:30:00Z"),
    )
    expect(result).toBeNull()
  })

  it("skips to the earliest point where any camera resumes", () => {
    const result = findNextPlayableTime(
      [
        timeline("a", [range("2026-10-01T02:00:00Z", "2026-10-01T04:00:00Z")]),
        timeline("b", [range("2026-10-01T01:00:00Z", "2026-10-01T03:00:00Z")]),
      ],
      at("2026-10-01T00:30:00Z"),
    )
    // Earliest, not latest. Jumping to 01:00 restores camera b while camera a
    // stays in its gap until 02:00, and those recover independently — which is
    // the whole point of tolerant mode. Waiting for the intersection instead
    // would keep every tile black until 02:00 for no benefit.
    expect(result).toBe(at("2026-10-01T01:00:00Z"))
  })

  it("ignores ranges that are known-unplayable", () => {
    const result = findNextPlayableTime(
      [
        timeline("a", [
          range("2026-10-01T00:40:00Z", "2026-10-01T00:50:00Z", "purged"),
          range("2026-10-01T02:00:00Z", "2026-10-01T03:00:00Z", "local"),
        ]),
      ],
      at("2026-10-01T00:30:00Z"),
    )
    expect(result).toBe(at("2026-10-01T02:00:00Z"))
  })

  it("counts a remote-only range as a resume point", () => {
    // It is playable, just not yet local — the resolve flow will restore it.
    const result = findNextPlayableTime(
      [timeline("a", [range("2026-10-01T01:00:00Z", "2026-10-01T02:00:00Z", "remote")])],
      at("2026-10-01T00:30:00Z"),
    )
    expect(result).toBe(at("2026-10-01T01:00:00Z"))
  })

  it("returns null when there is nothing ahead to jump to", () => {
    expect(
      findNextPlayableTime(
        [timeline("a", [range("2026-10-01T00:00:00Z", "2026-10-01T00:20:00Z")])],
        at("2026-10-01T00:30:00Z"),
      ),
    ).toBeNull()
  })

  it("returns null for an empty wall", () => {
    expect(findNextPlayableTime([], at("2026-10-01T00:30:00Z"))).toBeNull()
  })

  it("treats a range end as exclusive", () => {
    // `[start, end)` — a camera whose range ends exactly now has nothing left.
    const result = findNextPlayableTime(
      [timeline("a", [range("2026-10-01T00:00:00Z", "2026-10-01T00:30:00Z")])],
      at("2026-10-01T00:30:00Z"),
    )
    expect(result).toBeNull()
  })
})
