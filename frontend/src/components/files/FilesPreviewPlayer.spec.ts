import { mount } from "@vue/test-utils"
import { describe, expect, it, vi } from "vitest"

import FilesPreviewPlayer from "./FilesPreviewPlayer.vue"
import type { SegmentItem } from "./types"

const segment: SegmentItem = {
  id: "segment-a",
  file: "recording-a.mp4",
  start: "08:00:00",
  end: "08:05:00",
  startDate: new Date("2026-09-30T08:00:00Z"),
  endDate: new Date("2026-09-30T08:05:00Z"),
  durationSec: 300,
  sizeFormatted: "10 MB",
  bytes: 10_485_760,
  type: "continuous",
  tier: "local",
  tierLabel: "本地",
  storageNode: "本地存储池",
  isArchived: false,
  archiveLabel: "未归档",
  spec: "H.264",
  audioSpec: "AAC",
  protected: false,
  health: "healthy",
  healthLabel: "正常",
  codec: "h264",
  container: "mp4"
}

const props = {
  activeSegment: segment,
  videoUrl: null as string | null,
  selectionToken: 1
}

describe("FilesPreviewPlayer", () => {
  it("shows the selected segment and resets placeholder playback on reselection", async () => {
    const wrapper = mount(FilesPreviewPlayer, { props })

    expect(wrapper.find(".stage-placeholder").text()).toContain("recording-a.mp4")
    expect(wrapper.find(".player-timecode-osd").text()).toContain("08:00:00 - 08:05:00")
    await wrapper.find(".transport-btn--primary").trigger("click")
    expect(wrapper.find(".transport-btn--primary").text()).toBe("暂停")
    expect(wrapper.emitted("preview-status")?.[0]).toEqual(["正在播放录像片段预览"])

    await wrapper.setProps({ selectionToken: 2 })
    expect(wrapper.find(".transport-btn--primary").text()).toBe("播放")
  })

  it("routes navigation controls and honors the auto-advance switch", async () => {
    const wrapper = mount(FilesPreviewPlayer, {
      props: { ...props, videoUrl: "/recordings/a.mp4" }
    })

    const video = wrapper.find("video.stage-video")
    expect(video.attributes("src")).toBe("/recordings/a.mp4")
    await wrapper.find('button[title="上一段"]').trigger("click")
    await wrapper.find('button[title="下一段"]').trigger("click")
    await video.trigger("ended")
    expect(wrapper.emitted("previous")).toHaveLength(1)
    expect(wrapper.emitted("next")).toHaveLength(2)

    await wrapper.find('input[type="checkbox"]').setValue(false)
    await video.trigger("ended")
    expect(wrapper.emitted("next")).toHaveLength(2)
  })

  it("plays and pauses the mounted video element", async () => {
    const wrapper = mount(FilesPreviewPlayer, {
      props: { ...props, videoUrl: "/recordings/a.mp4" }
    })
    const video = wrapper.find("video.stage-video").element as HTMLVideoElement
    const play = vi.spyOn(video, "play").mockResolvedValue(undefined)
    const pause = vi.spyOn(video, "pause").mockImplementation(() => undefined)

    await wrapper.find(".transport-btn--primary").trigger("click")
    expect(play).toHaveBeenCalledOnce()
    expect(wrapper.find(".transport-btn--primary").text()).toBe("暂停")

    Object.defineProperty(video, "paused", { configurable: true, value: false })
    await wrapper.find(".transport-btn--primary").trigger("click")
    expect(pause).toHaveBeenCalledOnce()
    expect(wrapper.find(".transport-btn--primary").text()).toBe("播放")
  })
})
