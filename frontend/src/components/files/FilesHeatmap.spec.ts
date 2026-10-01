import { mount } from "@vue/test-utils"
import { describe, expect, it } from "vitest"

import FilesHeatmap from "./FilesHeatmap.vue"
import type { SegmentItem } from "./types"

const first: SegmentItem = {
  id: "segment-a",
  file: "first.mp4",
  start: "08:00:00",
  end: "08:05:00",
  startDate: new Date(2026, 8, 30, 8, 0),
  endDate: new Date(2026, 8, 30, 8, 5),
  durationSec: 300,
  sizeFormatted: "1 MB",
  bytes: 1_048_576,
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

const second: SegmentItem = {
  ...first,
  id: "segment-b",
  file: "second.mp4",
  start: "08:05:00",
  end: "08:10:00",
  startDate: new Date(2026, 8, 30, 8, 5),
  endDate: new Date(2026, 8, 30, 8, 10),
  protected: true
}

describe("FilesHeatmap", () => {
  it("renders 288 five-minute cells with the original coverage and protection levels", () => {
    const wrapper = mount(FilesHeatmap, {
      props: {
        selectedDate: "2026-09-30",
        segments: [first, second],
        totalDurationFormatted: "10分钟",
        activeHeatBinIndex: 97
      }
    })

    const cells = wrapper.findAll(".heat-cell")
    expect(cells).toHaveLength(288)
    expect(cells[96].classes()).toContain("recorded")
    expect(cells[96].attributes("title")).toContain("1.0 MB")
    expect(cells[97].classes()).toContain("cloud")
    expect(cells[97].classes()).toContain("active")
    expect(wrapper.find(".heat-summary-tag").text()).toContain("2 段 · 10分钟")
  })

  it("emits the clicked time cell and index for parent selection", async () => {
    const wrapper = mount(FilesHeatmap, {
      props: {
        selectedDate: "2026-09-30",
        segments: [first],
        totalDurationFormatted: "5分钟",
        activeHeatBinIndex: null
      }
    })

    await wrapper.findAll(".heat-cell")[96].trigger("click")
    expect(wrapper.emitted("select-cell")?.[0]).toEqual([
      { hour: 8, minuteSlot: 0, timeLabel: "08:00", level: 1, count: 1, bytes: 1_048_576 },
      96
    ])
  })
})
