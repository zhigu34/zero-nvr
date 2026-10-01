import { mount } from "@vue/test-utils"
import { describe, expect, it, vi } from "vitest"

import type { PlaybackPlayable } from "../../api/playback"
import PlaybackControls from "./PlaybackControls.vue"

vi.mock("vue-i18n", () => ({
  useI18n: () => ({ t: (key: string) => key })
}))

const baseProps = {
  playbackControlActive: false,
  highSpeedMuted: false,
  effectiveMuted: true,
  playbackRate: 1 as const,
  playbackRateOptions: [0.5, 1, 2, 4, 8] as (0.5 | 1 | 2 | 4 | 8)[],
  diagnosticsOpen: false,
  currentAt: new Date("2026-09-30T00:00:00Z"),
  formatTimestamp: () => "30 Sep 08:00",
  canProtect: true,
  canExport: true,
  multiCameraMode: false,
  playbackResult: null
}

describe("PlaybackControls", () => {
  it("routes playback, mute, speed, diagnostics and action controls", async () => {
    const wrapper = mount(PlaybackControls, { props: baseProps })

    expect(wrapper.find('button[aria-label="playback.play"]').exists()).toBe(true)
    expect(wrapper.text()).toContain("30 Sep 08:00")
    await wrapper.find('button[aria-label="playback.play"]').trigger("click")
    await wrapper.find('button[aria-label="playback.unmute"]').trigger("click")
    await wrapper.findAll(".playback-speed-switcher button")[2].trigger("click")
    await wrapper.find('.playback-controls > button.media-button--text').trigger("click")
    await wrapper.findAll(".playback-action-buttons button")[0].trigger("click")
    await wrapper.findAll(".playback-action-buttons button")[1].trigger("click")

    expect(wrapper.emitted("toggle-playback")).toHaveLength(1)
    expect(wrapper.emitted("toggle-mute")).toHaveLength(1)
    expect(wrapper.emitted("set-rate")?.[0]).toEqual([2])
    expect(wrapper.emitted("update:diagnosticsOpen")?.[0]).toEqual([true])
    expect(wrapper.emitted("open-action")).toEqual([["protect"], ["export"]])
  })

  it("disables mute at high speed and hides actions without permission", () => {
    const wrapper = mount(PlaybackControls, {
      props: {
        ...baseProps,
        playbackControlActive: true,
        highSpeedMuted: true,
        canProtect: false,
        canExport: false,
        multiCameraMode: true
      }
    })

    expect(wrapper.find('button[aria-label="playback.pause"]').exists()).toBe(true)
    expect(wrapper.find('button[aria-label="playback.highSpeedMutedLabel"]').attributes("disabled")).toBeDefined()
    expect(wrapper.findAll(".playback-action-buttons button")).toHaveLength(0)
    expect(wrapper.find(".playback-codec").text()).toBe("playback.tolerantSync")
  })

  it("shows the resolved codec for a single playable camera", () => {
    const playbackResult: PlaybackPlayable = {
      status: "playable",
      segment_id: "segment-a",
      segment_start_at: "2026-09-30T00:00:00Z",
      offset_ms: 0,
      transport: "mp4",
      url: "/video.mp4",
      expires_at: "2026-09-30T01:00:00Z",
      codec: "h264"
    }
    const wrapper = mount(PlaybackControls, {
      props: { ...baseProps, playbackResult }
    })

    expect(wrapper.find(".playback-codec").text()).toBe("h264")
  })
})
