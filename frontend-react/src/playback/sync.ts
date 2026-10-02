/**
 * Synchronisation arbitration for multi-camera playback.
 *
 * In tolerant mode (the default) the master clock runs on its own and each
 * tile corrects itself, so this file only has to decide *what a tile reports*
 * about itself. In strict mode every tile must reach a shared barrier before
 * the master clock is allowed to advance, which makes the state classification
 * load-bearing rather than cosmetic.
 */
import type {
  PlaybackTimelineView,
  SegmentAvailability,
} from "../api/playback"

export type TileSyncState =
  | "unavailable"
  | "resolving"
  | "pending"
  | "gap"
  | "buffering"
  | "ready"

/**
 * Strict mode treats these as blockers. `ready` does not block, and neither
 * does `gap`: a canonical gap is a fact about the recording schedule, not a
 * malfunction, and blocking on it would freeze the whole wall forever because
 * that camera will never have media at that instant.
 */
export const STRICT_BLOCKING_STATES: ReadonlySet<TileSyncState> = new Set([
  "unavailable",
  "resolving",
  "pending",
  "buffering",
])

export function blocksStrict(state: TileSyncState): boolean {
  return STRICT_BLOCKING_STATES.has(state)
}

export interface TileSignals {
  /** A resolve request is in flight. */
  loading: boolean
  /** A previous resolve threw; `failure` is the message to show. */
  failure: string | null
  /** The media element fired `waiting` / `stalled`. */
  buffering: boolean
  /** The resolved media has produced a first frame and is not buffering. */
  mediaReady: boolean
  resolveStatus: "playable" | "pending" | "gap" | null
}

/**
 * Ordered most-urgent first. A tile that has failed must not be reported as
 * "resolving" just because a retry happens to be in flight — the operator
 * needs to see that it is broken.
 */
export function resolveTileSyncState(signals: TileSignals): TileSyncState {
  if (signals.failure !== null) return "unavailable"
  if (signals.loading) return "resolving"
  if (signals.resolveStatus === "pending") return "pending"
  if (signals.resolveStatus === "gap") return "gap"
  if (signals.buffering) return "buffering"
  if (signals.resolveStatus === "playable" && signals.mediaReady) {
    return "ready"
  }
  // Nothing has resolved yet, or it resolved but never painted a frame.
  return "resolving"
}

/**
 * Cameras that are holding up a strict barrier.
 *
 * A camera that has not reported a state counts as a blocker. That is
 * deliberately fail-closed: a tile that mounted late or whose WebSocket
 * message was lost must not be silently treated as ready, because "ready"
 * is what releases the barrier.
 */
export function strictBlockers(
  participantIds: readonly string[],
  states: ReadonlyMap<string, TileSyncState>,
): string[] {
  return participantIds.filter((id) => {
    const state = states.get(id)
    return state === undefined || blocksStrict(state)
  })
}

export function isStrictBarrierActive(args: {
  multiCamera: boolean
  strictMode: boolean
  playbackRequested: boolean
  blockers: readonly string[]
}): boolean {
  return (
    args.multiCamera &&
    args.strictMode &&
    args.playbackRequested &&
    args.blockers.length > 0
  )
}

/* -------------------------------------------------------------------------- */
/* Gap skipping                                                               */
/* -------------------------------------------------------------------------- */

/** These have media behind them; the rest are known-unplayable. */
const PLAYABLE_AVAILABILITY: ReadonlySet<SegmentAvailability> = new Set([
  "local",
  "remote",
  "cached_remote",
])

function timelineHasPlayableAt(
  timeline: PlaybackTimelineView,
  atMs: number,
): boolean {
  return timeline.recording_ranges.some(
    (range) =>
      PLAYABLE_AVAILABILITY.has(range.availability) &&
      new Date(range.start_at).getTime() <= atMs &&
      atMs < new Date(range.end_at).getTime(),
  )
}

/**
 * The next wall-clock instant at which *every* participating camera could
 * have media, or `null` when there is nothing worth skipping to.
 *
 * Returns `null` — deliberately — if even one camera still has playable media
 * at `afterMs`. Advancing the shared clock in that case would cut off a
 * camera that is working, and in tolerant mode one slow channel must never
 * freeze the others.
 */
export function findNextPlayableTime(
  timelines: readonly PlaybackTimelineView[],
  afterMs: number,
): number | null {
  if (timelines.length === 0) return null

  if (timelines.some((timeline) => timelineHasPlayableAt(timeline, afterMs))) {
    return null
  }

  let next: number | null = null
  for (const timeline of timelines) {
    for (const range of timeline.recording_ranges) {
      if (!PLAYABLE_AVAILABILITY.has(range.availability)) continue
      const startMs = new Date(range.start_at).getTime()
      if (startMs <= afterMs) continue
      if (next !== null && startMs >= next) continue
      next = startMs
    }
  }

  return next
}
