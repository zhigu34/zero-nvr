export type MasterClockState =
  | "playing"
  | "paused"
  | "seeking"

export interface MasterClockSnapshot {
  anchorMediaTimeMs: number
  anchorMonotonicMs: number
  playbackRate: number
  state: MasterClockState
  currentTimeMs: number
}

type MonotonicNow = () => number

export class MasterPlaybackClock {
  private anchorMediaTimeMs: number
  private anchorMonotonicMs: number
  private playbackRateValue = 1
  private stateValue: MasterClockState = "paused"

  constructor(
    initialMediaTimeMs: number,
    private readonly monotonicNow: MonotonicNow = () =>
      performance.now()
  ) {
    this.assertTime(initialMediaTimeMs)
    this.anchorMediaTimeMs = initialMediaTimeMs
    this.anchorMonotonicMs = this.monotonicNow()
  }

  get state(): MasterClockState {
    return this.stateValue
  }

  get playbackRate(): number {
    return this.playbackRateValue
  }

  currentTimeMs(): number {
    if (this.stateValue !== "playing") {
      return this.anchorMediaTimeMs
    }

    return (
      this.anchorMediaTimeMs +
      (this.monotonicNow() - this.anchorMonotonicMs) *
        this.playbackRateValue
    )
  }

  seek(mediaTimeMs: number): void {
    this.assertTime(mediaTimeMs)
    this.anchorMediaTimeMs = mediaTimeMs
    this.anchorMonotonicMs = this.monotonicNow()
    this.stateValue = "seeking"
  }

  play(
    mediaTimeMs = this.currentTimeMs(),
    playbackRate = this.playbackRateValue
  ): void {
    this.assertTime(mediaTimeMs)
    this.assertRate(playbackRate)
    this.anchorMediaTimeMs = mediaTimeMs
    this.anchorMonotonicMs = this.monotonicNow()
    this.playbackRateValue = playbackRate
    this.stateValue = "playing"
  }

  pause(
    mediaTimeMs = this.currentTimeMs()
  ): void {
    this.assertTime(mediaTimeMs)
    this.anchorMediaTimeMs = mediaTimeMs
    this.anchorMonotonicMs = this.monotonicNow()
    this.stateValue = "paused"
  }

  setPlaybackRate(playbackRate: number): void {
    this.assertRate(playbackRate)
    const current = this.currentTimeMs()
    this.anchorMediaTimeMs = current
    this.anchorMonotonicMs = this.monotonicNow()
    this.playbackRateValue = playbackRate
  }

  snapshot(): MasterClockSnapshot {
    return {
      anchorMediaTimeMs: this.anchorMediaTimeMs,
      anchorMonotonicMs: this.anchorMonotonicMs,
      playbackRate: this.playbackRateValue,
      state: this.stateValue,
      currentTimeMs: this.currentTimeMs()
    }
  }

  private assertTime(value: number): void {
    if (!Number.isFinite(value)) {
      throw new Error(
        "Master clock media time must be finite."
      )
    }
  }

  private assertRate(value: number): void {
    if (!Number.isFinite(value) || value <= 0) {
      throw new Error(
        "Master clock playback rate must be positive."
      )
    }
  }
}
