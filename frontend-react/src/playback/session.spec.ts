import { describe, expect, it } from "vitest"

import type {
  PlaybackTimelineView,
  SegmentAvailability,
  TimelineGapReason,
} from "../api/playback"
import {
  gapAt,
  instantMs,
  nextPlayableInstant,
  previousPlayableInstant,
  segmentNeedsRestore,
  selectSegmentAt,
} from "./session"

const T = instantMs

function segment(
  id: string,
  start: string,
  end: string,
  availability: SegmentAvailability = "local",
) {
  return {
    id,
    playback_ref: id,
    start_at: start,
    end_at: end,
    availability,
  }
}

function timeline(
  segments: ReturnType<typeof segment>[],
  gaps: Array<{
    start_at: string
    end_at: string
    reason: TimelineGapReason
  }> = [],
): PlaybackTimelineView {
  return {
    camera_id: "cam-1",
    detail: "minute",
    range: { start_at: "2026-10-01T00:00:00Z", end_at: "2026-10-01T06:00:00Z" },
    segments,
    recording_ranges: [],
    gaps,
    events: [],
  }
}

const S1 = segment("s1", "2026-10-01T00:00:00Z", "2026-10-01T00:05:00Z")
const S2 = segment("s2", "2026-10-01T00:05:00Z", "2026-10-01T00:10:00Z")

describe("selectSegmentAt", () => {
  it("finds the covering segment and reports a millisecond offset", () => {
    const result = selectSegmentAt(timeline([S1, S2]), T("2026-10-01T00:02:30Z"))
    expect(result?.segment.id).toBe("s1")
    // Milliseconds, not seconds: 2 min 30 s into the clip is 150000.
    expect(result?.offsetMs).toBe(150_000)
  })

  it("treats segment ranges as half-open", () => {
    // At the exact boundary the previous segment has ended; the next owns it.
    const result = selectSegmentAt(timeline([S1, S2]), T("2026-10-01T00:05:00Z"))
    expect(result?.segment.id).toBe("s2")
    expect(result?.offsetMs).toBe(0)
  })

  it("returns null inside a gap rather than a neighbouring segment", () => {
    const result = selectSegmentAt(
      timeline([S1], [
        {
          start_at: "2026-10-01T00:05:00Z",
          end_at: "2026-10-01T00:20:00Z",
          reason: "purged",
        },
      ]),
      T("2026-10-01T00:10:00Z"),
    )
    expect(result).toBeNull()
  })

  it("is not fooled by an unsorted response", () => {
    const result = selectSegmentAt(
      timeline([S2, S1]),
      T("2026-10-01T00:02:30Z"),
    )
    expect(result?.segment.id).toBe("s1")
  })

  it("tolerates a null timeline", () => {
    expect(selectSegmentAt(null, 0)).toBeNull()
  })

  it("never returns a negative offset", () => {
    // A segment whose start_at parses slightly after the requested instant
    // would otherwise produce a negative seek, which some decoders reject.
    const skewed = segment("s3", "2026-10-01T00:02:00Z", "2026-10-01T00:07:00Z")
    const result = selectSegmentAt(timeline([skewed]), T("2026-10-01T00:01:00Z"))
    expect(result).toBeNull()
  })
})

describe("segmentNeedsRestore", () => {
  it("flags archives that are not local yet", () => {
    expect(segmentNeedsRestore(segment("a", "x", "y", "remote"))).toBe(true)
    expect(segmentNeedsRestore(segment("a", "x", "y", "cached_remote"))).toBe(true)
  })

  it("does not flag local or permanently lost media", () => {
    expect(segmentNeedsRestore(segment("a", "x", "y", "local"))).toBe(false)
    expect(segmentNeedsRestore(segment("a", "x", "y", "purged"))).toBe(false)
    expect(segmentNeedsRestore(segment("a", "x", "y", "corrupted"))).toBe(false)
  })
})

describe("gapAt", () => {
  it("identifies the gap covering an instant", () => {
    const t = timeline([S1], [
      {
        start_at: "2026-10-01T00:05:00Z",
        end_at: "2026-10-01T00:20:00Z",
        reason: "storage_failure",
      },
    ])
    expect(gapAt(t, T("2026-10-01T00:06:00Z"))?.reason).toBe("storage_failure")
    expect(gapAt(t, T("2026-10-01T00:04:00Z"))).toBeNull()
  })
})

describe("jump targets around a gap", () => {
  const t = timeline([S1, S2])

  it("finds the next playable instant", () => {
    expect(nextPlayableInstant(t, T("2026-10-01T00:02:00Z"))).toBe(
      T("2026-10-01T00:05:00Z"),
    )
  })

  it("finds the previous playable instant", () => {
    expect(previousPlayableInstant(t, T("2026-10-01T00:08:00Z"))).toBe(
      T("2026-10-01T00:05:00Z"),
    )
  })

  it("returns null at the trailing edge rather than inventing a target", () => {
    // Nothing ahead of the last segment is a real end state.
    expect(nextPlayableInstant(t, T("2026-10-01T00:09:00Z"))).toBeNull()
    expect(previousPlayableInstant(t, T("2026-10-01T00:01:00Z"))).toBeNull()
  })

  it("keeps stepping backwards on repeated presses", () => {
    const three = timeline([
      S1,
      S2,
      segment("s3", "2026-10-01T00:10:00Z", "2026-10-01T00:15:00Z"),
    ])

    const first = previousPlayableInstant(three, T("2026-10-01T00:12:00Z"))
    expect(first).toBe(T("2026-10-01T00:10:00Z"))

    // The second press must move, not hand back the same instant.
    const second = previousPlayableInstant(three, first!)
    expect(second).toBe(T("2026-10-01T00:05:00Z"))

    // And a third lands on the start of the range, below which there is
    // nothing to step back to — a null here is the honest answer, not a
    // jump to the epoch.
    expect(previousPlayableInstant(three, second!)).toBeNull()
  })

  it("tolerates a null timeline", () => {
    expect(nextPlayableInstant(null, 0)).toBeNull()
    expect(previousPlayableInstant(null, 0)).toBeNull()
  })
})
