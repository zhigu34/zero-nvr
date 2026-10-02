/**
 * Timebase helpers for a single media element.
 *
 * An MP4 served by ZLM VOD usually starts at a non-zero timestamp origin — a
 * five-minute segment can begin at 123.5s into the container's timeline. If
 * that origin is applied twice, the playhead lands at 3 minutes instead of
 * where it should; if it is dropped, the whole drift calculation is offset by
 * the same amount. So the origin has to be established exactly once and only
 * from data the browser has actually confirmed.
 */

export function absoluteMediaTimeMs(
  anchorMs: number,
  currentTimeSeconds: number,
  originSeconds: number,
): number {
  return anchorMs + (currentTimeSeconds - originSeconds) * 1000
}

export function mediaTimelineOriginSeconds(
  currentTimeSeconds: number,
  seekableStartSeconds: number | null,
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

/**
 * How much to trust a candidate origin.
 *
 * The distinction exists because `loadedmetadata` fires before the browser
 * necessarily knows where the seekable range begins. A boolean `confirm` flag
 * cannot express "this is the final answer" versus "this is better than
 * nothing", and conflating them is what let a provisional origin get locked in
 * permanently.
 */
export type OriginConfidence = "provisional" | "weak" | "strong"

const RANK: Record<OriginConfidence, number> = {
  provisional: 0,
  weak: 1,
  strong: 2,
}

/**
 * The origin of an element that is currently ready to be seeked.
 *
 * Returns `null` when the element has no seekable range yet, which is the
 * signal that a candidate is not yet trustworthy as anything stronger than
 * provisional.
 */
export function mediaElementSeekableStartSeconds(
  element: HTMLMediaElement,
): number | null {
  try {
    if (element.seekable.length > 0) {
      return element.seekable.start(0)
    }
  } catch {
    // Some engines throw on a detached or zero-length TimeRanges.
  }
  return null
}

export function mediaElementTimelineOriginSeconds(
  element: HTMLMediaElement,
): number {
  return mediaTimelineOriginSeconds(
    element.currentTime,
    mediaElementSeekableStartSeconds(element),
  )
}

/**
 * Remembers the container time origin for one media element.
 *
 * A candidate replaces the stored origin only when it is *more* trustworthy
 * than what is already stored. That makes the tracker's job idempotent: a
 * stream of `timeupdate` events carrying stale candidates cannot drag the
 * origin backwards, and a late-arriving strong candidate always wins.
 */
export class MediaTimelineOriginTracker {
  private originSeconds: number | null = null
  private confidence: OriginConfidence = "provisional"

  get value(): number | null {
    return this.originSeconds
  }

  /**
   * Returns the origin now in effect. A candidate that is not more
   * trustworthy than the stored one is discarded, which is what stops a
   * zero-valued `currentTime` read at `loadedmetadata` from permanently
   * shadowing the real origin.
   */
  capture(
    candidateSeconds: number,
    confidence: OriginConfidence = "provisional",
  ): number {
    const candidate = Number.isFinite(candidateSeconds)
      ? Math.max(0, candidateSeconds)
      : // A media element can report currentTime as NaN while it is being
        // torn down. Fall back to the plain zero-based timebase rather than
        // storing NaN, which would poison every later subtraction.
        0

    if (
      this.originSeconds === null ||
      (Number.isFinite(candidateSeconds) &&
        RANK[confidence] > RANK[this.confidence])
    ) {
      this.originSeconds = candidate
      this.confidence = Number.isFinite(candidateSeconds)
        ? confidence
        : "provisional"
    }
    return this.originSeconds
  }

  /**
   * Convenience for the common case: take the element's own seekable start
   * when it has one (strong), otherwise fall back to a weak reading that a
   * later `canplay` is still allowed to replace.
   */
  captureFromElement(
    element: HTMLMediaElement,
    baseConfidence: OriginConfidence = "weak",
  ): number {
    const seekable = mediaElementSeekableStartSeconds(element)
    if (seekable !== null) {
      return this.capture(seekable, "strong")
    }
    return this.capture(element.currentTime, baseConfidence)
  }

  reset(): void {
    this.originSeconds = null
    this.confidence = "provisional"
  }
}
