import { describe, expect, it } from "vitest"

import {
  axisTicks,
  bucketMinutes,
  defaultDetailFor,
  detailWarning,
  resolveRange,
  todayRange,
  RANGE_PRESETS,
} from "./timelineRange"

/**
 * The backend has no cap on range or on how many events come back, so these
 * rules are the only thing keeping a week-long per-event request from being
 * issued. They are pinned against a fixed clock rather than `Date.now()`.
 */

const NOW = Date.parse("2026-10-02T15:30:00.000Z")
const HOUR = 60 * 60 * 1000

describe("resolveRange", () => {
  it("starts today at local midnight, not at UTC midnight", () => {
    const range = todayRange(NOW)
    const start = new Date(range.from)
    expect(start.getHours()).toBe(0)
    expect(start.getMinutes()).toBe(0)
    expect(range.to).toBe(new Date(NOW).toISOString())
  })

  it("spans 24 hours and 7 days back from now", () => {
    const day = resolveRange("24h", undefined, NOW)
    expect(new Date(day.to).getTime() - new Date(day.from).getTime()).toBe(24 * HOUR)
    const week = resolveRange("7d", undefined, NOW)
    expect(new Date(week.to).getTime() - new Date(week.from).getTime()).toBe(7 * 24 * HOUR)
  })

  it("passes a custom range through untouched", () => {
    const custom = { from: "2026-01-01T00:00:00.000Z", to: "2026-01-02T00:00:00.000Z" }
    expect(resolveRange("custom", custom, NOW)).toEqual(custom)
  })

  it("falls back to today when a custom range is incomplete", () => {
    // A half-filled custom range would otherwise be sent as an empty filter
    // and read as "the whole archive".
    const range = resolveRange("custom", { from: "2026-01-01T00:00:00.000Z" }, NOW)
    expect(new Date(range.from).getHours()).toBe(0)
  })

  it("never returns a backwards range", () => {
    for (const preset of RANGE_PRESETS) {
      const range = resolveRange(preset.value, undefined, NOW)
      expect(
        new Date(range.to).getTime(),
      ).toBeGreaterThan(new Date(range.from).getTime())
    }
  })
})

describe("bucketMinutes", () => {
  it("documents that the detail names do not describe the bucket", () => {
    // `day` buckets by the hour and `hour` by five minutes
    // (`timeline.py:414-418`). Anyone assuming otherwise will pick a
    // granularity and get a different one.
    expect(bucketMinutes("day")).toBe(60)
    expect(bucketMinutes("hour")).toBe(5)
    expect(bucketMinutes("minute")).toBeNull()
  })
})

describe("defaultDetailFor", () => {
  it("coarsens as the range widens", () => {
    expect(defaultDetailFor(2 * HOUR)).toBe("minute")
    expect(defaultDetailFor(24 * HOUR)).toBe("hour")
    expect(defaultDetailFor(7 * 24 * HOUR)).toBe("day")
  })

  it("never picks a granularity the range cannot justify", () => {
    for (const hours of [1, 3, 6, 12, 24, 48, 72, 168]) {
      const detail = defaultDetailFor(hours * HOUR)
      if (detail === "minute") expect(hours).toBeLessThanOrEqual(6)
    }
  })
})

describe("detailWarning", () => {
  it("warns before a per-event request over a wide range", () => {
    expect(detailWarning(7 * 24 * HOUR, "minute")).toContain("成千上万")
    expect(detailWarning(24 * HOUR, "minute")).toContain("上千")
  })

  it("stays quiet for a short range and for any bucketed level", () => {
    expect(detailWarning(3 * HOUR, "minute")).toBeNull()
    expect(detailWarning(7 * 24 * HOUR, "day")).toBeNull()
    expect(detailWarning(7 * 24 * HOUR, "hour")).toBeNull()
  })
})

describe("axisTicks", () => {
  it("snaps to whole hours rather than to even fractions", () => {
    const start = Date.parse("2026-10-02T09:17:00.000Z")
    const end = Date.parse("2026-10-02T12:43:00.000Z")
    const ticks = axisTicks(start, end, 4)
    expect(ticks.length).toBeGreaterThan(0)
    for (const tick of ticks) {
      const d = new Date(tick.ms)
      expect(d.getMinutes()).toBe(0)
      expect(d.getSeconds()).toBe(0)
    }
  })

  it("stays inside the requested range", () => {
    const start = Date.parse("2026-10-01T00:00:00.000Z")
    const end = Date.parse("2026-10-03T00:00:00.000Z")
    for (const tick of axisTicks(start, end, 8)) {
      expect(tick.ms).toBeGreaterThanOrEqual(start)
      expect(tick.ms).toBeLessThanOrEqual(end)
    }
  })

  it("labels a multi-day span by date, not by clock time", () => {
    const start = Date.parse("2026-10-01T00:00:00.000Z")
    const end = Date.parse("2026-10-08T00:00:00.000Z")
    const ticks = axisTicks(start, end, 7)
    expect(ticks.every((t) => /\d/.test(t.label))).toBe(true)
    // A week axis must not read "00:00" seven times.
    expect(new Set(ticks.map((t) => t.label)).size).toBe(ticks.length)
  })

  it("returns nothing for a degenerate range instead of looping", () => {
    expect(axisTicks(1000, 1000)).toEqual([])
    expect(axisTicks(2000, 1000)).toEqual([])
    expect(axisTicks(Number.NaN, Number.NaN)).toEqual([])
  })
})
