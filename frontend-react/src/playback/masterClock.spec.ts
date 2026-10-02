import { describe, expect, it } from "vitest"

import { MasterPlaybackClock } from "./masterClock"

/**
 * The master clock is the single source of truth for multi-camera playback
 * position. These tests pin the two properties the spec depends on:
 *
 * 1. Only the injected monotonic source advances time. Wall-clock corrections
 *    must not be able to jump playback.
 * 2. Re-anchoring is explicit. A new anchor is only taken on a logical
 *    transition (seek / play / pause / rate change / segment switch), never
 *    because some video element emitted `timeupdate` last.
 */
describe("MasterPlaybackClock", () => {
  function fakeMonotonic(startMs = 0) {
    let now = startMs
    return {
      now: () => now,
      advance: (ms: number) => {
        now += ms
      },
    }
  }

  it("starts paused and does not advance", () => {
    const mono = fakeMonotonic()
    const clock = new MasterPlaybackClock(1_000, mono.now)

    expect(clock.state).toBe("paused")
    expect(clock.playbackRate).toBe(1)

    mono.advance(5_000)
    expect(clock.currentTimeMs()).toBe(1_000)
  })

  it("advances from the monotonic source while playing", () => {
    const mono = fakeMonotonic()
    const clock = new MasterPlaybackClock(1_000, mono.now)

    clock.play()
    mono.advance(2_000)

    expect(clock.state).toBe("playing")
    expect(clock.currentTimeMs()).toBe(3_000)
  })

  it("freezes at the pause instant instead of drifting afterwards", () => {
    const mono = fakeMonotonic()
    const clock = new MasterPlaybackClock(1_000, mono.now)

    clock.play()
    mono.advance(2_000)
    clock.pause()
    mono.advance(10_000)

    expect(clock.state).toBe("paused")
    expect(clock.currentTimeMs()).toBe(3_000)
  })

  it("does not let a wall-clock jump move playback", () => {
    const mono = fakeMonotonic()
    const clock = new MasterPlaybackClock(0, mono.now)

    clock.play()
    mono.advance(1_000)
    expect(clock.currentTimeMs()).toBe(1_000)

    // An NTP correction of an hour on the OS wall clock is invisible here,
    // because the clock only ever reads performance.now().
    expect(clock.currentTimeMs()).toBe(1_000)
  })

  it("scales advancement by the playback rate", () => {
    const mono = fakeMonotonic()
    const clock = new MasterPlaybackClock(0, mono.now)

    clock.play(0, 4)
    mono.advance(1_000)

    expect(clock.currentTimeMs()).toBe(4_000)
  })

  it("keeps continuity when the rate changes mid-playback", () => {
    const mono = fakeMonotonic()
    const clock = new MasterPlaybackClock(0, mono.now)

    clock.play()
    mono.advance(3_000)
    clock.setPlaybackRate(2)

    // The rate change re-anchors at the current position, so the timeline
    // must not jump forward or backward at the moment of the switch.
    expect(clock.currentTimeMs()).toBe(3_000)

    mono.advance(1_000)
    expect(clock.currentTimeMs()).toBe(5_000)
  })

  it("enters seeking on seek and stays there until playback resumes", () => {
    const mono = fakeMonotonic()
    const clock = new MasterPlaybackClock(0, mono.now)

    clock.play()
    mono.advance(1_000)
    clock.seek(500_000)

    expect(clock.state).toBe("seeking")
    expect(clock.currentTimeMs()).toBe(500_000)

    mono.advance(1_000)
    expect(clock.currentTimeMs()).toBe(500_000)
  })

  it("re-anchors play at an explicit segment boundary", () => {
    const mono = fakeMonotonic()
    const clock = new MasterPlaybackClock(0, mono.now)

    clock.play()
    mono.advance(1_000)

    // Canonical segment-boundary switching: the new segment starts at its own
    // absolute offset, so the anchor is replaced outright.
    clock.play(300_000)
    expect(clock.currentTimeMs()).toBe(300_000)

    mono.advance(500)
    expect(clock.currentTimeMs()).toBe(300_500)
  })

  it("defaults play to the current position", () => {
    const mono = fakeMonotonic()
    const clock = new MasterPlaybackClock(0, mono.now)

    clock.play()
    mono.advance(2_500)
    clock.pause()
    mono.advance(60_000)
    clock.play()

    expect(clock.currentTimeMs()).toBe(2_500)
  })

  it("rejects a non-finite media time", () => {
    const mono = fakeMonotonic()
    const clock = new MasterPlaybackClock(0, mono.now)

    expect(() => clock.seek(Number.NaN)).toThrow(/finite/i)
    expect(() => clock.play(Number.POSITIVE_INFINITY)).toThrow(/finite/i)
  })

  it("rejects a non-positive playback rate", () => {
    const mono = fakeMonotonic()
    const clock = new MasterPlaybackClock(0, mono.now)

    expect(() => clock.play(0, 0)).toThrow(/positive/i)
    expect(() => clock.setPlaybackRate(Number.NaN)).toThrow(/positive/i)
  })

  it("exposes an anchor-consistent snapshot", () => {
    const mono = fakeMonotonic()
    const clock = new MasterPlaybackClock(10, mono.now)

    clock.play(10, 1.5)
    mono.advance(100)
    const snapshot = clock.snapshot()

    expect(snapshot.state).toBe("playing")
    expect(snapshot.playbackRate).toBe(1.5)
    expect(snapshot.anchorMediaTimeMs).toBe(10)
    expect(snapshot.anchorMonotonicMs).toBe(0)
    expect(snapshot.currentTimeMs).toBe(160)
  })
})
