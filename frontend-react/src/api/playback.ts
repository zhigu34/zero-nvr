/**
 * Playback read contract. Mirrors `backend/app/modules/recordings/schemas.py`.
 *
 * Three things in here are easy to get wrong:
 *
 * 1. **`PlaybackResolve` is a discriminated union on `status`.** The backend
 *    only ever returns one of `playable` / `pending` / `gap`, and the field
 *    sets do not overlap — `url` and `offset_ms` exist *only* on `playable`.
 *    Any `if (resolve.url)` is a lie to the type checker.
 *
 * 2. **Milliseconds, not seconds.** `duration_ms`, `offset_ms` and
 *    `retry_after_ms` are all milliseconds, while `segment_target_seconds` and
 *    `pre_roll_seconds` on the policy side are seconds. Mixing them produces
 *    seeks that land a thousand times too far away.
 *
 * 3. **`detail` only coarsens event markers.** Segments, recording ranges and
 *    gaps come back at full resolution no matter what `detail` says, and the
 *    mapping is counter-intuitive: `hour` buckets events into 5-minute groups
 *    and `day` into 1-hour groups. It is not a segment-granularity knob.
 */
import { api } from "./client"

/** `recordings/schemas.py:10-17` — why a segment may not be playable. */
export type SegmentAvailability =
  | "local"
  | "remote"
  | "cached_remote"
  | "missing"
  | "corrupted"
  | "purged"

/** `recordings/schemas.py:19-28` — why a stretch of the timeline is empty. */
export type TimelineGapReason =
  | "not_scheduled"
  | "no_event"
  | "source_lost"
  | "runtime_restart"
  | "storage_failure"
  | "missing_media"
  | "purged"
  | "unknown"

/**
 * The same vocabulary, delivered as a bare `str` by the resolver rather than a
 * Literal. Rendered through `gapReasonLabel` and never through a strict cast.
 */
export type LooseGapReason = string

export type RecordingSegmentView = {
  id: string
  camera_id: string
  stream_profile_id: string | null
  start_at: string
  end_at: string
  /** Milliseconds. */
  duration_ms: number
  /** Free strings — the backend defines no enum for either. */
  timing_status: string
  timing_source: string
  recording_reasons: string[]
  /** Bytes. */
  size_bytes: number
  codec: string | null
  container: string
  integrity_status: string
  completion_reason: string | null
  /** When the catalog row was written — not when the footage was recorded. */
  created_at: string
}

export type RecordingLocationView = {
  id: string
  recording_segment_id: string
  storage_target_id: string
  storage_target_name: string
  storage_type: string
  storage_role: string
  object_path: string
  /** Free string, not an enum. */
  state: string
  /** Bytes. */
  size_bytes: number
  checksum: string | null
  verified_at: string | null
  created_at: string
  deleted_at: string | null
}

export type TimelineSegmentRef = {
  id: string
  /** Stable logical id to hand to the resolver — `RecordingSegment.id`. */
  playback_ref: string
  start_at: string
  end_at: string
  availability: SegmentAvailability
}

export type TimelineRange = {
  start_at: string
  end_at: string
}

/** `recording_ranges` elements carry availability; plain ranges do not. */
export type TimelineRecordingRange = TimelineRange & {
  availability: SegmentAvailability
}

export type TimelineGap = {
  start_at: string
  end_at: string
  reason: TimelineGapReason
}

export type TimelineEventMarker = {
  id: string
  marker_type: "point" | "range" | "aggregate"
  category: string
  label: string | null
  start_at: string
  end_at: string | null
  /** Populated on `aggregate` markers only. */
  count: number
  category_counts: Record<string, number>
  label_counts: Record<string, number>
}

export type PlaybackTimelineView = {
  camera_id: string
  detail: string
  range: TimelineRange
  segments: TimelineSegmentRef[]
  recording_ranges: TimelineRecordingRange[]
  gaps: TimelineGap[]
  events: TimelineEventMarker[]
}

export type RecordingSegmentPage = {
  items: RecordingSegmentView[]
  next_cursor: string | null
}

/* -------------------------------------------------------------------------- */
/* Resolve                                                                    */
/* -------------------------------------------------------------------------- */

export type PlaybackResolvePlayable = {
  status: "playable"
  segment_id: string
  segment_start_at: string
  /** Milliseconds from the start of the segment. */
  offset_ms: number
  /** Legacy field, constant `"mp4"`. */
  transport: "mp4"
  url: string
  /** Advisory only: `/media` validates the session cookie, not this stamp. */
  expires_at: string
  codec: string | null
}

