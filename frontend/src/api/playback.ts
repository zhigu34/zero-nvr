import { apiRequest } from "./client"

export type TimelineDetailLevel =
  | "day"
  | "hour"
  | "minute"

export type TimelineAvailability =
  | "local"
  | "remote"
  | "cached_remote"
  | "missing"
  | "corrupted"
  | "purged"

const PLAYABLE_TIMELINE_AVAILABILITY =
  new Set<TimelineAvailability>([
    "local",
    "remote",
    "cached_remote"
  ])

export interface TimelineRange {
  start_at: string
  end_at: string
}

export interface TimelineRecordingRange {
  start_at: string
  end_at: string
  availability: TimelineAvailability
}

export interface TimelineSegment {
  id: string
  playback_ref: string
  start_at: string
  end_at: string
  availability: TimelineAvailability
}

export interface TimelineGap {
  start_at: string
  end_at: string
  reason: string
}

export type TimelineEventMarkerType =
  | "point"
  | "range"
  | "aggregate"

export interface TimelineEvent {
  id: string
  marker_type: TimelineEventMarkerType
  category: string
  label: string | null
  start_at: string
  end_at: string | null
  count: number
  category_counts: Record<string, number>
  label_counts: Record<string, number>
}

export interface PlaybackTimeline {
  camera_id: string
  detail: TimelineDetailLevel
  range: TimelineRange
  segments: TimelineSegment[]
  recording_ranges: TimelineRecordingRange[]
  gaps: TimelineGap[]
  events: TimelineEvent[]
}

export interface PlaybackAlignedTimeline {
  detail: TimelineDetailLevel
  range: TimelineRange
  tracks: PlaybackTimeline[]
}

export interface PlaybackPlayable {
  status: "playable"
  segment_id: string
  segment_start_at: string
  offset_ms: number
  transport: "fmp4"
  url: string
  expires_at: string
  codec: string | null
}

export interface PlaybackPending {
  status: "pending"
  reason: "remote_restore_required"
  segment_id: string
  retry_after_ms: number
}

export interface PlaybackGap {
  status: "gap"
  reason: string
  previous_at: string | null
  next_at: string | null
}

export type PlaybackResolve =
  | PlaybackPlayable
  | PlaybackPending
  | PlaybackGap

export function getAlignedCameraTimelines(
  cameraIds: string[],
  from: Date,
  to: Date,
  detail: TimelineDetailLevel = "minute"
): Promise<PlaybackAlignedTimeline> {
  return apiRequest<PlaybackAlignedTimeline>(
    "/playback/timeline",
    {
      method: "POST",
      json: {
        camera_ids: cameraIds,
        from: from.toISOString(),
        to: to.toISOString(),
        detail
      }
    }
  )
}

export function getCameraTimeline(
  cameraId: string,
  from: Date,
  to: Date,
  detail: TimelineDetailLevel = "minute"
): Promise<PlaybackTimeline> {
  const params = new URLSearchParams({
    from: from.toISOString(),
    to: to.toISOString(),
    detail
  })
  return apiRequest<PlaybackTimeline>(
    `/cameras/${encodeURIComponent(cameraId)}/timeline?${params}`
  )
}

export function timelineHasPlayableAt(
  timeline: PlaybackTimeline,
  atMs: number
): boolean {
  return timeline.recording_ranges.some(
    (range) =>
      PLAYABLE_TIMELINE_AVAILABILITY.has(
        range.availability
      ) &&
      new Date(range.start_at).getTime() <= atMs &&
      atMs < new Date(range.end_at).getTime()
  )
}

export function findNextPlayableTimelineTime(
  timelines: PlaybackTimeline[],
  afterMs: number
): number | null {
  if (
    timelines.some((timeline) =>
      timelineHasPlayableAt(
        timeline,
        afterMs
      )
    )
  ) {
    return null
  }

  let next: number | null = null
  for (const timeline of timelines) {
    for (const range of timeline.recording_ranges) {
      if (
        !PLAYABLE_TIMELINE_AVAILABILITY.has(
          range.availability
        )
      ) {
        continue
      }

      const startMs = new Date(
        range.start_at
      ).getTime()
      if (
        startMs <= afterMs ||
        (next !== null && startMs >= next)
      ) {
        continue
      }
      next = startMs
    }
  }

  return next
}

export function findTimelineSegmentAt(
  segments: TimelineSegment[],
  at: Date
): TimelineSegment | null {
  const target = at.getTime()
  let low = 0
  let high = segments.length - 1
  let candidate = -1

  while (low <= high) {
    const middle = (low + high) >>> 1
    const start = new Date(
      segments[middle].start_at
    ).getTime()

    if (start <= target) {
      candidate = middle
      low = middle + 1
    } else {
      high = middle - 1
    }
  }

  if (candidate < 0) return null

  const segment = segments[candidate]
  const end = new Date(
    segment.end_at
  ).getTime()
  return target < end ? segment : null
}

export function resolveRecordingSegment(
  segmentId: string,
  offsetMs = 0
): Promise<PlaybackResolve> {
  return apiRequest<PlaybackResolve>(
    `/recordings/${encodeURIComponent(
      segmentId
    )}/playback/resolve`,
    {
      method: "POST",
      json: { offset_ms: offsetMs }
    }
  )
}

export function resolveCameraPlayback(
  cameraId: string,
  at: Date
): Promise<PlaybackResolve> {
  return apiRequest<PlaybackResolve>(
    `/cameras/${encodeURIComponent(cameraId)}/playback/resolve`,
    {
      method: "POST",
      json: { at: at.toISOString() }
    }
  )
}
