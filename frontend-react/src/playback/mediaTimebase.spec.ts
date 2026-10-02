import { describe, expect, it } from "vitest"

import {
  absoluteMediaTimeMs,
  MediaTimelineOriginTracker,
  mediaElementSeekableStartSeconds,
  mediaTimelineOriginSeconds,
} from "./mediaTimebase"

describe("recording media timebase", () => {
  it("does not apply a nonzero fMP4 timestamp origin twice", () => {
    expect(absoluteMediaTimeMs(1_600_000, 125.5, 123.5)).toBe(1_602_000)
  })

  it("preserves the ordinary zero-based MP4 timebase", () => {
    expect(absoluteMediaTimeMs(1_600_000, 2, 0)).toBe(1_602_000)
  })

  it("uses the first seekable timestamp when playback already advanced", () => {
    expect(mediaTimelineOriginSeconds(125.5, 123.5)).toBe(123.5)
  })

  it("falls back to currentTime before a seekable range exists", () => {
    expect(mediaTimelineOriginSeconds(7.25, null)).toBe(7.25)
  })
})

describe("MediaTimelineOriginTracker", () => {
  it("keeps the first provisional reading until something better arrives", () => {
    const tracker = new MediaTimelineOriginTracker()

    expect(tracker.capture(0, "provisional")).toBe(0)
    expect(tracker.value).toBe(0)
  })

  /**
   * Regression: `loadedmetadata` can fire before the browser knows where the
   * seekable range starts, so the `currentTime` read at that moment is close
   * to zero even though the container really begins at 123.5s. A tracker that
   * treats that first reading as final locks the origin at zero and offsets
   * every later drift calculation by the whole container offset.
   */
  it("lets a strong origin replace a weak one captured at loadedmetadata", () => {
    const tracker = new MediaTimelineOriginTracker()

    // loadedmetadata: no seekable range yet, currentTime is ~0.
    expect(tracker.capture(0, "weak")).toBe(0)

    // canplay: the real range is known.
    expect(tracker.capture(123.5, "strong")).toBe(123.5)
    expect(tracker.value).toBe(123.5)
  })

  it("does not let a stale reading drag the origin backwards", () => {
    const tracker = new MediaTimelineOriginTracker()
    tracker.capture(123.5, "strong")

    // A timeupdate firing mid-playment must not re-seed the origin.
    expect(tracker.capture(130, "weak")).toBe(123.5)
    expect(tracker.capture(0, "provisional")).toBe(123.5)
    expect(tracker.value).toBe(123.5)
  })

  it("ignores a same-rank replacement", () => {
    const tracker = new MediaTimelineOriginTracker()
    tracker.capture(10, "strong")

    // Two strong candidates should not happen, but if they do the first one
    // that actually came from a real seekable range wins.
    expect(tracker.capture(50, "strong")).toBe(10)
  })

  it("upgrades from provisional straight to strong", () => {
    const tracker = new MediaTimelineOriginTracker()
    tracker.capture(0, "provisional")

    expect(tracker.capture(50, "strong")).toBe(50)
  })

  it("clamps a negative candidate to zero", () => {
    const tracker = new MediaTimelineOriginTracker()
    expect(tracker.capture(-5, "weak")).toBe(0)
  })

  it("falls back rather than propagating a non-finite candidate", () => {
    const tracker = new MediaTimelineOriginTracker()
    tracker.capture(Number.NaN, "strong")

    expect(Number.isFinite(tracker.value)).toBe(true)
  })

  it("starts clean after a reset", () => {
    const tracker = new MediaTimelineOriginTracker()
    tracker.capture(123.5, "strong")
    tracker.reset()

    expect(tracker.value).toBeNull()
    // The confidence must reset too, otherwise a new element would inherit
    // the old element's "strong" standing and reject its own first reading.
    expect(tracker.capture(7, "provisional")).toBe(7)
  })

  it("promotes an element reading to strong once a range exists", () => {
    const fake = {
      currentTime: 0,
      seekable: { length: 1, start: () => 123.5 },
    } as unknown as HTMLMediaElement

    const tracker = new MediaTimelineOriginTracker()
    expect(tracker.captureFromElement(fake)).toBe(123.5)
    expect(tracker.value).toBe(123.5)
  })

  it("falls back to a weak reading when the element has no range yet", () => {
    const fake = {
      currentTime: 0,
      seekable: { length: 0 },
    } as unknown as HTMLMediaElement

    const tracker = new MediaTimelineOriginTracker()
    expect(tracker.captureFromElement(fake)).toBe(0)
    // Still replaceable later.
    expect(tracker.capture(123.5, "strong")).toBe(123.5)
  })

  it("survives an element that throws on its seekable range", () => {
    const fake = {
      currentTime: 4,
      get seekable(): TimeRanges {
        throw new Error("detached")
      },
    } as unknown as HTMLMediaElement

    expect(mediaElementSeekableStartSeconds(fake)).toBeNull()
    expect(mediaTimelineOriginSeconds(fake.currentTime, null)).toBe(4)
  })
})
