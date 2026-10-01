import { mount } from "@vue/test-utils"
import { describe, expect, it, vi } from "vitest"

import PlaybackDiagnosticsPanel from "./PlaybackDiagnosticsPanel.vue"

vi.mock("vue-i18n", () => ({
  useI18n: () => ({ t: (key: string) => key })
}))

const baseProps = {
  diagnosticClock: {
    anchorMediaTimeMs: 0,
    anchorMonotonicMs: 0,
    playbackRate: 1,
    state: "paused" as const,
    currentTimeMs: 1_000
  },
  diagnosticResolverState: "idle",
  playbackControlActive: false,
  playbackRate: 1,
  multiCameraMode: false,
  syncMode: "tolerant" as const,
  playbackParticipants: [{ id: "camera-a", name: "Lobby" }],
  skipGaps: false,
  activeSegmentId: null,
  activeTimelineSegment: null,
  standbySegment: null,
  standbyReady: false,
  playbackResult: null,
  gapResult: null,
  activeMediaDiagnostics: {
    readyState: "enough-data",
    currentTimeSeconds: 1.25,
    mediaTimeMs: 1_250,
    driftMs: 250,
    playbackRate: 1,
    paused: false,
    seeking: false
  },
  syncTileStates: {},
  formatTimestamp: (date: Date) => String(date.getTime()),
  formatDiagnosticMs: (value: number | null) => `${value} ms`,
  translatedStatus: (value: string) => `status:${value}`,
  translatedReason: (value: string) => `reason:${value}`
}

describe("PlaybackDiagnosticsPanel", () => {
  it("shows single-camera media diagnostics and closes on request", async () => {
    const wrapper = mount(PlaybackDiagnosticsPanel, {
      props: baseProps
    })

    expect(wrapper.text()).toContain("status:paused")
    expect(wrapper.text()).toContain("status:enough-data")
    expect(wrapper.text()).toContain("1.250 s")
    expect(wrapper.text()).toContain("250 ms")
    expect(wrapper.text()).not.toContain("playback.syncChannels")

    await wrapper.find("header button").trigger("click")
    expect(wrapper.emitted("close")).toHaveLength(1)
  })

  it("shows each synchronized camera and its strict blocker state", () => {
    const wrapper = mount(PlaybackDiagnosticsPanel, {
      props: {
        ...baseProps,
        multiCameraMode: true,
        syncMode: "strict",
        playbackParticipants: [
          { id: "camera-a", name: "Lobby" },
          { id: "camera-b", name: "Garage" }
        ],
        syncTileStates: {
          "camera-a": { state: "ready", blocksStrict: false },
          "camera-b": { state: "gap", blocksStrict: true }
        }
      }
    })

    expect(wrapper.text()).toContain("status:strict · 2")
    expect(wrapper.text()).toContain("Lobby")
    expect(wrapper.text()).toContain("Garage")
    expect(wrapper.text()).toContain("status:gap")
    expect(wrapper.text()).toContain("playback.strictBlocker")
    expect(wrapper.text()).not.toContain("playback.activeMedia")
  })
})
