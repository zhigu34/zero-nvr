export function absoluteMediaTimeMs(
  anchorMs: number,
  currentTimeSeconds: number,
  originSeconds: number
): number {
  return (
    anchorMs +
    (currentTimeSeconds - originSeconds) * 1000
  )
}

export function mediaTimelineOriginSeconds(
  currentTimeSeconds: number,
  seekableStartSeconds: number | null
): number {
  if (
    seekableStartSeconds !== null &&
    Number.isFinite(seekableStartSeconds)
  ) {
    return Math.max(0, seekableStartSeconds)
  }
  if (Number.isFinite(currentTimeSeconds)) {
    return Math.max(0, currentTimeSeconds)
  }
  return 0
}

export function mediaElementTimelineOriginSeconds(
  element: HTMLMediaElement
): number {
  let seekableStartSeconds: number | null = null
  try {
    if (element.seekable.length > 0) {
      seekableStartSeconds = element.seekable.start(0)
    }
  } catch {
    seekableStartSeconds = null
  }
  return mediaTimelineOriginSeconds(
    element.currentTime,
    seekableStartSeconds
  )
}

export class MediaTimelineOriginTracker {
  private originSeconds: number | null = null
  private confirmed = false

  get value(): number | null {
    return this.originSeconds
  }

  capture(
    candidateSeconds: number,
    confirm: boolean
  ): number {
    if (
      this.originSeconds === null ||
      (confirm && !this.confirmed)
    ) {
      this.originSeconds = candidateSeconds
    }
    if (confirm) this.confirmed = true
    return this.originSeconds
  }

  reset(): void {
    this.originSeconds = null
    this.confirmed = false
  }
}
