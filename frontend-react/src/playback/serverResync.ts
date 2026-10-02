/**
 * Decides what a multi-camera tile does when it falls badly out of sync.
 *
 * This sits *after* `PlaybackDriftController`, which already owns the soft
 * band (250ms..1000ms) and answers with a bounded rate tweak. This arbiter
 * only ever sees a drift the controller has already given up on, i.e. one it
 * classified as `hard_seek`.
 *
 * The Vue implementation did two things here that are worth keeping and one
 * that is not:
 *
 * - **Kept:** a severe drift is corrected by asking the server to re-resolve
 *   media for the current master time, not by yanking the browser's
 *   `currentTime`. A `media` element seek on a ZLM VOD stream drops buffered
 *   data and visibly stalls; a re-resolve hands back a stream that already
 *   starts at the right offset.
 * - **Kept:** re-resolution is armed by a one-shot gate. Re-resolving produces
 *   a stream that starts slightly off, which would immediately look like
 *   another severe drift — so the gate has to be re-armed by drift actually
 *   converging, not merely by time passing.
 * - **Dropped:** the Vue version hard-coded `base * 0.92` / `base * 1.08` in
 *   this branch, bypassing the configured clamp and the re-evaluation
 *   cooldown. Here the magnitude comes from `maxRateAdjustment` like every
 *   other correction, so a caller cannot accidentally ask the decoder for a
 *   rate it never agreed to.
 */

export type ResyncDecision =
  | { kind: "none" }
  | { kind: "rate"; playbackRate: number }
  /** Ask the server to resolve media for the current master time. */
  | { kind: "server_resolve" }

export interface ServerResyncOptions {
  /**
   * Drift at or above which the browser is considered too far out to fix
   * locally. The single-camera controller uses 1000ms; a multi-camera tile
   * tolerates more because the drift is measured against an already
   * independently-advancing master clock.
   */
  hardSeekMs?: number
  /** Drift that counts as "converged", re-arming the gate. */
  rearmDriftMs?: number
  maxRateAdjustment?: number
  /** Floor for the local rate nudge taken while the gate is spent. */
  minRateAdjustment?: number
  /** Re-evaluation cooldown for that nudge, matching the soft controller. */
  rateCooldownMs?: number
}

export class ServerResyncArbiter {
  private readonly hardSeekMs: number
  private readonly rearmDriftMs: number
  private readonly maxRateAdjustment: number
  private readonly minRateAdjustment: number
  private readonly rateCooldownMs: number

  private armed = true
  private lastRateChangeAt = Number.NEGATIVE_INFINITY

  constructor(options: ServerResyncOptions = {}) {
    this.hardSeekMs = options.hardSeekMs ?? 5_000
    this.rearmDriftMs = options.rearmDriftMs ?? 250
    this.maxRateAdjustment = options.maxRateAdjustment ?? 0.08
    this.minRateAdjustment = options.minRateAdjustment ?? 0.015
    this.rateCooldownMs = options.rateCooldownMs ?? 750
  }

  /** Re-arms the gate; a new segment or a fresh resolve starts clean. */
  reset(monotonicNowMs: number): void {
    this.armed = true
    this.lastRateChangeAt = monotonicNowMs - this.rateCooldownMs
  }

  evaluate(
    driftMs: number,
    basePlaybackRate: number,
    monotonicNowMs: number,
  ): ResyncDecision {
    if (
      !Number.isFinite(driftMs) ||
      !Number.isFinite(basePlaybackRate) ||
      basePlaybackRate <= 0 ||
      !Number.isFinite(monotonicNowMs)
    ) {
      return { kind: "none" }
    }

    const magnitude = Math.abs(driftMs)

    // Converged: put the gate back so the next severe drift may re-resolve.
    if (magnitude <= this.rearmDriftMs) {
      this.armed = true
      return { kind: "none" }
    }

    // Still inside the soft controller's territory — it owns this drift.
    if (magnitude < this.hardSeekMs) {
      return { kind: "none" }
    }

    if (this.armed) {
      this.armed = false
      // A re-resolve is a large action on the media pipeline. Start the
      // cooldown here too, so the channel is not immediately re-tuned while
      // the new stream is still arriving.
      this.lastRateChangeAt = monotonicNowMs
      return { kind: "server_resolve" }
    }

    // The gate is spent: a re-resolve is already in flight, so pulling the
    // media element around again would fight it. Nudge locally instead.
    if (monotonicNowMs - this.lastRateChangeAt < this.rateCooldownMs) {
      return { kind: "none" }
    }
    this.lastRateChangeAt = monotonicNowMs

    const normalized = Math.min(
      1,
      Math.max(
        0,
        (magnitude - this.hardSeekMs) /
          Math.max(1, this.hardSeekMs * 2 - this.hardSeekMs),
      ),
    )
    const adjustment = Math.max(
      this.minRateAdjustment,
      Math.min(
        this.maxRateAdjustment,
        this.minRateAdjustment +
          normalized * (this.maxRateAdjustment - this.minRateAdjustment),
      ),
    )

    return {
      kind: "rate",
      playbackRate:
        basePlaybackRate * (driftMs > 0 ? 1 - adjustment : 1 + adjustment),
    }
  }
}
