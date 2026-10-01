import { mount } from "@vue/test-utils"
import { describe, expect, it } from "vitest"

import type { SegmentItem } from "./types"
import FilesSegmentTable from "./FilesSegmentTable.vue"

const segment = {
  id: "segment-a",
  file: "recording-a.mp4",
  start: "08:00:00",
  end: "08:05:00",
  durationSec: 300,
  sizeFormatted: "10 MB",
  spec: "H.264",
  tier: "local",
  tierLabel: "本地",
  protected: false,
  health: "healthy"
} as SegmentItem

const baseProps = {
  filteredCount: 1,
  pagedSegments: [segment],
  selectedSegmentId: "segment-a",
  loading: false,
  selectedDate: "2026-09-30",
  currentPage: 1,
  totalPages: 2,
  pageStartIndex: 1,
  pageEndIndex: 1,
  formatDuration: () => "5分钟"
}

describe("FilesSegmentTable", () => {
  it("forwards row actions and pagination without selecting on an action click", async () => {
    const wrapper = mount(FilesSegmentTable, { props: baseProps })
    const row = wrapper.find(".files-table tbody tr")
    expect(row.classes()).toContain("tr--active")
    expect(row.text()).toContain("5分钟")

    await row.trigger("click")
    await row.trigger("dblclick")
    expect(wrapper.emitted("select")?.[0]).toEqual([segment])
    expect(wrapper.emitted("jump")?.[0]).toEqual([segment])

    await wrapper.find('button[title="下载 Raw MP4"]').trigger("click")
    await wrapper.find('button[title="加锁保护"]').trigger("click")
    expect(wrapper.emitted("download")?.[0]).toEqual([segment])
    expect(wrapper.emitted("toggle-lock")?.[0]).toEqual([segment])
    expect(wrapper.emitted("select")).toHaveLength(1)

    await wrapper.findAll(".page-nav-btn")[1].trigger("click")
    expect(wrapper.emitted("update:currentPage")?.[0]).toEqual([2])
  })

  it("shows the empty state only after loading finishes", async () => {
    const emptyProps = { ...baseProps, filteredCount: 0, pagedSegments: [] }
    const wrapper = mount(FilesSegmentTable, { props: emptyProps })
    expect(wrapper.find(".files-table").exists()).toBe(false)
    expect(wrapper.find(".empty-state").text()).toContain("2026-09-30")

    await wrapper.setProps({ loading: true })
    expect(wrapper.find(".empty-state").exists()).toBe(false)
  })
})
