import { describe, expect, it } from "vitest"

import { PlaybackDriftController } from "./driftController"

/**
 * Drift correction has three bands, and the middle one is deliberately
 * hysteretic so a player sitting near a threshold does not toggle between
 * "correcting" and "idle" every frame.
 *
 *   |drift| <  250ms  -> idle
 *   |drift| >= 1000ms -> hard seek
 *   in between         -> bounded temporary playback-rate correction,
 *                         entered at 250ms, left at 150ms
 *
 * Rate correction is additionally clamped to roughly 1.5%..4% and is not
 * re-evaluated more often than every 750ms, because a per-frame rate change
 * is audible on a video element.
 */
describe("PlaybackDriftController", () => {
  it("does nothing below the soft-enter threshold", () => {
    const controller = new PlaybackDriftController()

    expect(controller.evaluate(249, 1, 0)).toEqual({ kind: "none" })
    expect(controller.evaluate(-249, 1, 0)).toEqual({ kind: "none" })
  })

  it("hard-seeks at or beyond the severe-drift threshold", () => {
    const controller = new PlaybackDriftController()

    expect(controller.evaluate(1_000, 1, 0)).toEqual({ kind: "hard_seek" })
  })

  it("slows the media when it runs ahead of the master clock", () => {
    const controller = new PlaybackDriftController()
    const action = controller.evaluate(500, 1, 0)

    expect(action.kind).toBe("rate")
    if (action.kind !== "rate") return
    // drift 500ms -> normalized (500-150)/850 = 0.4118
    //            -> adjustment 1.5% + 0.4118*2.5% = 2.529%
    expect(action.playbackRate).toBeCloseTo(0.9747, 4)
  })

  it("speeds the media up when it lags the master clock", () => {
    const controller = new PlaybackDriftController()
    const action = controller.evaluate(-500, 1, 0)

    expect(action.kind).toBe("rate")
    if (action.kind !== "rate") return
    expect(action.playbackRate).toBeCloseTo(1.0253, 4)
  })

  it("scales the correction around the base rate, not around 1x", () => {
    const controller = new PlaybackDriftController()
    const action = controller.evaluate(500, 2, 0)

    expect(action.kind).toBe("rate")
    if (action.kind !== "rate") return
    // 2x * (1 - 0.025294)
    expect(action.playbackRate).toBeCloseTo(1.9494, 4)
  })

  it("keeps correcting inside the hysteresis band once activated", () => {
    const controller = new PlaybackDriftController()

    // Enter at 500ms, then drop into the 150..250 dead zone.
    controller.evaluate(500, 1, 0)
    const action = controller.evaluate(200, 1, 1_000)

    expect(action.kind).toBe("rate")
    if (action.kind !== "rate") return
    expect(action.playbackRate).toBeLessThan(1)
  })

  it("ignores the same dead zone when never activated", () => {
    const controller = new PlaybackDriftController()

    expect(controller.evaluate(200, 1, 0)).toEqual({ kind: "none" })
  })

  it("returns the base rate when drift falls back under the exit threshold", () => {
    const controller = new PlaybackDriftController()

    controller.evaluate(500, 1, 0)
    const action = controller.evaluate(100, 1, 1_000)

    expect(action).toEqual({ kind: "rate", playbackRate: 1 })
  })

  it("clamps the correction into roughly 1.5%..4%", () => {
    // Just past the exit threshold, but only reachable once correction is
    // engaged: the floor keeps a tiny residual drift from being ignored.
    const floor = new PlaybackDriftController()
    floor.evaluate(500, 1, 0)
    const nearExit = floor.evaluate(-151, 1, 1_000)
    expect(nearExit.kind).toBe("rate")
    if (nearExit.kind === "rate") {
      expect(nearExit.playbackRate).toBeCloseTo(1.015, 2)
    }

    // Just below a hard seek: the ceiling keeps a near-severe drift from
    // asking the decoder for an unplayable rate.
    const ceiling = new PlaybackDriftController().evaluate(999, 1, 0)
    expect(ceiling.kind).toBe("rate")
    if (ceiling.kind === "rate") {
      expect(ceiling.playbackRate).toBeCloseTo(0.96, 2)
    }
  })

  it("does not re-evaluate the rate inside the cooldown window", () => {
    const controller = new PlaybackDriftController()

    expect(controller.evaluate(500, 1, 0).kind).toBe("rate")
    expect(controller.evaluate(500, 1, 300)).toEqual({ kind: "none" })
    expect(controller.evaluate(500, 1, 749)).toEqual({ kind: "none" })
    expect(controller.evaluate(500, 1, 750).kind).toBe("rate")
  })

  it("does not hard-seek twice inside its own cooldown", () => {
    const controller = new PlaybackDriftController()

    expect(controller.evaluate(5_000, 1, 0)).toEqual({ kind: "hard_seek" })
    expect(controller.evaluate(5_000, 1, 500)).toEqual({ kind: "none" })
    expect(controller.evaluate(5_000, 1, 1_000)).toEqual({ kind: "hard_seek" })
  })

  it("stays idle right after a hard seek", () => {
    const controller = new PlaybackDriftController()

    controller.evaluate(5_000, 1, 0)
    // A 400ms drift would normally be corrected, but the player has just been
    // yanked back to the master clock; give it a moment to settle.
    expect(controller.evaluate(400, 1, 100)).toEqual({ kind: "none" })
  })

  it("honours custom thresholds", () => {
    const controller = new PlaybackDriftController({
      softEnterMs: 100,
      softExitMs: 50,
      hardSeekMs: 500,
    })

    expect(controller.evaluate(150, 1, 0).kind).toBe("rate")
    expect(controller.evaluate(500, 1, 0)).toEqual({ kind: "hard_seek" })
  })

  it("ignores nonsense input instead of corrupting the player", () => {
    const controller = new PlaybackDriftController()

    expect(controller.evaluate(Number.NaN, 1, 0)).toEqual({ kind: "none" })
    expect(controller.evaluate(500, 0, 0)).toEqual({ kind: "none" })
    expect(controller.evaluate(500, -1, 0)).toEqual({ kind: "none" })
    expect(controller.evaluate(500, 1, Number.NaN)).toEqual({ kind: "none" })
  })

  it("arms itself for immediate use after a reset", () => {
    const controller = new PlaybackDriftController()

    controller.evaluate(5_000, 1, 0)
    controller.reset(10_000)

    // A fresh segment owns a new controller state: the cooldowns from the
    // previous segment must not silence the first correction.
    expect(controller.evaluate(5_000, 1, 10_000)).toEqual({
      kind: "hard_seek"
    })
  })
})
