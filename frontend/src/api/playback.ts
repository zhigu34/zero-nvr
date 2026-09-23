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

export interface TimelineRange {
  start_at: string
  end_at: string
}

export interface TimelineRecordingRange {
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
  recording_ranges: TimelineRecordingRange[]
  gaps: TimelineGap[]
  events: TimelineEvent[]
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
