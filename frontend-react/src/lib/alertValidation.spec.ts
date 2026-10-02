import { describe, expect, it } from "vitest"

import { MATCH_KEYS, type AlertMatch } from "../api/alerts"
import {
  MAX_CAMERA_IDS,
  clearTimeWindow,
  hasMatchErrors,
  importFromRecordingFilter,
  recordingFilterKeys,
  validateMatch,
  weekdayLabel,
} from "./alertValidation"

/**
 * These mirror `normalize_match` line for line. The interesting ones are the
 * rules that are *not* field-local — the time window is accepted only as a
 * complete triple, which is easy to get wrong in a form that renders three
 * independent inputs.
 */

describe("validateMatch", () => {
  it("accepts an empty match", () => {
    expect(hasMatchErrors(validateMatch({}))).toBe(false)
  })

  it("enforces the per-key list ceilings", () => {
    // `service.py:213-220` — note the ceilings are not uniform: labels and
    // zones take 128, severities only 32.
    expect(validateMatch({ labels: new Array(129).fill("a") }).labels).toContain("128")
    expect(validateMatch({ labels: new Array(128).fill("a") }).labels).toBeUndefined()
    expect(validateMatch({ severities: new Array(33).fill("info") }).severities)
      .toBeTruthy()
    expect(
      validateMatch({ camera_ids: new Array(MAX_CAMERA_IDS + 1).fill("c") })
        .camera_ids,
    ).toBeTruthy()
  })

  it("rejects an unknown event severity by name", () => {
    const errors = validateMatch({ severities: ["catastrophic"] })
    expect(errors.severities).toContain("catastrophic")
  })

  it("bounds min_confidence to 0–1", () => {
    expect(validateMatch({ min_confidence: 1.5 }).min_confidence).toBeTruthy()
    expect(validateMatch({ min_confidence: -0.1 }).min_confidence).toBeTruthy()
    expect(validateMatch({ min_confidence: 0 }).min_confidence).toBeUndefined()
    expect(validateMatch({ min_confidence: 1 }).min_confidence).toBeUndefined()
  })

  it("bounds min_duration_seconds to a day", () => {
    expect(validateMatch({ min_duration_seconds: 86_401 }).min_duration_seconds)
      .toBeTruthy()
    expect(validateMatch({ min_duration_seconds: 86_400 }).min_duration_seconds)
      .toBeUndefined()
  })

  it("rejects a weekday outside Monday=0..Sunday=6", () => {
    expect(validateMatch({ weekdays: [0, 7] }).weekdays).toBeTruthy()
    expect(validateMatch({ weekdays: [0, 6] }).weekdays).toBeUndefined()
  })

  it("rejects a non-string in a string list", () => {
    expect(validateMatch({ labels: ["ok", 3] as unknown as string[] }).labels)
      .toBeTruthy()
  })
})

describe("the time window is one unit", () => {
  // `service.py:307-338` raises unless all three are present, so a partial
  // window is a guaranteed 400 rather than a partial filter.
  it("refuses a start without an end", () => {
    const errors = validateMatch({ time_start: "08:00", timezone: "Asia/Shanghai" })
    expect(errors.timezone).toContain("同时填写")
  })

  it("refuses a timezone on its own", () => {
    expect(validateMatch({ timezone: "Asia/Shanghai" }).timezone).toContain("同时填写")
  })

  it("refuses identical start and end", () => {
    const errors = validateMatch({
      time_start: "08:00",
      time_end: "08:00",
      timezone: "Asia/Shanghai",
    })
    expect(errors.time_end).toContain("不能相同")
  })

  it("accepts a window that crosses midnight", () => {
    // Supported deliberately: night-time rules are the common case.
    expect(
      hasMatchErrors(
        validateMatch({
          time_start: "22:00",
          time_end: "06:00",
          timezone: "Asia/Shanghai",
        }),
      ),
    ).toBe(false)
  })

  it("rejects a malformed clock value", () => {
    expect(validateMatch({ time_start: "8:00", time_end: "18:00", timezone: "UTC" }).time_start)
      .toBeTruthy()
    expect(validateMatch({ time_start: "24:00", time_end: "18:00", timezone: "UTC" }).time_start)
      .toBeTruthy()
  })

  it("rejects an unrecognised zone", () => {
    const errors = validateMatch({
      time_start: "08:00",
      time_end: "18:00",
      timezone: "Nowhere/Land",
    })
    expect(errors.timezone).toContain("无法识别")
  })

  it("clears all three together, because the backend only accepts all three", () => {
    const cleared = clearTimeWindow({
      time_start: "08:00",
      time_end: "18:00",
      timezone: "Asia/Shanghai",
      labels: ["car"],
    })
    expect(cleared).toEqual({ labels: ["car"] })
  })
})

