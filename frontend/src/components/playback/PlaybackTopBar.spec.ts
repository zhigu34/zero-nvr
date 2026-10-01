import { mount } from "@vue/test-utils"
import { describe, expect, it, vi } from "vitest"

import type { CameraSummary } from "../../api/cameras"
import PlaybackTopBar from "./PlaybackTopBar.vue"

vi.mock("vue-i18n", () => ({
  useI18n: () => ({ t: (key: string) => key })
}))

const cameras = [
  { id: "camera-a", name: "Lobby", enabled: true, adapter_type: "onvif" },
  { id: "camera-b", name: "Garage", enabled: false, adapter_type: "manual_rtsp" }
] as CameraSummary[]

const baseProps = {
  cameras,
  activeCameraId: "camera-a",
  activeCameraName: "Lobby",
  cameraPanelOpen: false,
  selectedDate: "2026-09-28",
  isToday: false,
  syncMode: "tolerant" as const,
  zoomHours: 6 as const,
  zoomOptions: [1, 6, 24] as (1 | 6 | 24)[],
  fullscreen: false
}

describe("PlaybackTopBar", () => {
  it("selects a camera and emits date navigation actions", async () => {
    const wrapper = mount(PlaybackTopBar, { props: baseProps })

    await wrapper.find('.topbar-pill-btn:not(.date-pill-btn)').trigger("click")
    await wrapper.findAll(".popover-cam-item")[1].trigger("click")
    expect(wrapper.emitted("select-camera")?.[0]).toEqual(["camera-b"])
    expect(wrapper.find(".camera-dropdown-popover").exists()).toBe(false)

    await wrapper.findAll(".date-nav-btn")[0].trigger("click")
    expect(wrapper.emitted("shift-day")?.[0]).toEqual([-1])

    await wrapper.find(".date-pill-btn").trigger("click")
    await wrapper.find('input[type="date"]').setValue("2026-09-29")
    expect(wrapper.emitted("update:selectedDate")?.[0]).toEqual(["2026-09-29"])
    expect(wrapper.emitted("date-change")).toHaveLength(1)

    await wrapper.find(".date-pill-btn").trigger("click")
    await wrapper.findAll(".quick-date-btn")[0].trigger("click")
    expect(wrapper.emitted("select-today")).toHaveLength(1)
  })

  it("routes sync, zoom and fullscreen controls", async () => {
    const wrapper = mount(PlaybackTopBar, { props: baseProps })

    await wrapper.findAll(".topbar-icon-btn")[0].trigger("click")
    await wrapper.findAll(".sync-btn")[1].trigger("click")
    await wrapper.findAll(".zoom-btn")[2].trigger("click")
    await wrapper.findAll(".topbar-icon-btn")[1].trigger("click")

    expect(wrapper.emitted("update:cameraPanelOpen")?.[0]).toEqual([true])
    expect(wrapper.emitted("set-sync-mode")?.[0]).toEqual(["strict"])
    expect(wrapper.emitted("set-zoom")?.[0]).toEqual([24])
    expect(wrapper.emitted("toggle-fullscreen")).toHaveLength(1)
  })
})
