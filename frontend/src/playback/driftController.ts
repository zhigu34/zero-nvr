export type DriftCorrectionAction =
  | {
      kind: "none"
    }
  | {
      kind: "rate"
      playbackRate: number
    }
  | {
      kind: "hard_seek"
    }

export interface PlaybackDriftControllerOptions {
  softEnterMs?: number
  softExitMs?: number
  hardSeekMs?: number
  rateCooldownMs?: number
  hardSeekCooldownMs?: number
  maxRateAdjustment?: number
  minRateAdjustment?: number
}

export class PlaybackDriftController {
  private readonly softEnterMs: number
  private readonly softExitMs: number
  private readonly hardSeekMs: number
  private readonly rateCooldownMs: number
  private readonly hardSeekCooldownMs: number
  private readonly maxRateAdjustment: number
  private readonly minRateAdjustment: number

  private correctionActive = false
  private lastRateChangeAt =
    Number.NEGATIVE_INFINITY
  private lastHardSeekAt =
    Number.NEGATIVE_INFINITY

  constructor(
    options: PlaybackDriftControllerOptions = {}
  ) {
    this.softEnterMs = options.softEnterMs ?? 250
    this.softExitMs = options.softExitMs ?? 150
    this.hardSeekMs = options.hardSeekMs ?? 1000
    this.rateCooldownMs =
      options.rateCooldownMs ?? 750
    this.hardSeekCooldownMs =
      options.hardSeekCooldownMs ?? 1000
    this.maxRateAdjustment =
      options.maxRateAdjustment ?? 0.04
    this.minRateAdjustment =
      options.minRateAdjustment ?? 0.015
  }

  reset(monotonicNowMs: number): void {
    this.correctionActive = false
    this.lastRateChangeAt =
      monotonicNowMs - this.rateCooldownMs
    this.lastHardSeekAt =
      monotonicNowMs -
      this.hardSeekCooldownMs
  }

  evaluate(
    driftMs: number,
    basePlaybackRate: number,
    monotonicNowMs: number
  ): DriftCorrectionAction {
    if (
      !Number.isFinite(driftMs) ||
      !Number.isFinite(basePlaybackRate) ||
      basePlaybackRate <= 0 ||
      !Number.isFinite(monotonicNowMs)
    ) {
      return { kind: "none" }
    }

    const magnitude = Math.abs(driftMs)

    if (magnitude >= this.hardSeekMs) {
      if (
        monotonicNowMs - this.lastHardSeekAt <
        this.hardSeekCooldownMs
      ) {
        return { kind: "none" }
      }

      this.correctionActive = false
      this.lastHardSeekAt = monotonicNowMs
      this.lastRateChangeAt = monotonicNowMs
      return { kind: "hard_seek" }
    }

    if (
      monotonicNowMs - this.lastHardSeekAt <
      this.hardSeekCooldownMs
    ) {
      return { kind: "none" }
    }

    if (this.correctionActive) {
      if (magnitude <= this.softExitMs) {
        this.correctionActive = false
        this.lastRateChangeAt = monotonicNowMs
        return {
          kind: "rate",
          playbackRate: basePlaybackRate
        }
      }
    } else if (magnitude >= this.softEnterMs) {
      this.correctionActive = true
    } else {
      return { kind: "none" }
    }

    if (
      monotonicNowMs - this.lastRateChangeAt <
      this.rateCooldownMs
    ) {
      return { kind: "none" }
    }

    this.lastRateChangeAt = monotonicNowMs
    const normalized = Math.min(
      1,
      Math.max(
        0,
        (magnitude - this.softExitMs) /
          Math.max(
            1,
            this.hardSeekMs - this.softExitMs
          )
      )
    )
    const adjustment = Math.max(
      this.minRateAdjustment,
      Math.min(
        this.maxRateAdjustment,
        this.minRateAdjustment +
          normalized *
            (
              this.maxRateAdjustment -
              this.minRateAdjustment
            )
      )
    )

    return {
      kind: "rate",
      playbackRate:
        basePlaybackRate *
        (
          driftMs > 0
            ? 1 - adjustment
            : 1 + adjustment
        )
    }
  }
}
