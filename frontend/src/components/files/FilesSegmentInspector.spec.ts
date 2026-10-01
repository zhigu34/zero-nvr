import { mount } from "@vue/test-utils"
import { describe, expect, it } from "vitest"

import FilesSegmentInspector from "./FilesSegmentInspector.vue"
import type { SegmentItem } from "./types"

const segment: SegmentItem = {
  id: "segment-a",
  file: "rec_2026-09-30_080000_300s.mp4",
  start: "08:00:00",
  end: "08:05:00",
  startDate: new Date("2026-09-30T08:00:00Z"),
  endDate: new Date("2026-09-30T08:05:00Z"),
  durationSec: 300,
  sizeFormatted: "10 MB",
  bytes: 10_485_760,
  type: "continuous",
  tier: "remote",
  tierLabel: "远端",
  storageNode: "远端归档池",
  isArchived: true,
  archiveLabel: "已归档至远端",
  spec: "H.264 1080p",
  audioSpec: "AAC",
  protected: true,
  protectionId: "protection-a",
  health: "healthy",
  healthLabel: "正常",
  codec: "h264",
  container: "mp4"
}

const props = {
  activeSegment: segment,
  activeSegmentIndex: 1,
  segmentsCount: 3,
  formatDuration: () => "5分钟"
}

describe("FilesSegmentInspector", () => {
  it("shows the selected segment's metadata and position", () => {
    const wrapper = mount(FilesSegmentInspector, { props })

    expect(wrapper.find(".inspector-filename").text()).toBe(segment.file)
    expect(wrapper.text()).toContain("片段 2 / 3")
    expect(wrapper.text()).toContain("5分钟")
    expect(wrapper.text()).toContain("远端归档池")
    expect(wrapper.text()).toContain("已加锁保护")
  })

  it("forwards single-segment actions without performing them locally", async () => {
    const wrapper = mount(FilesSegmentInspector, { props })

    await wrapper.find(".action-btn--primary").trigger("click")
    await wrapper.findAll(".action-btn")[1].trigger("click")
    await wrapper.findAll(".action-btn")[2].trigger("click")
    await wrapper.findAll(".action-btn")[3].trigger("click")
    await wrapper.find(".action-btn--danger").trigger("click")

    expect(wrapper.emitted("jump")?.[0]).toEqual([segment])
    expect(wrapper.emitted("download")?.[0]).toEqual([segment])
    expect(wrapper.emitted("toggle-lock")?.[0]).toEqual([segment])
    expect(wrapper.emitted("archive")?.[0]).toEqual([segment])
    expect(wrapper.emitted("clear")?.[0]).toEqual([])
  })

  it("shows the original empty prompt when no segment is selected", () => {
    const wrapper = mount(FilesSegmentInspector, {
      props: { ...props, activeSegment: null }
    })

    expect(wrapper.find(".inspector-card--empty").text()).toContain("未选定切片")
    expect(wrapper.find(".metadata-rows").exists()).toBe(false)
    expect(wrapper.findAll(".action-btn")).toHaveLength(0)
  })
})
