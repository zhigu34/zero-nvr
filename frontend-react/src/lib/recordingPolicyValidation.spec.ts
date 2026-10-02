import { describe, expect, it } from "vitest"

import type { ScheduleWindow } from "../api/recordingPolicies"
import {
  fromSchedulePayload,
  toSchedulePayload,
  validatePolicyForm,
  validateWeeklySchedule,
  type PolicyFormValues,
} from "./recordingPolicyValidation"

/**
 * The backend validates the schedule inside the service layer, so none of this
 * is visible in the generated OpenAPI schema. Each rule below has its own
 * error code in `recordings/policy.py`; a form that only learns them from a
 * 400 makes the operator redo the whole page.
 */

const WINDOW: ScheduleWindow = {
  days: [0, 1, 2],
  start: "22:00",
  end: "06:00",
}

function form(over: Partial<PolicyFormValues> = {}): PolicyFormValues {
  return {
    baselineMode: "continuous",
    enabled: true,
    scheduleWindows: [],
    scheduleTimezone: "",
    segmentTargetSeconds: 300,
    preRollSeconds: 10,
    postRollSeconds: 10,
    ...over,
  }
}

describe("validateWeeklySchedule", () => {
  it("accepts a window that crosses midnight", () => {
    // start > end is explicitly supported by the backend.
    expect(validateWeeklySchedule([WINDOW])).toEqual([])
  })

  it("requires at least one window", () => {
    expect(validateWeeklySchedule([])).toEqual([
      { field: "schedule", message: "按计划录制至少需要一个时段" },
    ])
  })

  it("enforces the 64 window cap", () => {
    const many = Array.from({ length: 65 }, () => WINDOW)
    expect(validateWeeklySchedule(many)[0].message).toContain("64")
  })

  it("rejects a malformed time", () => {
    const errors = validateWeeklySchedule([{ ...WINDOW, start: "9:00" }])
    expect(errors.some((e) => e.field.endsWith("start"))).toBe(true)
  })

  it("rejects an out-of-range hour", () => {
    const errors = validateWeeklySchedule([{ ...WINDOW, end: "24:00" }])
    expect(errors.some((e) => e.field.endsWith("end"))).toBe(true)
  })

  it("rejects a zero-length window", () => {
    const errors = validateWeeklySchedule([{ ...WINDOW, end: "22:00" }])
    expect(errors.some((e) => e.message.includes("不能相同"))).toBe(true)
  })

  it("rejects duplicate weekdays", () => {
    const errors = validateWeeklySchedule([{ ...WINDOW, days: [1, 1, 2] }])
    expect(errors.some((e) => e.message.includes("重复"))).toBe(true)
  })

  it("rejects a weekday outside 0-6", () => {
    const errors = validateWeeklySchedule([{ ...WINDOW, days: [7] }])
    expect(errors.some((e) => e.message.includes("无效"))).toBe(true)
  })

  it("rejects a window with no days selected", () => {
    const errors = validateWeeklySchedule([{ ...WINDOW, days: [] }])
    expect(errors.some((e) => e.message.includes("未选择星期"))).toBe(true)
  })

  it("reports each window separately", () => {
    const errors = validateWeeklySchedule([
      { days: [0], start: "bad", end: "06:00" },
      { days: [], start: "22:00", end: "23:00" },
    ])
    expect(new Set(errors.map((e) => e.field)).size).toBeGreaterThan(1)
  })
})

