import { describe, expect, it } from "vitest"

import { ServerResyncArbiter } from "./serverResync"

/**
 * These mirror the behavioural contract the Vue `TolerantPlaybackTile`
 * asserted through a 608-line component. The sequence in the first two
 * tests is the one that matters: a startup-sized drift is absorbed by rate
 * correction, the *next* severe drift re-resolves on the server, and a third
 * drift does not re-resolve again.
 */
describe("ServerResyncArbiter", () => {
  it("leaves startup-sized drift to the soft controller", () => {
    const arbiter = new ServerResyncArbiter()

    // +2000ms is past the soft controller's 1000ms hard-seek band, so the
    // controller has already answered with a rate correction. Re-resolving
    // here would restart the stream on every hiccup at startup.
    expect(arbiter.evaluate(-2_000, 1, 0)).toEqual({ kind: "none" })
  })

  it("re-resolves on the server for a severe drift, then stops re-resolving", () => {
    const arbiter = new ServerResyncArbiter()

    // 1. Startup drift: rate correction, no stream restart.
    expect(arbiter.evaluate(-2_000, 1, 0)).toEqual({ kind: "none" })

    // 2. Severe drift: ask the server for media at the current master time
    //    instead of hard-seeking the element.
    expect(arbiter.evaluate(-6_000, 1, 1_000)).toEqual({
      kind: "server_resolve",
    })

    // 3. The gate is now spent, so further drift must not queue a second
    //    re-resolve; it falls back to a local rate nudge.
    const third = arbiter.evaluate(-6_500, 1, 2_000)
    expect(third.kind).toBe("rate")
  })

  it("re-arms only once the drift has actually converged", () => {
    const arbiter = new ServerResyncArbiter()

    expect(arbiter.evaluate(6_000, 1, 0)).toEqual({ kind: "server_resolve" })
    // Gate spent: a severe drift right afterwards must not re-resolve.
    expect(arbiter.evaluate(6_000, 1, 5_000).kind).not.toBe("server_resolve")

    // Converge.
    expect(arbiter.evaluate(100, 1, 6_000)).toEqual({ kind: "none" })

    // Now a severe drift is allowed to re-resolve again.
    expect(arbiter.evaluate(6_000, 1, 7_000)).toEqual({
      kind: "server_resolve",
    })
  })

  it("treats a persistent moderate drift as never severe", () => {
    const arbiter = new ServerResyncArbiter()

    // 400ms stays above the re-arm threshold, so the gate is never restored,
    // and it stays below the 5000ms severe threshold, so nothing happens.
    expect(arbiter.evaluate(400, 1, 0)).toEqual({ kind: "none" })
    expect(arbiter.evaluate(4_000, 1, 1_000)).toEqual({ kind: "none" })
    expect(arbiter.evaluate(4_999, 1, 2_000)).toEqual({ kind: "none" })
  })

  it("treats the severe threshold as inclusive", () => {
    const arbiter = new ServerResyncArbiter()

    expect(arbiter.evaluate(5_000, 1, 0)).toEqual({
      kind: "server_resolve",
    })
  })

  it("slows a channel that has run ahead", () => {
    const arbiter = new ServerResyncArbiter()
    arbiter.evaluate(6_000, 1, 0) // spend the gate

    const decision = arbiter.evaluate(6_000, 1, 1_000)
    expect(decision.kind).toBe("rate")
    if (decision.kind !== "rate") return
    expect(decision.playbackRate).toBeLessThan(1)
  })

  it("speeds a channel that has fallen behind", () => {
    const arbiter = new ServerResyncArbiter()
    arbiter.evaluate(-6_000, 1, 0)

    const decision = arbiter.evaluate(-6_000, 1, 1_000)
    expect(decision.kind).toBe("rate")
    if (decision.kind !== "rate") return
    expect(decision.playbackRate).toBeGreaterThan(1)
  })

  it("keeps the local nudge inside the configured clamp", () => {
    // The Vue version hard-coded ±8% here regardless of configuration. A
    // caller asking for a tighter clamp must actually get one.
    const arbiter = new ServerResyncArbiter({
      maxRateAdjustment: 0.02,
      hardSeekMs: 5_000,
    })
    arbiter.evaluate(50_000, 1, 0)

    const decision = arbiter.evaluate(50_000, 1, 1_000)
    expect(decision.kind).toBe("rate")
    if (decision.kind !== "rate") return
    expect(decision.playbackRate).toBeGreaterThanOrEqual(0.98)
    expect(decision.playbackRate).toBeLessThanOrEqual(1.02)
  })

  it("respects the re-evaluation cooldown", () => {
    const arbiter = new ServerResyncArbiter({ rateCooldownMs: 750 })
    arbiter.evaluate(6_000, 1, 0)

    expect(arbiter.evaluate(6_000, 1, 300)).toEqual({ kind: "none" })
    expect(arbiter.evaluate(6_000, 1, 1_000).kind).toBe("rate")
  })

  it("starts armed after a reset", () => {
    const arbiter = new ServerResyncArbiter()
    arbiter.evaluate(6_000, 1, 0)
    arbiter.reset(10_000)

    // A fresh resolve for a new segment must be allowed to re-resolve once.
    expect(arbiter.evaluate(6_000, 1, 10_000)).toEqual({
      kind: "server_resolve",
    })
  })

  it("ignores nonsense input", () => {
    const arbiter = new ServerResyncArbiter()

    expect(arbiter.evaluate(Number.NaN, 1, 0)).toEqual({ kind: "none" })
    expect(arbiter.evaluate(6_000, 0, 0)).toEqual({ kind: "none" })
    expect(arbiter.evaluate(6_000, 1, Number.NaN)).toEqual({ kind: "none" })
  })

  it("ignores a zero drift entirely", () => {
    const arbiter = new ServerResyncArbiter()
    expect(arbiter.evaluate(0, 1, 0)).toEqual({ kind: "none" })
  })
})