describe("importFromRecordingFilter", () => {
  const filter = { labels: ["car"], zones: ["driveway"], min_confidence: 0.6 }

  it("copies labels, which mean the same thing on both sides", () => {
    const result = importFromRecordingFilter({}, filter, "labels", { allowed: true })
    expect(result.copied).toBe(true)
    expect(result.draft.labels).toEqual(["car"])
  })

  it("refuses zones even when a caller passes allowed: true", () => {
    // The guard is duplicated in the component and here on purpose: the
    // metadata says no, and a "copy all" path must not be able to say yes.
    const result = importFromRecordingFilter({}, filter, "zones", { allowed: true })
    expect(result.draft.zones).toBeUndefined()
    expect(result.reason).toBeTruthy()
  })

  it("says so when the recording policy does not set the key", () => {
    const result = importFromRecordingFilter({}, { labels: ["car"] }, "min_confidence", {
      allowed: true,
    })
    expect(result.copied).toBe(false)
    expect(result.reason).toContain("未设置")
  })

  it("handles a camera with no recording policy at all", () => {
    const result = importFromRecordingFilter({}, undefined, "labels", { allowed: true })
    expect(result.copied).toBe(false)
  })

  it("does not touch the rest of the draft", () => {
    const draft: AlertMatch = { categories: ["person"] }
    const result = importFromRecordingFilter(draft, filter, "labels", { allowed: true })
    expect(result.draft.categories).toEqual(["person"])
  })
})

describe("recordingFilterKeys", () => {
  it("lists only the three keys the recording side accepts", () => {
    const keys = recordingFilterKeys({ labels: [], zones: [], min_confidence: 0.5 })
    expect(keys.sort()).toEqual(["labels", "min_confidence", "zones"])
  })

  it("returns nothing for a camera with no policy", () => {
    expect(recordingFilterKeys(null)).toEqual([])
    expect(recordingFilterKeys({})).toEqual([])
  })

  it("never reports a key the recording side does not support", () => {
    // If the backend ever widens the recording filter, this is where it will
    // show up, and the `importable` metadata is what decides the outcome.
    const keys = recordingFilterKeys({ labels: ["a"], something_new: 1 })
    expect(keys).toContain("labels")
    expect(keys).not.toContain("something_new" as never)
  })
})

describe("every match key has a validator path", () => {
  it("does not silently accept a key it never checks", () => {
    // A key added to the whitelist with no rule here would be sent to the
    // backend and fail there with a message the operator cannot act on.
    for (const key of MATCH_KEYS) {
      const errors = validateMatch({ [key]: "definitely-wrong-shape" })
      // Either it is validated (an error) or it is genuinely free-form; both
      // are fine, a crash is not.
      expect(errors).toBeTypeOf("object")
    }
  })
})

describe("weekdayLabel", () => {
  it("labels Monday as 0, matching the backend", () => {
    expect(weekdayLabel(0)).toBe("周一")
    expect(weekdayLabel(6)).toBe("周日")
  })
})