export type PlaybackResolvePending = {
  status: "pending"
  /** The backend only ever emits this one reason. */
  reason: "remote_restore_required"
  segment_id: string
  /** Constant 2000. Poll on this cadence until the status flips. */
  retry_after_ms: number
}

export type PlaybackResolveGap = {
  status: "gap"
  reason: LooseGapReason
  previous_at: string | null
  next_at: string | null
}

export type PlaybackResolve =
  | PlaybackResolvePlayable
  | PlaybackResolvePending
  | PlaybackResolveGap

/* -------------------------------------------------------------------------- */
/* Per-day aggregates                                                         */
/* -------------------------------------------------------------------------- */

/**
 * One local calendar day of recorded material.
 *
 * `day` is a **local** date in the timezone that was asked for, so a segment at
 * 16:00Z belongs to the *next* day in `Asia/Shanghai`. Bucketing in UTC would
 * split the same footage across two days for most of the world and shift the
 * hour axis of a day heatmap by the offset.
 *
 * `size_bytes` is the real sum of `recording_segments.size_bytes` — not a
 * duration-to-bytes estimate. (The Vue files page had to invent one, because
 * the timeline endpoint carries no size at all; see G-45.)
 *
 * There is deliberately **no** cloud/remote count. Availability is decided by
 * `PlaybackTimelineService._availability` across segment integrity, location
 * state and storage target type; a second, coarser SQL approximation of that
 * rule is exactly the kind of thing that disagrees with playback.
 */
export type RecordingDayStat = {
  day: string
  count: number
  duration_sec: number
  size_bytes: number
}

export function listCameraRecordingsDaily(
  cameraId: string,
  range: { from: string; to: string; timeZone: string },
  signal?: AbortSignal,
) {
  const qs = new URLSearchParams({
    from: range.from,
    to: range.to,
    time_zone: range.timeZone,
  })
  return api.get<RecordingDayStat[]>(
    `/cameras/${cameraId}/recordings/daily?${qs}`,
    signal,
  )
}

/* -------------------------------------------------------------------------- */
/* Requests                                                                   */
/* -------------------------------------------------------------------------- */

export type RecordingFilters = {
  from?: string
  to?: string
  cursor?: string
  limit?: number
}

export function listCameraRecordings(
  cameraId: string,
  filters: RecordingFilters = {},
  signal?: AbortSignal,
) {
  const qs = new URLSearchParams()
  if (filters.from) qs.set("from", filters.from)
  if (filters.to) qs.set("to", filters.to)
  if (filters.cursor) qs.set("cursor", filters.cursor)
  qs.set("limit", String(filters.limit ?? 100))
  return api.get<RecordingSegmentPage>(
    `/cameras/${cameraId}/recordings?${qs}`,
    signal,
  )
}

export function getRecordingSegment(
  segmentId: string,
  signal?: AbortSignal,
) {
  return api.get<RecordingSegmentView>(`/recordings/${segmentId}`, signal)
}

export function listRecordingLocations(
  segmentId: string,
  signal?: AbortSignal,
) {
  return api.get<RecordingLocationView[]>(
    `/recordings/${segmentId}/locations`,
    signal,
  )
}

/** Resolve by segment id + offset. This is the stable public resolver. */
export function resolveSegmentPlayback(
  segmentId: string,
  offsetMs: number,
  signal?: AbortSignal,
) {
  return api.post<PlaybackResolve>(
    `/recordings/${segmentId}/playback/resolve`,
    { offset_ms: offsetMs },
    signal,
  )
}

/** Resolve by absolute wall-clock time; selects the covering segment first. */
export function resolveCameraPlayback(
  cameraId: string,
  at: string,
  signal?: AbortSignal,
) {
  return api.post<PlaybackResolve>(
    `/cameras/${cameraId}/playback/resolve`,
    { at },
    signal,
  )
}

/* -------------------------------------------------------------------------- */
/* Timeline                                                                   */
/* -------------------------------------------------------------------------- */

export type TimelineDetail = "minute" | "hour" | "day"

/** The aligned endpoint requires at least two cameras. */
export const MIN_ALIGNED_CAMERAS = 2
/** ...and refuses more than nine, even though a layout can hold sixteen tiles. */
export const MAX_ALIGNED_CAMERAS = 9

export function getCameraTimeline(
  cameraId: string,
  range: { from: string; to: string; detail?: TimelineDetail },
  signal?: AbortSignal,
) {
  const qs = new URLSearchParams({
    from: range.from,
    to: range.to,
  })
  if (range.detail) qs.set("detail", range.detail)
  return api.get<PlaybackTimelineView>(
    `/cameras/${cameraId}/timeline?${qs}`,
    signal,
  )
}

