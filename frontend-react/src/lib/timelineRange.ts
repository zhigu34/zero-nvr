/**
 * Range and granularity rules for the timeline screen.
 *
 * The backend puts no upper bound on either: `PlaybackTimelineService.build`
 * selects every segment and every event in the range with no `LIMIT`
 * (`recordings/timeline.py:562-590`). The only thing standing between an
 * operator and a 40,000-marker response is this module, so the coupling
 * between "how far back" and "how finely" is decided here rather than
 * discovered in the browser.
 */
import type { TimelineDetail } from "../api/playback"

export const RANGE_PRESETS = [
  { value: "today", label: "今天", ms: 24 * 60 * 60 * 1000 },
  { value: "24h", label: "最近 24 小时", ms: 24 * 60 * 60 * 1000 },
  { value: "7d", label: "最近 7 天", ms: 7 * 24 * 60 * 60 * 1000 },
  { value: "custom", label: "自定义", ms: 0 },
] as const

export type RangePreset = (typeof RANGE_PRESETS)[number]["value"]

export type TimeRange = { from: string; to: string }

/**
 * The three detail levels are named for something other than what they do.
 * `timeline.py:414-418` buckets events by **1 hour** when `detail == "day"`
 * and by **5 minutes** when `detail == "hour"`; only `minute` is literal.
 * The UI therefore labels them by bucket size, and the raw token is kept only
 * as the request parameter.
 */
export const DETAIL_OPTIONS: {
  value: TimelineDetail
  label: string
  bucket: string
}[] = [
  { value: "minute", label: "逐个事件", bucket: "每个事件一个标记" },
  { value: "hour", label: "5 分钟", bucket: "按 5 分钟分桶" },
  { value: "day", label: "1 小时", bucket: "按 1 小时分桶" },
]

export function bucketMinutes(detail: TimelineDetail): number | null {
  if (detail === "minute") return null
  return detail === "hour" ? 5 : 60
}

/** Midnight→now in the browser's zone, expressed as UTC ISO bounds. */
export function todayRange(now: number = Date.now()): TimeRange {
  const start = new Date(now)
  start.setHours(0, 0, 0, 0)
  return {
    from: start.toISOString(),
    to: new Date(now).toISOString(),
  }
}

export function resolveRange(
  preset: RangePreset,
  custom?: { from: string; to?: string },
  now: number = Date.now(),
): TimeRange {
  if (preset === "custom" && custom?.from && custom.to) {
    return { from: custom.from, to: custom.to }
  }
  if (preset === "7d" || preset === "24h") {
    const days = preset === "7d" ? 7 : 1
    return {
      from: new Date(now - days * 24 * 60 * 60 * 1000).toISOString(),
      to: new Date(now).toISOString(),
    }
  }
  return todayRange(now)
}

/**
 * The finest granularity that is still sane for a given span.
 *
 * Used as the default when the range changes, so choosing "最近 7 天" does not
 * silently request one marker per event across a week.
 */
export function defaultDetailFor(rangeMs: number): TimelineDetail {
  const hours = rangeMs / (60 * 60 * 1000)
  if (hours <= 6) return "minute"
  if (hours <= 48) return "hour"
  return "day"
}

/**
 * Why the current combination is a bad idea, or null if it is fine.
 *
 * Not a hard block: the operator may genuinely want every event across a
 * day, and refusing to draw it would be its own kind of dishonesty. But the
 * cost is worth stating before the request goes out, because the failure mode
 * is a slow page rather than an error.
 */
export function detailWarning(
  rangeMs: number,
  detail: TimelineDetail,
): string | null {
  if (detail !== "minute") return null
  const hours = rangeMs / (60 * 60 * 1000)
  if (hours > 48) {
    return "逐个事件粒度在超过两天的范围上可能一次返回成千上万个标记，页面会明显变慢。"
  }
  if (hours > 12) {
    return "逐个事件粒度在一天以上的范围上可能一次返回上千个标记，建议改用 5 分钟或 1 小时。"
  }
  return null
}

export type AxisTick = { ms: number; label: string }

/**
 * Tick positions for the time axis.
 *
 * Steps are snapped to whole minutes/hours/days rather than to `span/count`,
 * so a "3 小时" axis lands on 09:00 / 10:00 / 11:00 instead of on
 * 09:17 / 10:51 — an operator reading a gap reason has to be able to compare
 * the tooltip against the axis by eye.
 */
export function axisTicks(
  startMs: number,
  endMs: number,
  target = 8,
): AxisTick[] {
  const span = endMs - startMs
  if (!Number.isFinite(span) || span <= 0) return []

  const steps = [
    60_000, 5 * 60_000, 15 * 60_000, 30 * 60_000,
    60 * 60_000, 3 * 60 * 60_000, 6 * 60 * 60_000, 12 * 60 * 60_000,
    24 * 60 * 60_000, 7 * 24 * 60 * 60_000,
  ]
  const ideal = span / Math.max(1, target)
  const step = steps.find((s) => s >= ideal) ?? steps[steps.length - 1]

  // Align to the step in local time, so a daily axis reads midnight-to-midnight.
  const offset = new Date(startMs).getTimezoneOffset() * 60_000
  const first = Math.ceil((startMs - offset) / step) * step + offset

  const ticks: AxisTick[] = []
  for (let t = first; t <= endMs && ticks.length < 200; t += step) {
    ticks.push({ ms: t, label: tickLabel(t, step) })
  }
  return ticks
}

function tickLabel(ms: number, step: number): string {
  const d = new Date(ms)
  if (step >= 24 * 60 * 60_000) {
    return d.toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" })
  }
  return d.toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  })
}
