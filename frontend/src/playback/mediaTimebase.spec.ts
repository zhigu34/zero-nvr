import { describe, expect, it } from "vitest"

import {
  absoluteMediaTimeMs,
  MediaTimelineOriginTracker,
  mediaTimelineOriginSeconds,
  mediaTimeSecondsForAbsoluteMs
} from "./mediaTimebase"

describe("recording media timebase", () => {
  it("does not apply a nonzero fMP4 timestamp origin twice", () => {
    expect(
      absoluteMediaTimeMs(
        1_600_000,
        125.5,
        123.5
      )
    ).toBe(1_602_000)
  })

  it("seeks on the browser media timeline when its origin is nonzero", () => {
    expect(
      mediaTimeSecondsForAbsoluteMs(
        1_600_000,
        1_602_000,
        123.5
      )
    ).toBe(125.5)
  })

  it("preserves the ordinary zero-based MP4 timebase", () => {
    expect(
      absoluteMediaTimeMs(1_600_000, 2, 0)
    ).toBe(1_602_000)
    expect(
      mediaTimeSecondsForAbsoluteMs(
        1_600_000,
        1_602_000,
        0
      )
    ).toBe(2)
  })

  it("uses the first seekable timestamp when playback already advanced", () => {
    expect(
      mediaTimelineOriginSeconds(125.5, 123.5)
    ).toBe(123.5)
  })

  it("falls back to currentTime before a seekable range exists", () => {
    expect(
      mediaTimelineOriginSeconds(7.25, null)
    ).toBe(7.25)
  })

  it("replaces a provisional origin when canplay reveals the media timeline", () => {
    const tracker = new MediaTimelineOriginTracker()

    expect(tracker.capture(0, false)).toBe(0)
    expect(tracker.capture(123.5, true)).toBe(123.5)
    expect(tracker.capture(124, false)).toBe(123.5)
  })
})
