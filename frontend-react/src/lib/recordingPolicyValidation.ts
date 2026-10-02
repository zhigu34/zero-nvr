/**
 * Client-side validation for recording policy writes.
 *
 * The backend validates all of this too, but only inside the service layer —
 * `RecordingPolicyPut.schedule` and `.event_filter` are declared as bare
 * `dict[str, object]` in Pydantic (`recordings/schemas.py:125,128`), so the
 * rules are invisible to OpenAPI and invisible to us at the type level. The
 * checks in `recordings/policy.py:53-161` are strict, and a policy form that
 * only discovers them by getting a 400 back wastes the operator's work.
 *
 * Nothing here replaces server validation. It exists so the common mistakes
 * are caught while the form is still open.
 */
import type {
  BaselineMode,
  ScheduleWindow,
} from "../api/recordingPolicies"

export interface PolicyFieldError {
  field: string
  message: string
}

/** `recordings/policy.py` limits. */
export const SEGMENT_TARGET_RANGE = { min: 5, max: 3600 } as const
export const PRE_ROLL_RANGE = { min: 0, max: 300 } as const
export const POST_ROLL_RANGE = { min: 0, max: 3600 } as const
export const MAX_WEEKLY_WINDOWS = 64

const TIME_PATTERN = /^([01]\d|2[0-3]):[0-5]\d$/

/** Monday = 0, matching the backend's `weekday()` convention. */
export const WEEKDAY_LABEL: Record<number, string> = {
  0: "周一",
  1: "周二",
  2: "周三",
  3: "周四",
  4: "周五",
  5: "周六",
  6: "周日",
}

export function validateWeeklySchedule(
  windows: readonly ScheduleWindow[],
): PolicyFieldError[] {
  const errors: PolicyFieldError[] = []

  if (windows.length === 0) {
    return [{ field: "schedule", message: "按计划录制至少需要一个时段" }]
  }
  if (windows.length > MAX_WEEKLY_WINDOWS) {
    return [
      {
        field: "schedule",
        message: `时段数量不能超过 ${MAX_WEEKLY_WINDOWS} 个`,
      },
    ]
  }

  windows.forEach((window, index) => {
    const label = `第 ${index + 1} 个时段`

    if (!Array.isArray(window.days) || window.days.length === 0) {
      errors.push({ field: `schedule.${index}.days`, message: `${label}未选择星期` })
    } else {
      const invalid = window.days.filter(
        (day) => !Number.isInteger(day) || day < 0 || day > 6,
      )
      if (invalid.length > 0) {
        errors.push({
          field: `schedule.${index}.days`,
          message: `${label}含有无效的星期取值`,
        })
      }
      if (new Set(window.days).size !== window.days.length) {
        errors.push({
          field: `schedule.${index}.days`,
          message: `${label}有重复的星期`,
        })
      }
    }

    for (const key of ["start", "end"] as const) {
      const value = window[key]
      if (typeof value !== "string" || !TIME_PATTERN.test(value)) {
        errors.push({
          field: `schedule.${index}.${key}`,
          message: `${label}的${key === "start" ? "开始" : "结束"}时间须为 HH:MM`,
        })
      }
    }

    // The backend rejects an empty window outright; a "window" with no
    // duration is always a mistake rather than an intent.
    if (
      typeof window.start === "string" &&
      typeof window.end === "string" &&
      window.start === window.end
    ) {
      errors.push({
        field: `schedule.${index}`,
        message: `${label}的开始与结束时间不能相同`,
      })
    }
  })

  return errors
}

function inRange(
  value: number,
  range: { min: number; max: number },
): boolean {
  return Number.isInteger(value) && value >= range.min && value <= range.max
}

export interface PolicyFormValues {
  baselineMode: BaselineMode
  enabled: boolean
  scheduleWindows: ScheduleWindow[]
  scheduleTimezone: string
  segmentTargetSeconds: number
  preRollSeconds: number
  postRollSeconds: number
}

/**
 * Cross-field rules the backend enforces together, each with its own error
 * code — getting them wrong in a form is otherwise a 400 with no hint about
 * which field the server objected to.
 */
export function validatePolicyForm(
  values: PolicyFormValues,
): PolicyFieldError[] {
  const errors: PolicyFieldError[] = []

  if (values.baselineMode === "schedule") {
    errors.push(...validateWeeklySchedule(values.scheduleWindows))
    if (!values.scheduleTimezone.trim()) {
      errors.push({
        field: "schedule_timezone",
        message: "按计划录制必须指定时区",
      })
    }
  } else {
    // `recording_schedule_not_allowed` / `recording_schedule_timezone_not_allowed`
    if (values.scheduleWindows.length > 0) {
      errors.push({
        field: "schedule",
        message: "当前模式不是「按计划录制」，时段设置不会被保存",
      })
    }
    if (values.scheduleTimezone.trim()) {
      errors.push({
        field: "schedule_timezone",
        message: "当前模式不是「按计划录制」，时区不会被保存",
      })
    }
  }

  if (!inRange(values.segmentTargetSeconds, SEGMENT_TARGET_RANGE)) {
    errors.push({
      field: "segment_target_seconds",
      message: `目标分段时长需在 ${SEGMENT_TARGET_RANGE.min}–${SEGMENT_TARGET_RANGE.max} 秒之间`,
    })
  }
  if (!inRange(values.preRollSeconds, PRE_ROLL_RANGE)) {
    errors.push({
      field: "pre_roll_seconds",
      message: `预录时长需在 ${PRE_ROLL_RANGE.min}–${PRE_ROLL_RANGE.max} 秒之间`,
    })
  }
  if (!inRange(values.postRollSeconds, POST_ROLL_RANGE)) {
    errors.push({
      field: "post_roll_seconds",
      message: `后录时长需在 ${POST_ROLL_RANGE.min}–${POST_ROLL_RANGE.max} 秒之间`,
    })
  }

  return errors
}

/**
 * A `weekly` payload shaped exactly as `recordings/policy.py` expects. The
 * backend rejects any other top-level key, so this builds the object rather
 * than having the form assemble one.
 */
export function toSchedulePayload(
  windows: readonly ScheduleWindow[],
): Record<string, unknown> | undefined {
  if (windows.length === 0) return undefined
  return {
    weekly: windows.map((window) => ({
      // Deduplicated and sorted, matching what the backend stores.
      days: [...new Set(window.days)].sort((a, b) => a - b),
      start: window.start,
      end: window.end,
    })),
  }
}

/** Parses a stored `schedule` back into form state, tolerating junk. */
export function fromSchedulePayload(
  schedule: Record<string, unknown> | null | undefined,
): ScheduleWindow[] {
  const weekly = schedule?.weekly
  if (!Array.isArray(weekly)) return []
  return weekly.flatMap((entry) => {
    if (!entry || typeof entry !== "object") return []
    const raw = entry as Partial<ScheduleWindow>
    if (!Array.isArray(raw.days)) return []
    const days = raw.days.filter(
      (day): day is number => typeof day === "number" && day >= 0 && day <= 6,
    )
    // An entry whose days all fall outside the valid range is not a window
    // with no days — it is an unusable entry, and handing it to the form
    // would produce a validation error the operator cannot see the cause of.
    if (days.length === 0) return []
    if (typeof raw.start !== "string" || typeof raw.end !== "string") return []
    return [{ days, start: raw.start, end: raw.end }]
  })
}
