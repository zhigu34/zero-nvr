import { describe, expect, it } from "vitest"

import {
  classifyHlsError,
  describeStreamFailure,
  planHlsRecovery,
  type FailureContext,
  type HlsErrorLike,
} from "./errors"

const session: FailureContext = {
  hasMediaSession: true,
  everPainted: false,
}

function error(type: string, fatal = true): HlsErrorLike {
  return { type, fatal }
}

describe("classifyHlsError", () => {
  it("separates transport failures from decoder failures", () => {
    expect(classifyHlsError(error("networkError"))).toBe("network")
    expect(classifyHlsError(error("mediaError"))).toBe("media")
    expect(classifyHlsError(error("otherError"))).toBe("other")
  })

  it("does not care whether the error is fatal", () => {
    expect(classifyHlsError(error("networkError", false))).toBe("network")
    expect(classifyHlsError(error("mediaError", false))).toBe("media")
  })
})

describe("planHlsRecovery", () => {
  it("recovers a non-fatal error in place", () => {
    // hls.js emits these constantly during normal segment churn; tearing the
    // attachment down here would restart playback every few seconds.
    expect(planHlsRecovery(error("networkError", false))).toEqual({
      action: "restart",
    })
    expect(planHlsRecovery(error("mediaError", false))).toEqual({
      action: "restart",
    })
  })

  it("restarts on a fatal network error rather than rebuilding", () => {
    expect(planHlsRecovery(error("networkError"))).toEqual({
      action: "restart",
    })
  })

  it("recovers the decoder on a fatal media error", () => {
    expect(planHlsRecovery(error("mediaError"))).toEqual({
      action: "recover_media",
    })
  })

  it("rebuilds on an unrecognised fatal error", () => {
    expect(planHlsRecovery(error("somethingNew"))).toEqual({
      action: "rebuild",
    })
  })
})

describe("describeStreamFailure", () => {
  it("always produces a message with no undefined or NaN in it", () => {
    for (const kind of ["network", "media", "other"] as const) {
      for (const context of [
        { hasMediaSession: false, everPainted: false },
        { hasMediaSession: true, everPainted: false },
        { hasMediaSession: true, everPainted: true },
      ]) {
        const message = describeStreamFailure(kind, context)
        expect(message.length).toBeGreaterThan(0)
        expect(message).not.toMatch(/undefined|NaN|\[object/)
      }
    }
  })

  it("distinguishes a camera with no authorisation from a transport failure", () => {
    const noSession = describeStreamFailure("network", {
      hasMediaSession: false,
      everPainted: false,
    })
    expect(noSession).toContain("播放授权")
    expect(noSession).not.toBe(describeStreamFailure("network", session))
  })

  it("distinguishes a mid-stream drop from a stream that never started", () => {
    const dropped = describeStreamFailure("network", {
      hasMediaSession: true,
      everPainted: true,
    })
    const neverStarted = describeStreamFailure("network", session)

    expect(dropped).not.toBe(neverStarted)
    expect(dropped).toContain("中断")
  })

  it("names the compatibility transcode when one is in play", () => {
    const message = describeStreamFailure("media", {
      ...session,
      isCompatibilitySource: true,
    })
    expect(message).toContain("转码")
  })
})
