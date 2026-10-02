import { describe, expect, it } from "vitest"

import {
  EXPORT_MAX_RANGE_MS,
  isValidTimeZone,
  localInputToUtcIso,
  utcIsoToLocalInput,
  validateExportForm,
  validateMaxDownloads,
  validateShareTtl,
} from "./exportValidation"
import { formatSpan } from "./format"

/**
 * The conversion under test is the one thing on this screen that can be wrong
 * *and still succeed*: a mis-shifted range produces a valid export of the
 * wrong eight hours. So these are pinned against explicit offsets rather than
 * against whatever the machine's local zone happens to be.
 */

const SHANGHAI = "Asia/Shanghai" // UTC+8, no DST
const NEW_YORK = "America/New_York" // UTC-5 / UTC-4, DST

describe("localInputToUtcIso", () => {
  it("shifts a wall clock by the zone offset", () => {
    expect(localInputToUtcIso("2026-10-01T14:30", SHANGHAI)).toBe(
      "2026-10-01T06:30:00.000Z",
    )
    expect(localInputToUtcIso("2026-10-01T14:30", "UTC")).toBe(
      "2026-10-01T14:30:00.000Z",
    )
  })

  it("never consults the machine's own timezone", () => {
    // Proved by breadth rather than by mutating `process.env.TZ`, which is
    // unreliable at runtime: if the host zone leaked in, at most one of these
    // could come out right, and the host is certainly not all of them.
    expect(localInputToUtcIso("2026-10-01T14:30", "Pacific/Kiritimati")).toBe(
      "2026-10-01T00:30:00.000Z", // UTC+14
    )
    expect(localInputToUtcIso("2026-10-01T14:30", "Pacific/Niue")).toBe(
      "2026-10-02T01:30:00.000Z", // UTC-11
    )
    expect(localInputToUtcIso("2026-10-01T14:30", "Asia/Kolkata")).toBe(
      "2026-10-01T09:00:00.000Z", // UTC+5:30
    )
  })

  it("picks the correct offset on each side of a DST transition", () => {
    // 2026-03-08 is the US spring-forward. 01:30 exists on neither side of
    // 02:00, so the range is chosen to straddle it without landing inside.
    expect(localInputToUtcIso("2026-03-08T03:30", NEW_YORK)).toBe(
      "2026-03-08T07:30:00.000Z",
    )
    // Same wall clock, ten days later, is a different offset.
    expect(localInputToUtcIso("2026-03-18T03:30", NEW_YORK)).toBe(
      "2026-03-18T07:30:00.000Z",
    )
  })

  it("crossing midnight rolls the date correctly", () => {
    expect(localInputToUtcIso("2026-10-02T00:15", SHANGHAI)).toBe(
      "2026-10-01T16:15:00.000Z",
    )
  })

  it("rejects input that is not a datetime-local value", () => {
    expect(localInputToUtcIso("", SHANGHAI)).toBeNull()
    expect(localInputToUtcIso("not-a-time", SHANGHAI)).toBeNull()
    expect(localInputToUtcIso("2026-10-01", SHANGHAI)).toBeNull()
    // A value that already carries an offset is not what this function takes.
    expect(localInputToUtcIso("2026-10-01T14:30:00Z", SHANGHAI)).toBeNull()
  })
})

describe("utcIsoToLocalInput", () => {
  it("renders a segment's bounds in the operator's zone", () => {
    expect(utcIsoToLocalInput("2026-10-01T02:00:00.000Z", SHANGHAI)).toBe(
      "2026-10-01T10:00",
    )
  })

  it("rolls the date back for a western zone", () => {
    expect(utcIsoToLocalInput("2026-10-01T02:00:00.000Z", NEW_YORK)).toBe(
      "2026-09-30T22:00",
    )
  })

  it("round-trips with localInputToUtcIso", () => {
    for (const zone of [SHANGHAI, NEW_YORK, "UTC", "Asia/Kolkata"]) {
      const back = utcIsoToLocalInput("2026-07-04T18:45:00.000Z", zone)
      expect(localInputToUtcIso(back, zone)).toBe("2026-07-04T18:45:00.000Z")
    }
  })

  it("returns empty rather than throwing on bad input", () => {
    expect(utcIsoToLocalInput("nope", SHANGHAI)).toBe("")
    expect(utcIsoToLocalInput("2026-10-01T02:00:00.000Z", "Nowhere/Land")).toBe("")
  })
})

