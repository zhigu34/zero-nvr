import * as React from "react"

import {
  GAP_REASON_LABEL,
  type PlaybackTimelineView,
  type SegmentAvailability,
  type TimelineEventMarker,
  type TimelineGapReason,
} from "../../api/playback"
import { categoryLabel } from "../../api/events"
import { instantMs } from "../../playback/session"
import { cn } from "../../lib/utils"

/**
 * The horizontal record track.
 *
 * The one rule this component exists to enforce: an empty stretch of timeline
 * is never drawn as a plain black bar. The backend projects a specific reason
 * for every gap — the recording schedule did not cover it, the camera dropped,
 * the media service restarted, retention removed the file — and those point at
 * different operator actions. Collapsing them into one colour makes the track
 * unreadable exactly when something has gone wrong.
 */

const SEGMENT_FILL: Record<SegmentAvailability, string> = {
  local: "bg-primary/85",
  remote: "bg-primary/45",
  cached_remote: "bg-primary/65",
  missing: "bg-status-offline/45",
  corrupted: "bg-status-degraded/55",
  purged: "bg-muted-foreground/30",
}

/**
 * Diagonal hatching separates "no recording" from "recording that cannot be
 * shown" without relying on colour alone.
 */
const GAP_FILL: Record<TimelineGapReason, string> = {
  not_scheduled: "bg-muted-foreground/15",
  no_event: "bg-muted-foreground/20",
  source_lost: "bg-status-offline/25",
  runtime_restart: "bg-status-degraded/25",
  storage_failure: "bg-status-degraded/40",
  missing_media: "bg-status-offline/35",
  purged: "bg-muted-foreground/25",
  unknown: "bg-muted-foreground/20",
}

/**
 * Event categories reuse the events vocabulary (`CATEGORY_LABEL`), so the
 * same category reads the same colour here as it does in the event list —
 * otherwise an operator comparing the two has to learn the mapping twice.
 *
 * Only four tones are used on purpose: a track that distinguishes eight
 * categories by hue stops being readable at track height, and the category
 * is in the tooltip and the side panel where detail belongs.
 */
const CATEGORY_TONE: Record<string, "online" | "degraded" | "offline" | "unknown"> = {
  person: "online",
  vehicle: "online",
  animal: "degraded",
  motion: "unknown",
  intrusion: "offline",
  line: "degraded",
}

const CATEGORY_BAR: Record<string, string> = {
  online: "bg-status-online",
  degraded: "bg-status-degraded",
  offline: "bg-status-offline",
  unknown: "bg-muted-foreground",
}

function eventTitle(event: TimelineEventMarker): string {
  const when = new Date(event.start_at).toLocaleString("zh-CN", { hour12: false })
  const what = event.label ? `${categoryLabel(event.category)} · ${event.label}` : categoryLabel(event.category)
  // An aggregate marker stands for a bucket of events, so it says how many
  // rather than implying a single occurrence.
  return event.marker_type === "aggregate"
    ? `${when} 起 ${event.count} 个事件（${what}）`
    : `${when} ${what}`
}

export interface TimelineTrackProps {
  timeline: PlaybackTimelineView | null
  rangeStartMs: number
  rangeEndMs: number
  currentMs: number
  onSeek?: (atMs: number) => void
  className?: string
  height?: number
  /**
   * Draw the event markers above the record track. Off in the playback
   * screen, where the events are already listed below the stage and a second
   * layer on the same track is noise; on in the timeline screen, where the
   * events are most of what is being compared.
   */
  showEvents?: boolean
}

