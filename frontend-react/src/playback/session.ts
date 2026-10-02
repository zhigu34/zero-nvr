/**
 * Mapping an absolute wall-clock instant onto concrete media.
 *
 * The backend deliberately never embeds storage URLs in a timeline; a segment
 * is only a logical id, and turning it into something playable is a separate
 * round trip. So the client has to do this mapping itself, twice: once to draw
 * the timeline, and once to decide what to resolve when the playhead moves.
 *
 * Both directions use milliseconds. `TimelineSegmentRef.start_at` is an
 * ISO-8601 instant and `PlaybackResolve` wants `offset_ms` from the start of
 * the chosen segment — mixing the two sends the player to a thousand times
 * the intended position, and lands outside the segment entirely.
 */
import type {
  PlaybackTimelineView,
  TimelineSegmentRef,
} from "../api/playback"
import { needsRemoteRestore } from "../api/playback"

/** Parse once; the timeline view is re-rendered on every animation frame. */
export function instantMs(iso: string): number {
  return new Date(iso).getTime()
}

export interface SegmentAtResult {
  segment: TimelineSegmentRef
  /** Milliseconds from the start of the segment. */
  offsetMs: number
}

/**
 * Every reader below treats a malformed timeline as "nothing here" rather than
 * throwing. The playback page renders on every animation frame, and a single
 * unexpected shape from one endpoint takes the whole screen down instead of
 * showing an empty track.
 */
function segmentsOf(timeline: PlaybackTimelineView | null) {
  return Array.isArray(timeline?.segments) ? timeline.segments : []
}

function gapsOf(timeline: PlaybackTimelineView | null) {
  return Array.isArray(timeline?.gaps) ? timeline.gaps : []
}

/**
 * Finds the playable segment covering `atMs`, or `null` when the instant falls
 * in a gap.
 *
 * Segments are searched in their returned order but the result is by explicit
 * containment, so an unsorted response is handled correctly rather than
 * silently resolving to the wrong clip.
 */
export function selectSegmentAt(
  timeline: PlaybackTimelineView | null,
  atMs: number,
): SegmentAtResult | null {
  for (const segment of segmentsOf(timeline)) {
    if (!segment?.start_at || !segment?.end_at) continue
    const start = instantMs(segment.start_at)
    const end = instantMs(segment.end_at)
    // Half-open: a segment ending exactly at `atMs` no longer covers it, and
    // its neighbour's start is the same instant.
    if (start <= atMs && atMs < end) {
      return { segment, offsetMs: Math.max(0, Math.round(atMs - start)) }
    }
  }
  return null
}

/** The gap containing `atMs`, if the instant falls inside one. */
export function gapAt(
  timeline: PlaybackTimelineView | null,
  atMs: number,
) {
  return (
    gapsOf(timeline).find(
      (gap) =>
        gap?.start_at != null &&
        gap?.end_at != null &&
        instantMs(gap.start_at) <= atMs &&
        atMs < instantMs(gap.end_at),
    ) ?? null
  )
}

/**
 * True when the segment exists but its media has to be pulled back from a
 * remote archive first, which turns the next resolve into a `pending` that
 * the UI has to poll rather than an immediate play.
 */
export function segmentNeedsRestore(segment: TimelineSegmentRef): boolean {
  return needsRemoteRestore(segment.availability)
}

/**
 * Next instant worth offering as a jump target, so a gap is navigable instead
 * of being a dead end. Returns `null` when there is nothing ahead — a
 * trailing gap is a legitimate end state, not a bug to paper over.
 */
export function nextPlayableInstant(
  timeline: PlaybackTimelineView | null,
  afterMs: number,
): number | null {
  let next: number | null = null
  for (const segment of segmentsOf(timeline)) {
    if (!segment?.start_at) continue
    const start = instantMs(segment.start_at)
    if (start <= afterMs) continue
    if (next !== null && start >= next) continue
    next = start
  }
  return next
}

/** The nearest playable instant strictly before `afterMs`, for stepping backwards. */
export function previousPlayableInstant(
  timeline: PlaybackTimelineView | null,
  afterMs: number,
): number | null {
  let previous: number | null = null
  for (const segment of segmentsOf(timeline)) {
    if (!segment?.end_at) continue
    const end = instantMs(segment.end_at)
    // A segment whose range ends exactly at `afterMs` does not cover that
    // instant — ranges are half-open, matching `selectSegmentAt` — so it is
    // not a jump target. Using `>=` here is what makes repeated presses keep
    // moving instead of returning the same instant forever.
    if (end >= afterMs) continue
    if (previous === null || end > previous) previous = end
  }
  return previous
}