describe("isValidTimeZone", () => {
  it("accepts IANA names and rejects nonsense without throwing", () => {
    expect(isValidTimeZone("Asia/Shanghai")).toBe(true)
    expect(isValidTimeZone("UTC")).toBe(true)
    expect(isValidTimeZone("Not/AZone")).toBe(false)
    expect(isValidTimeZone("")).toBe(false)
  })
})

describe("validateExportForm", () => {
  const base = {
    start: "2026-10-01T10:00",
    end: "2026-10-01T11:00",
    timeZone: SHANGHAI,
    codecMode: "auto" as const,
    gapPolicy: "skip" as const,
  }

  it("accepts a one-hour range and returns UTC bounds", () => {
    const result = validateExportForm(base)
    expect(result.ok).toBe(true)
    if (!result.ok) return
    expect(result.startUtc).toBe("2026-10-01T02:00:00.000Z")
    expect(result.endUtc).toBe("2026-10-01T03:00:00.000Z")
    expect(result.durationMs).toBe(60 * 60 * 1000)
  })

  it("reports the missing field before it measures the range", () => {
    const result = validateExportForm({ ...base, start: "" })
    expect(result).toEqual({ ok: false, error: "请选择开始时间" })
  })

  it("rejects a non-positive range the way the backend would", () => {
    expect(validateExportForm({ ...base, end: base.start })).toEqual({
      ok: false,
      error: "结束时间必须晚于开始时间",
    })
    expect(
      validateExportForm({ ...base, end: "2026-10-01T09:00" }).ok,
    ).toBe(false)
  })

  it("rejects a range over 7 days and says how long it is", () => {
    const result = validateExportForm({
      ...base,
      end: "2026-10-09T10:00",
    })
    expect(result.ok).toBe(false)
    if (result.ok) return
    expect(result.error).toContain("7 天")
    expect(result.error).toContain("8 天")
  })

  it("accepts exactly 7 days", () => {
    const result = validateExportForm({
      ...base,
      end: "2026-10-08T10:00",
    })
    expect(result.ok).toBe(true)
    if (!result.ok) return
    expect(result.durationMs).toBe(EXPORT_MAX_RANGE_MS)
  })

  it("measures the range in real time, so a DST day is 23 or 25 hours", () => {
    // Spring forward in New York: 2026-03-08 is 23 hours long. A naive
    // wall-clock subtraction would call this exactly 24 and, at the limit,
    // admit a range the backend rejects.
    const day = validateExportForm({
      ...base,
      start: "2026-03-08T00:00",
      end: "2026-03-09T00:00",
      timeZone: NEW_YORK,
    })
    expect(day.ok).toBe(true)
    if (!day.ok) return
    expect(day.durationMs).toBe(23 * 60 * 60 * 1000)
  })

  it("rejects an unusable timezone before anything else is measured", () => {
    const result = validateExportForm({ ...base, timeZone: "Nowhere/Land" })
    expect(result.ok).toBe(false)
    if (result.ok) return
    expect(result.error).toContain("时区无效")
  })
})

describe("formatSpan", () => {
  it("reads the way an operator would say it", () => {
    expect(formatSpan(45 * 60 * 1000)).toBe("45 分钟")
    expect(formatSpan(90 * 60 * 1000)).toBe("1 小时 30 分")
    expect(formatSpan(8 * 24 * 60 * 60 * 1000)).toBe("8 天 0 小时")
  })
})

describe("share limits", () => {
  it("mirrors the backend bounds", () => {
    expect(validateShareTtl(24)).toBeNull()
    expect(validateShareTtl(1)).toBeNull()
    expect(validateShareTtl(720)).toBeNull()
    expect(validateShareTtl(0)).toContain("1–720")
    expect(validateShareTtl(721)).toContain("1–720")
    expect(validateShareTtl(1.5)).toContain("整数")
  })

  it("treats an absent download cap as valid", () => {
    expect(validateMaxDownloads(null)).toBeNull()
    expect(validateMaxDownloads(1)).toBeNull()
    expect(validateMaxDownloads(100_000)).toBeNull()
    expect(validateMaxDownloads(0)).toContain("1–100000")
    expect(validateMaxDownloads(100_001)).toContain("1–100000")
  })
})