export function TimelineTrack({
  timeline,
  rangeStartMs,
  rangeEndMs,
  currentMs,
  onSeek,
  className,
  height = 44,
  showEvents = false,
}: TimelineTrackProps) {
  const span = Math.max(1, rangeEndMs - rangeStartMs)
  const toPercent = (ms: number) =>
    ((Math.min(Math.max(ms, rangeStartMs), rangeEndMs) - rangeStartMs) /
      span) *
    100

  // A malformed payload must render an empty track, not take the page down
  // on a frame that happens to be the first one to touch it.
  const segments = Array.isArray(timeline?.segments) ? timeline.segments : []
  const gaps = Array.isArray(timeline?.gaps) ? timeline.gaps : []
  const events = Array.isArray(timeline?.events) ? timeline.events : []

  const handleClick = (event: React.MouseEvent<HTMLDivElement>) => {
    if (!onSeek) return
    const rect = event.currentTarget.getBoundingClientRect()
    if (rect.width === 0) return
    const ratio = (event.clientX - rect.left) / rect.width
    onSeek(rangeStartMs + ratio * span)
  }

  return (
    <div
      className={cn("relative w-full select-none", className)}
      style={{ height }}
      onClick={handleClick}
      role={onSeek ? "slider" : undefined}
      aria-label={onSeek ? "回放时间轴" : undefined}
      aria-valuenow={onSeek ? Math.round(currentMs) : undefined}
    >
      <div className="absolute inset-0 overflow-hidden rounded-md border border-border bg-muted/30">
        {segments.map((segment) => (
          <div
            key={segment.id}
            className={cn(
              "absolute top-0 h-full",
              SEGMENT_FILL[segment.availability] ??
                "bg-primary/50",
            )}
            style={{
              left: `${toPercent(instantMs(segment.start_at))}%`,
              width: `${Math.max(
                0.4,
                toPercent(instantMs(segment.end_at)) -
                  toPercent(instantMs(segment.start_at)),
              )}%`,
            }}
            title={`${segment.availability}`}
          />
        ))}

        {gaps.map((gap) => (
          <div
            key={`${gap.start_at}-${gap.reason}`}
            className={cn(
              "absolute top-0 h-full",
              GAP_FILL[gap.reason] ?? GAP_FILL.unknown,
            )}
            style={{
              left: `${toPercent(instantMs(gap.start_at))}%`,
              width: `${Math.max(
                0.4,
                toPercent(instantMs(gap.end_at)) -
                  toPercent(instantMs(gap.start_at)),
              )}%`,
              backgroundImage:
                "repeating-linear-gradient(45deg, transparent, transparent 3px, rgba(0,0,0,0.18) 3px, rgba(0,0,0,0.18) 6px)",
            }}
            // The reason is the actionable part: an operator reading this
            // needs to know whether to check the schedule, the camera, the
            // media service or retention.
            title={`${GAP_REASON_LABEL[gap.reason] ?? gap.reason}（${formatClock(
              instantMs(gap.start_at),
            )} – ${formatClock(instantMs(gap.end_at))}）`}
            data-gap-reason={gap.reason}
          />
        ))}
      </div>

      {showEvents &&
        events.map((event) => {
          // A point marker has no `end_at`; a range or aggregate does, and a
          // missing end on those would otherwise render as zero width and
          // look like a rendering bug rather than a payload problem.
          const start = instantMs(event.start_at)
          const end = event.end_at ? instantMs(event.end_at) : start
          const width =
            event.marker_type === "point"
              ? 0
              : Math.max(0.5, toPercent(end) - toPercent(start))
          const tone = CATEGORY_TONE[event.category] ?? "unknown"
          return (
            <div
              key={event.id}
              className={cn(
                "pointer-events-none absolute bottom-0 z-[5] h-1.5 rounded-full",
                CATEGORY_BAR[tone],
              )}
              style={{
                left: `${toPercent(start)}%`,
                width: `${width}%`,
              }}
              data-event-category={event.category}
              title={eventTitle(event)}
            />
          )
        })}

      <div
        className="pointer-events-none absolute inset-y-0 z-10 w-px bg-foreground"
        style={{ left: `${toPercent(currentMs)}%` }}
        data-testid="playhead"
        aria-hidden
      />
    </div>
  )
}

function formatClock(ms: number): string {
  return new Date(ms).toLocaleTimeString("zh-CN", { hour12: false })
}
