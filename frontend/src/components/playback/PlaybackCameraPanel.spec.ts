import { mount } from "@vue/test-utils"
import { describe, expect, it, vi } from "vitest"

import type { CameraSummary } from "../../api/cameras"
import PlaybackCameraPanel from "./PlaybackCameraPanel.vue"

vi.mock("vue-i18n", () => ({
  useI18n: () => ({ t: (key: string) => key })
}))

const cameras = [
  {
    id: "camera-a",
    name: "Lobby",
    location: "East wing",
    adapter_type: "onvif",
    enabled: true
  },
  {
    id: "camera-b",
    name: "Garage",
    location: "West wing",
    adapter_type: "manual_rtsp",
    enabled: false
  }
] as CameraSummary[]

describe("PlaybackCameraPanel", () => {
  it("filters cameras and sends actions to the playback view", async () => {
    const wrapper = mount(PlaybackCameraPanel, {
      props: {
        open: true,
        cameras,
        loading: false,
        activeCameraId: "camera-a",
        syncedCameraIds: []
      }
    })

    await wrapper.find('input[type="search"]').setValue("west")
    expect(wrapper.text()).toContain("Garage")
    expect(wrapper.text()).not.toContain("Lobby")

    await wrapper.find(".playback-camera-select-row__primary").trigger("click")
    await wrapper.find(".playback-sync-toggle").trigger("click")
    await wrapper.find(".live-camera-panel__header button").trigger("click")

    expect(wrapper.emitted("select")?.[0]).toEqual(["camera-b"])
    expect(wrapper.emitted("toggle-sync")?.[0]).toEqual(["camera-b"])
    expect(wrapper.emitted("refresh")).toHaveLength(1)
  })

  it("keeps the primary camera out of sync toggle actions", () => {
    const wrapper = mount(PlaybackCameraPanel, {
      props: {
        open: true,
        cameras,
        loading: false,
        activeCameraId: "camera-a",
        syncedCameraIds: []
      }
    })

    const toggles = wrapper.findAll(".playback-sync-toggle")
    expect(toggles[0].attributes("disabled")).toBeDefined()
    expect(toggles[1].attributes("disabled")).toBeUndefined()
  })
})