export type AlignedTimelineRequest = {
  /** 2–9 entries. A sixteen-tile wall has to be split across two calls. */
  cameraIds: string[]
  from: string
  to: string
  detail?: TimelineDetail
}

export function getAlignedTimeline(
  body: AlignedTimelineRequest,
  signal?: AbortSignal,
) {
  return api.post<PlaybackTimelineView[]>(
    "/playback/timeline",
    {
      // Wire field is snake_case (`PlaybackAlignedTimelineRequest`); sending
      // `cameraIds` here fails validation outright rather than being ignored.
      camera_ids: body.cameraIds,
      from: body.from,
      to: body.to,
      detail: body.detail ?? "minute",
    },
    signal,
  )
}

/* -------------------------------------------------------------------------- */
/* Presentation                                                               */
/* -------------------------------------------------------------------------- */

/**
 * An empty stretch of timeline is not a generic black bar. Each reason points
 * at a different operator action, so they stay visually distinct.
 */
export const GAP_REASON_LABEL: Record<TimelineGapReason, string> = {
  not_scheduled: "不在录制计划内",
  no_event: "事件触发但无匹配录制",
  source_lost: "摄像机信号丢失",
  runtime_restart: "媒体服务重启",
  storage_failure: "存储故障",
  missing_media: "媒体文件缺失",
  purged: "已按保留策略清理",
  unknown: "原因未知",
}

export function gapReasonLabel(reason: string): string {
  return (
    GAP_REASON_LABEL[reason as TimelineGapReason] ??
    GAP_REASON_LABEL.unknown
  )
}

export const AVAILABILITY_LABEL: Record<SegmentAvailability, string> = {
  local: "本地",
  remote: "远端归档",
  cached_remote: "远端（已回源）",
  missing: "缺失",
  corrupted: "损坏",
  purged: "已清理",
}

export function availabilityLabel(
  availability: SegmentAvailability,
): string {
  return AVAILABILITY_LABEL[availability] ?? availability
}

/** True when the segment exists but is not currently playable. */
export function needsRemoteRestore(
  availability: SegmentAvailability,
): boolean {
  return availability === "remote" || availability === "cached_remote"
}

/* -------------------------------------------------------------------------- */
/* Segment vocabulary                                                         */
/* -------------------------------------------------------------------------- */

/**
 * `RecordingCatalogService.recording_reasons` (`catalog.py:71-110`) builds
 * this from a fixed set of lowercase literals. A reason the backend has added
 * since is passed through rather than dropped, so a new recording cause shows
 * up as itself instead of as a blank cell.
 */
const REASON_LABEL: Record<string, string> = {
  continuous: "连续录像",
  schedule: "计划录像",
  manual: "手动触发",
  event: "事件触发",
}

export function recordingReasonLabel(reason: string): string {
  return REASON_LABEL[reason] ?? reason
}

/**
 * `PROVISIONAL` means the segment's time origin is still the ZLM hook's raw
 * stamp and has not been reconciled against a continuous media session — the
 * distinction ADR-0011 turns on. A file browser that hides it would let an
 * operator pull a clip for evidence without ever learning its timestamps are
 * not yet trustworthy, so it is shown rather than normalised away.
 */
const TIMING_STATUS_LABEL: Record<string, { label: string; tone: "online" | "degraded" | "unknown" }> = {
  FINAL: { label: "时间已校正", tone: "online" },
  PROVISIONAL: { label: "时间为暂定值", tone: "degraded" },
}

export function timingStatusLabel(status: string) {
  return TIMING_STATUS_LABEL[status] ?? { label: status, tone: "unknown" as const }
}

const TIMING_SOURCE_LABEL: Record<string, string> = {
  HOOK_RAW: "ZLM 原始戳",
  RECOVERY: "恢复重建",
  EXPLICIT_STOP: "显式停止",
  NORMALIZED: "已归一化",
}

export function timingSourceLabel(source: string): string {
  return TIMING_SOURCE_LABEL[source] ?? source
}

const INTEGRITY_LABEL: Record<string, { label: string; tone: "online" | "offline" | "degraded" | "unknown" }> = {
  OK: { label: "完整", tone: "online" },
  UNKNOWN: { label: "未校验", tone: "unknown" },
  TRUNCATED: { label: "不完整", tone: "degraded" },
  CORRUPT: { label: "已损坏", tone: "offline" },
}

export function integrityLabel(status: string) {
  return INTEGRITY_LABEL[status] ?? { label: status, tone: "unknown" as const }
}