describe("validatePolicyForm", () => {
  it("does not require a schedule for continuous recording", () => {
    expect(validatePolicyForm(form())).toEqual([])
  })

  it("requires both a schedule and a timezone in schedule mode", () => {
    const errors = validatePolicyForm(form({ baselineMode: "schedule" }))
    const fields = errors.map((e) => e.field)
    expect(fields).toContain("schedule")
    expect(fields).toContain("schedule_timezone")
  })

  it("accepts schedule mode once both are provided", () => {
    expect(
      validatePolicyForm(
        form({
          baselineMode: "schedule",
          scheduleWindows: [WINDOW],
          scheduleTimezone: "Asia/Shanghai",
        }),
      ),
    ).toEqual([])
  })

  /**
   * `recording_schedule_not_allowed`: the backend refuses a non-empty
   * schedule when the mode is not "schedule", which reads as "my schedule
   * disappeared" if the form silently drops it.
   */
  it("warns that a schedule set in another mode will not be saved", () => {
    const errors = validatePolicyForm(
      form({ baselineMode: "continuous", scheduleWindows: [WINDOW] }),
    )
    expect(errors.some((e) => e.field === "schedule")).toBe(true)
    expect(errors.some((e) => e.message.includes("不会被保存"))).toBe(true)
  })

  it("applies the same rule to a timezone set in another mode", () => {
    const errors = validatePolicyForm(form({ scheduleTimezone: "UTC" }))
    expect(errors.some((e) => e.field === "schedule_timezone")).toBe(true)
  })

  it("enforces the segment target range", () => {
    for (const value of [4, 3601, 0]) {
      const errors = validatePolicyForm(form({ segmentTargetSeconds: value }))
      expect(errors.some((e) => e.field === "segment_target_seconds")).toBe(true)
    }
  })

  it("accepts the segment target boundaries", () => {
    for (const value of [5, 3600]) {
      const errors = validatePolicyForm(form({ segmentTargetSeconds: value }))
      expect(errors.some((e) => e.field === "segment_target_seconds")).toBe(false)
    }
  })

  it("enforces the pre-roll and post-roll ranges", () => {
    expect(
      validatePolicyForm(form({ preRollSeconds: 301 })).some(
        (e) => e.field === "pre_roll_seconds",
      ),
    ).toBe(true)
    expect(
      validatePolicyForm(form({ postRollSeconds: 3601 })).some(
        (e) => e.field === "post_roll_seconds",
      ),
    ).toBe(true)
  })

  it("rejects a fractional second count", () => {
    // The backend types these as `int`; a float is a 422, not a rounding.
    const errors = validatePolicyForm(form({ segmentTargetSeconds: 300.5 }))
    expect(errors.some((e) => e.field === "segment_target_seconds")).toBe(true)
  })
})

describe("schedule payload round trip", () => {
  it("deduplicates and sorts days the way the backend stores them", () => {
    const payload = toSchedulePayload([{ days: [3, 1, 3], start: "09:00", end: "17:00" }])
    expect(payload).toEqual({
      weekly: [{ days: [1, 3], start: "09:00", end: "17:00" }],
    })
  })

  it("omits the payload entirely when there are no windows", () => {
    expect(toSchedulePayload([])).toBeUndefined()
  })

  it("never emits a key other than weekly", () => {
    // `recording_schedule_invalid` on any extra top-level key.
    const payload = toSchedulePayload([WINDOW])!
    expect(Object.keys(payload)).toEqual(["weekly"])
  })

  it("parses a stored payload back into form state", () => {
    const stored = {
      weekly: [{ days: [0, 2], start: "22:00", end: "06:00" }],
    }
    expect(fromSchedulePayload(stored)).toEqual([
      { days: [0, 2], start: "22:00", end: "06:00" },
    ])
  })

  it("drops malformed entries instead of crashing the form", () => {
    const stored = {
      weekly: [
        { days: [0], start: "22:00", end: "06:00" },
        { days: "not-an-array", start: "01:00", end: "02:00" },
        null,
        { days: [9], start: "01:00", end: "02:00" },
      ],
    }
    expect(fromSchedulePayload(stored)).toHaveLength(1)
  })

  it("tolerates a missing or non-object schedule", () => {
    expect(fromSchedulePayload(null)).toEqual([])
    expect(fromSchedulePayload({})).toEqual([])
    expect(fromSchedulePayload({ weekly: "nope" })).toEqual([])
  })
})
