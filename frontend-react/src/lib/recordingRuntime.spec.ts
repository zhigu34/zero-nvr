import { describe, expect, it } from "vitest"

import type { RecordingRuntime } from "../api/recordingPolicies"
import {
  describeBlocker,
  formatMilliseconds,
  formatSeconds,
  judgeRuntime,
  runtimeTone,
} from "./recordingRuntime"

/**
 * This is G-18 in test form: a policy save that returns 200 is not evidence
 * that anything is being recorded, and `runtime.recording === null` is not
 * evidence that nothing is.
 */

function runtime(over: Partial<RecordingRuntime> = {}): RecordingRuntime {
  return {
    desired_mode: "persistent",
    recording: true,
    stream_online: true,
    changed: false,
    assumed_existing_mode: false,
    observed_at: "2026-10-01T00:00:00Z",
    blockers: [],
    ...over,
  }
}

describe("judgeRuntime", () => {
  it("reports a healthy camera as recording", () => {
    const verdict = judgeRuntime(runtime(), "continuous", true)
    expect(verdict.health).toBe("recording")
    expect(verdict.message).toBe("正在录制")
  })

  /**
   * The failure this whole module exists for: 200, no error, and nothing on
   * disk. The blocker is the only place the reason is given.
   */
  it("surfaces a swallowed stream-offline error as not recording", () => {
    const verdict = judgeRuntime(
      runtime({
        recording: false,
        stream_online: false,
        blockers: ["recording_stream_offline"],
      }),
      "continuous",
      true,
    )

    expect(verdict.health).toBe("not_recording")
    expect(verdict.message).toContain("码流离线")
    expect(verdict.blockers).toEqual(["recording_stream_offline"])
  })

  it("prefers a blocker over the recording flag", () => {
    // The flags can disagree with the blocker; the blocker is authoritative
    // because it carries the reason.
    const verdict = judgeRuntime(
      runtime({ recording: true, blockers: ["recording_storage_capacity_critical"] }),
      "continuous",
      true,
    )
    expect(verdict.health).toBe("not_recording")
    expect(verdict.message).toContain("存储容量")
  })

  it("joins several blockers rather than showing only the first", () => {
    const verdict = judgeRuntime(
      runtime({
        recording: false,
        blockers: ["recording_storage_unavailable", "recording_stream_offline"],
      }),
      "continuous",
      true,
    )
    expect(verdict.message).toContain("存储目标不可用")
    expect(verdict.message).toContain("码流离线")
  })

  it("keeps an unrecognised blocker code visible instead of dropping it", () => {
    // An unfamiliar code means the backend gained a failure mode; hiding it
    // would leave the operator with a stopped camera and no reason.
    const verdict = judgeRuntime(
      runtime({ recording: false, blockers: ["a_new_failure_mode"] }),
      "continuous",
      true,
    )
    expect(verdict.message).toContain("a_new_failure_mode")
  })

  /**
   * `null` means the media runtime cannot be observed. Drawing it as
   * "未录制" would send the operator after a fault that may not exist.
   */
  it("distinguishes unobservable from not-recording", () => {
    const verdict = judgeRuntime(
      runtime({ recording: null, stream_online: null }),
      "continuous",
      true,
    )
    expect(verdict.health).toBe("unobservable")
    expect(verdict.message).toContain("不可观测")
    expect(runtimeTone(verdict.health)).toBe("unknown")
  })

  it("reports no runtime as unknown rather than assuming anything", () => {
    const verdict = judgeRuntime(null, "continuous", true)
    expect(verdict.health).toBe("unknown")
    expect(verdict.message).toBe("尚未观测到录制状态")
  })

  it("does not blame the camera for a policy that asked for no recording", () => {
    const verdict = judgeRuntime(
      runtime({ recording: false, blockers: [] }),
      "disabled",
      true,
    )
    expect(verdict.health).toBe("not_configured_to_record")
  })

  it("respects the enabled flag independently of the mode", () => {
    const verdict = judgeRuntime(
      runtime({ recording: true }),
      "continuous",
      false,
    )
    expect(verdict.health).toBe("not_configured_to_record")
    expect(verdict.message).toContain("已停用")
  })

  it("distinguishes an offline stream from one that is still starting", () => {
    const offline = judgeRuntime(
      runtime({ recording: false, stream_online: false }),
      "continuous",
      true,
    )
    const starting = judgeRuntime(
      runtime({ recording: false, stream_online: true }),
      "continuous",
      true,
    )
    expect(offline.message).not.toBe(starting.message)
    expect(starting.message).toContain("启动")
  })

  it("survives a malformed runtime object", () => {
    const verdict = judgeRuntime(
      { blockers: null } as unknown as RecordingRuntime,
      "continuous",
      true,
    )
    expect(verdict.blockers).toEqual([])
    expect(verdict.health).not.toBe("recording")
  })
})

describe("describeBlocker", () => {
  it("falls back to the raw code", () => {
    expect(describeBlocker("mystery_code")).toContain("mystery_code")
  })
})

describe("duration formatting", () => {
  it("formats policy seconds", () => {
    expect(formatSeconds(300)).toBe("5 分钟")
    expect(formatSeconds(10)).toBe("10 秒")
    expect(formatSeconds(7200)).toBe("2 小时")
  })

  it("formats segment milliseconds in its own unit", () => {
    // The two appear side by side on the same page; a formatter that guessed
    // would render 300000 ms as "300000 分钟".
    expect(formatMilliseconds(300_000)).toBe("5 分钟")
    expect(formatMilliseconds(1500)).toBe("1.5 秒")
  })

  it("never emits NaN for a missing value", () => {
    expect(formatSeconds(Number.NaN)).toBe("—")
    expect(formatMilliseconds(Number.NaN)).toBe("—")
  })
})
