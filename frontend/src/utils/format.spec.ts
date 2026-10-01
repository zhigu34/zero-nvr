import { describe, expect, it } from "vitest"

import {
  DATE_TIME_MINUTES,
  DATE_TIME_SECONDS,
  TIME_ONLY,
  formatBytes,
  formatBytesAdaptive,
  formatDateTime
} from "./format"

describe("formatBytes", () => {
  it("renders whole bytes without a decimal", () => {
    expect(formatBytes(0)).toBe("0 B")
    expect(formatBytes(512)).toBe("512 B")
  })

  it("scales to the largest fitting unit with one decimal", () => {
    expect(formatBytes(1024)).toBe("1.0 KB")
    expect(formatBytes(1536)).toBe("1.5 KB")
    expect(formatBytes(1024 ** 3)).toBe("1.0 GB")
    expect(formatBytes(1024 ** 4)).toBe("1.0 TB")
  })

  it("falls back for a missing value", () => {
    // The previous inline copies differed on `undefined`: one returned the
    // string "undefined B". Both cases now use the fallback.
    expect(formatBytes(null)).toBe("—")
    expect(formatBytes(undefined)).toBe("—")
    expect(formatBytes(null, { fallback: "n/a" })).toBe("n/a")
  })
})

describe("formatBytesAdaptive", () => {
  it("scales precision with magnitude", () => {
    expect(formatBytesAdaptive(512)).toBe("512 B")
    expect(formatBytesAdaptive(1536)).toBe("1.50 KB")
    expect(formatBytesAdaptive(10 * 1024)).toBe("10.0 KB")
    expect(formatBytesAdaptive(200 * 1024)).toBe("200 KB")
  })

  it("supports peta-bytes for large arrays", () => {
    expect(formatBytesAdaptive(1024 ** 5)).toBe("1.00 PB")
  })

  it("falls back for missing or non-finite values", () => {
    expect(formatBytesAdaptive(null)).toBe("—")
    expect(formatBytesAdaptive(Number.NaN)).toBe("—")
    expect(formatBytesAdaptive(Number.POSITIVE_INFINITY)).toBe("—")
  })
})

describe("formatDateTime", () => {
  const instant = "2026-09-20T17:30:45Z"
  // Pin the zone: the runtime's local zone would otherwise shift the rendered
  // day and hour and make the assertions depend on where the suite runs.
  const UTC = { timeZone: "UTC" } as const

  it("includes seconds with the seconds preset", () => {
    const rendered = formatDateTime(
      instant,
      { ...DATE_TIME_SECONDS, ...UTC },
      { locale: "en-GB" }
    )
    expect(rendered).toMatch(/17:30:45/)
    expect(rendered).toMatch(/20/)
  })

  it("omits seconds with the minutes preset", () => {
    const rendered = formatDateTime(
      instant,
      { ...DATE_TIME_MINUTES, ...UTC },
      { locale: "en-GB" }
    )
    expect(rendered).toMatch(/17:30(?!:)/)
    expect(rendered).not.toMatch(/17:30:\d\d/)
  })

  it("renders time only for the time preset", () => {
    expect(
      formatDateTime(instant, { ...TIME_ONLY, ...UTC }, { locale: "en-GB" })
    ).toBe("17:30")
  })

  it("falls back for missing or unparseable input", () => {
    // The inline copies either returned a fallback or threw a RangeError from
    // Intl; the shared helper always returns the fallback.
    expect(formatDateTime(null, DATE_TIME_SECONDS)).toBe("—")
    expect(formatDateTime("not-a-date", DATE_TIME_SECONDS)).toBe("—")
    expect(
      formatDateTime("not-a-date", DATE_TIME_SECONDS, { fallback: "never" })
    ).toBe("never")
  })

  it("can echo the raw input when asked", () => {
    expect(
      formatDateTime("2026-13-45", DATE_TIME_SECONDS, { invalidAsInput: true })
    ).toBe("2026-13-45")
  })
})
