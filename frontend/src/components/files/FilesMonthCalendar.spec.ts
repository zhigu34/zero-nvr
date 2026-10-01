import { mount } from "@vue/test-utils"
import { describe, expect, it } from "vitest"

import FilesMonthCalendar from "./FilesMonthCalendar.vue"

const baseProps = {
  selectedDate: "2026-09-15",
  todayDate: "2026-09-16",
  segmentsCount: 1,
  totalBytes: 1_048_576,
  totalDurationSec: 900,
  monthSegmentsMap: new Map([
    ["2026-09-16", { count: 2, bytes: 2_147_483_648, durationSec: 1800, cloudCount: 1 }]
  ])
}

describe("FilesMonthCalendar", () => {
  it("shows real month statistics and maps selected and timeline days", async () => {
    const wrapper = mount(FilesMonthCalendar, { props: baseProps })

    expect(wrapper.findAll(".cal-day-cell")).toHaveLength(35)
    expect(wrapper.find(".calendar-drawer-stats").text()).toContain("月度录像天数: 2 天")
    expect(wrapper.find(".calendar-drawer-stats").text()).toContain("切片总量: 2 段")
    expect(wrapper.find(".calendar-drawer-stats").text()).toContain("2.0 GB")
    expect(wrapper.find(".calendar-drawer-stats").text()).toContain("50%")
    expect(wrapper.find(".cal-day-cell--active .cal-day-count").text()).toContain("1段")
    expect(wrapper.find(".cal-day-cell--today .cal-day-count").text()).toContain("2段")

    await wrapper.findAll(".month-nav-btn")[0].trigger("click")
    await wrapper.findAll(".month-nav-btn")[1].trigger("click")
    await wrapper.find(".cal-day-cell--today").trigger("click")
    expect(wrapper.emitted("shift-month")).toEqual([[-1], [1]])
    expect(wrapper.emitted("select-date")?.[0]).toEqual(["2026-09-16"])
  })

  it("uses current-day totals before the month timeline loads", () => {
    const wrapper = mount(FilesMonthCalendar, {
      props: {
        ...baseProps,
        monthSegmentsMap: new Map(),
        segmentsCount: 3,
        totalBytes: 1_048_576
      }
    })

    const stats = wrapper.find(".calendar-drawer-stats").text()
    expect(stats).toContain("月度录像天数: 1 天")
    expect(stats).toContain("切片总量: 3 段")
    expect(stats).toContain("1.0 MB")
    expect(stats).toContain("0% (仅本地)")
  })
})
