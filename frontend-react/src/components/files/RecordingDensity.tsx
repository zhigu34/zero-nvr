/**
 * Recording density for a range of days, and the shape of one day.
 *
 * Both are built from **real** numbers. The Vue files page displayed a byte
 * total it had invented (`dur * 450_000`, `FilesView.vue:262`) because the
 * timeline endpoint carries no size; the per-day endpoint added for this
 * aggregates the actual `size_bytes` column, so nothing here is an estimate.
 *
 * The two views answer different questions and therefore use different sources:
 *
 * - the **strip** answers "which days in this range have material, and how
 *   much" from the per-day aggregate, so covering a month costs one request;
 * - the **heatmap** answers "when during this day" from that day's timeline,
 *   which carries exact segment bounds and so can be bucketed to the hour in
 *   the display timezone without guessing.
 */
import { useMemo } from "react"

import type { RecordingDayStat } from "../../api/playback"
import { Badge } from "../ui/primitives"
import { Callout } from "../ui/display"

/* -------------------------------------------------------------------------- */
/* Formatting                                                                  */
/* -------------------------------------------------------------------------- */

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  const units = ["KB", "MB", "GB", "TB"]
  let value = bytes / 1024
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value >= 10 ? value.toFixed(0) : value.toFixed(1)} ${units[unit]}`
}

export function formatDuration(sec: number): string {
  // Rounded **down** throughout. This number labels how much was recorded, and
  // rounding up claims footage that does not exist: 3660s across a day of
  // segments would read "1 小时 1 分". Flooring also avoids the ladder printing
  // "60 分钟" for 3599s and then "1 小时" for 3600s — the same length rendered
  // two different ways.
  if (sec < 60) return `${Math.max(0, Math.floor(sec))} 秒`
  if (sec < 3600) return `${Math.floor(sec / 60)} 分钟`
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  return m ? `${h} 小时 ${m} 分` : `${h} 小时`
}

/* -------------------------------------------------------------------------- */
/* Day density strip                                                          */
/* -------------------------------------------------------------------------- */

export type DayCell = {
  /** Local ISO date, `YYYY-MM-DD`. */
  day: string
  stat: RecordingDayStat | null
  /** True when the day falls inside the operator's selected range. */
  inRange: boolean
}

/** Scale a cell's shade against the busiest day, never against an absolute number. */
function densityLevel(stat: RecordingDayStat | null, peak: number): 0 | 1 | 2 | 3 | 4 {
  if (!stat || stat.duration_sec <= 0 || peak <= 0) return 0
  const ratio = stat.duration_sec / peak
  if (ratio > 0.75) return 4
  if (ratio > 0.5) return 3
  if (ratio > 0.2) return 2
  return 1
}

const SHADE = [
  "bg-transparent",
  "bg-status-online/15",
  "bg-status-online/30",
  "bg-status-online/50",
  "bg-status-online/75",
] as const

export function DayDensityStrip({
  days,
  selectedDay,
  onSelect,
  isPending,
  error,
}: {
  days: DayCell[]
  selectedDay: string | null
  onSelect: (day: string) => void
  isPending: boolean
  error: Error | null
}) {
  const peak = useMemo(
    () => days.reduce((max, cell) => Math.max(max, cell.stat?.duration_sec ?? 0), 0),
    [days],
  )

  if (error) {
    return (
      <Callout tone="offline" title="无法读取按日统计">
        {error.message}
      </Callout>
    )
  }
  if (isPending) {
    return <p className="text-xs text-muted-foreground">按日统计读取中…</p>
  }

  const withMaterial = days.filter((cell) => cell.stat !== null).length

  return (
    <div
      role="group"
      aria-label="按日录像密度"
      className="space-y-1.5"
    >
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium">
          按日密度
          <span className="ml-1.5 font-normal text-muted-foreground">
            {withMaterial > 0
              ? `${withMaterial} / ${days.length} 天有录像`
              : "所选范围内没有录像"}
          </span>
        </p>
        <span className="flex items-center gap-1 text-[10px] text-muted-foreground">
          少
          {SHADE.slice(1).map((shade) => (
            <span key={shade} className={`size-2.5 rounded-sm ${shade}`} />
          ))}
          多
        </span>
      </div>

      {days.length === 0 ? (
        <p className="text-xs text-muted-foreground">没有可显示的日期。</p>
      ) : (
        <ol className="flex flex-wrap gap-1">
          {days.map((cell) => {
            const level = densityLevel(cell.stat, peak)
            const selected = cell.day === selectedDay
            return (
              <li key={cell.day}>
                <button
                  type="button"
                  aria-pressed={selected}
                  title={
                    cell.stat
                      ? `${cell.day}：${cell.stat.count} 段 · ${formatDuration(
                          cell.stat.duration_sec,
                        )} · ${formatBytes(cell.stat.size_bytes)}`
                      : `${cell.day}：没有录像`
                  }
                  onClick={() => onSelect(cell.day)}
                  className={[
                    "flex size-8 flex-col items-center justify-center rounded border text-[10px] leading-none",
                    SHADE[level],
                    cell.inRange
                      ? "border-border"
                      : "border-transparent opacity-40",
                    selected
                      ? "ring-2 ring-ring"
                      : "hover:border-border",
                  ].join(" ")}
                >
                  <span className="font-mono">{Number(cell.day.slice(-2))}</span>
                  {cell.stat ? (
                    <span className="mt-0.5 text-[8px] opacity-70">
                      {cell.stat.count}
                    </span>
                  ) : (
                    <span className="mt-0.5 text-[8px] opacity-40">—</span>
                  )}
                </button>
              </li>
            )
          })}
        </ol>
      )}
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Day heatmap                                                                */
/* -------------------------------------------------------------------------- */

export type HourBucket = {
  /** 0–23 in the display timezone. */
  hour: number
  segments: number
  durationSec: number
}

/**
 * Bucket a day's segments into local hours.
 *
 * A segment belongs to the hour it **started** in. A segment straddling the
 * hour boundary is not split — that would need the per-second resolution the
 * heatmap does not have, and a 30-second segment is not a meaningful thing to
 * divide.
 *
 * Segments outside the requested day are ignored rather than clamped, so a
 * wide timeline range cannot bleed into hour 0 or 23.
 *
 * The parameter is the two bounds and nothing else: both `RecordingSegmentView`
 * (browse list) and `TimelineSegmentRef` (timeline) satisfy it, and the
 * function genuinely reads no other field.
 */
export function bucketByLocalHour(
  segments: readonly { start_at: string; end_at: string }[],
  timeZone: string,
  day: string,
): HourBucket[] {
  const buckets: HourBucket[] = Array.from({ length: 24 }, (_, hour) => ({
    hour,
    segments: 0,
    durationSec: 0,
  }))

  const formatter = new Intl.DateTimeFormat("en-US", {
    timeZone,
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
  })

  for (const segment of segments) {
    const start = new Date(segment.start_at)
    if (Number.isNaN(start.getTime())) continue
    const parts = formatter.formatToParts(start)
    const read = (type: string) =>
      parts.find((p) => p.type === type)?.value ?? ""
    const localDay = `${read("year")}-${read("month")}-${read("day")}`
    if (localDay !== day) continue
    const hour = Number(read("hour"))
    if (!Number.isInteger(hour) || hour < 0 || hour > 23) continue
    const bucket = buckets[hour]
    bucket.segments += 1
    bucket.durationSec += Math.max(
      0,
      Math.round(
        (new Date(segment.end_at).getTime() - start.getTime()) / 1000,
      ),
    )
  }

  return buckets
}

export function DayHeatmap({
  buckets,
  timeZone,
}: {
  buckets: HourBucket[]
  timeZone: string
}) {
  const peak = useMemo(
    () => buckets.reduce((max, b) => Math.max(max, b.durationSec), 0),
    [buckets],
  )
  const covered = buckets.filter((b) => b.segments > 0).length

  if (peak === 0) {
    return (
      <Callout tone="degraded" title="这一天没有录像">
        {`按 ${timeZone} 计算，24 个小时里没有任何分段。`}
      </Callout>
    )
  }

  return (
    <div role="group" aria-label="当日 24 小时分布" className="space-y-1.5">
      <p className="text-xs font-medium">
        当日分布
        <span className="ml-1.5 font-normal text-muted-foreground">
          {`${timeZone} · ${covered} / 24 小时有录像`}
        </span>
      </p>
      <ol className="flex items-end gap-0.5" style={{ height: 56 }}>
        {buckets.map((bucket) => {
          const ratio = bucket.durationSec / peak
          return (
            <li
              key={bucket.hour}
              title={
                bucket.segments > 0
                  ? `${String(bucket.hour).padStart(2, "0")}:00 · ${bucket.segments} 段 · ${formatDuration(bucket.durationSec)}`
                  : `${String(bucket.hour).padStart(2, "0")}:00 · 无录像`
              }
              className="group relative flex-1"
            >
              <div
                className="w-full rounded-sm bg-status-online/70"
                style={{
                  // A floor so a 1-minute hour is still visible next to a
                  // 60-minute one, rather than vanishing.
                  height: bucket.segments === 0 ? 2 : Math.max(8, ratio * 100),
                }}
              />
            </li>
          )
        })}
      </ol>
      <div className="flex justify-between text-[10px] text-muted-foreground">
        <span>00:00</span>
        <span>06:00</span>
        <span>12:00</span>
        <span>18:00</span>
        <span>23:00</span>
      </div>
    </div>
  )
}
