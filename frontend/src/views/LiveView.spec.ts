import { flushPromises, mount } from "@vue/test-utils"
import { defineComponent, nextTick } from "vue"
import { describe, expect, it, vi } from "vitest"

import LiveView from "./LiveView.vue"


const cameras = Array.from({ length: 9 }, (_, index) => ({
  id: `00000000-0000-0000-0000-${String(index + 1).padStart(12, "0")}`,
  name: `Camera ${index + 1}`,
  enabled: true,
  maintenance: false,
  retired_at: null,
  location: "Office",
  storage_label: null,
  adapter_type: "manual_rtsp",
  time_sync_mode: "monitor",
  ptz_capable: false
}))

const wallMocks = vi.hoisted(() => {
  const wall = {
    setLayout: vi.fn(),
    subscribe: vi.fn(),
    close: vi.fn()
  }
  return {
    wall,
    createWall: vi.fn(() => wall)
  }
})

vi.mock("../live/previewWall", () => ({
  createLivePreviewWallClient: wallMocks.createWall
}))

vi.mock("../api/cameras", () => ({
  listCameras: vi.fn(() => Promise.resolve(cameras))
}))

vi.mock("../api/live", () => ({
  listLiveViewLayouts: vi.fn(() => Promise.resolve([
    {
      id: "10000000-0000-0000-0000-000000000001",
      name: "Nine cameras",
      is_default: true,
      layout: {
        slots: 9,
        camera_ids: cameras.map((camera) => camera.id),
        camera_panel_open: true
      },
      created_at: "2026-09-27T00:00:00Z",
      updated_at: "2026-09-27T00:00:00Z"
    }
  ])),
  createLiveViewLayout: vi.fn(),
  updateLiveViewLayout: vi.fn(),
  deleteLiveViewLayout: vi.fn()
}))

vi.mock("../stores/auth", () => ({
  useAuthStore: () => ({
    hasPermission: () => true
  })
}))

vi.mock("vue-i18n", () => ({
  useI18n: () => ({
    t: (key: string) => key
  })
}))

const LiveTileStub = defineComponent({
  name: "LiveCameraTile",
  props: [
    "camera",
    "quality",
    "focused",
    "audioEnabled",
    "allowHighQuality",
    "playbackEnabled",
    "previewWall",
    "previewSlot"
  ],
  emits: ["focus", "playbackChange"],
  template: "<button class='tile-stub' @click=\"$emit('focus', camera.id)\">{{ camera.name }}</button>"
})


describe("LiveView preview wall ownership", () => {
  it("owns one client and supplies stable slots for grid layouts", async () => {
    wallMocks.createWall.mockClear()
    wallMocks.wall.setLayout.mockClear()
    wallMocks.wall.close.mockClear()
    const wrapper = mount(LiveView, {
      global: {
        stubs: {
          LiveCameraTile: LiveTileStub,
          UiIcon: true
        }
      }
    })
    await flushPromises()
    await nextTick()

    expect(wallMocks.createWall).toHaveBeenCalledOnce()
    expect(wallMocks.wall.setLayout).toHaveBeenLastCalledWith(9)
    let tiles = wrapper.findAllComponents(LiveTileStub)
    expect(tiles).toHaveLength(9)
    expect(tiles.map((tile) => tile.props("previewSlot"))).toEqual(
      Array.from({ length: 9 }, (_, index) => index)
    )
    expect(
      tiles.every((tile) => tile.props("previewWall") === wallMocks.wall)
    ).toBe(true)

    await tiles[0].trigger("click")
    await nextTick()
    expect(wallMocks.wall.setLayout).toHaveBeenLastCalledWith(null)
    expect(
      wrapper.findComponent(LiveTileStub).props("previewWall")
    ).toBeNull()

    const backToGrid = wrapper.findAll("button").find(
      (button) => button.text().includes("live.backToGrid")
    )
    expect(backToGrid).toBeDefined()
    await backToGrid?.trigger("click")
    await nextTick()
    expect(wallMocks.wall.setLayout).toHaveBeenLastCalledWith(9)
    expect(
      wrapper.findComponent(LiveTileStub).props("previewWall")
    ).toBe(wallMocks.wall)

    const layoutButtons = wrapper.findAll(
      ".live-layout-switcher .media-button"
    )
    await layoutButtons.at(0)?.trigger("click")
    await nextTick()
    expect(wallMocks.wall.setLayout).toHaveBeenLastCalledWith(null)
    expect(
      wrapper.findComponent(LiveTileStub).props("previewWall")
    ).toBeNull()

    await layoutButtons.at(-1)?.trigger("click")
    await nextTick()
    expect(wallMocks.wall.setLayout).toHaveBeenLastCalledWith(16)

    wrapper.unmount()
    expect(wallMocks.wall.close).toHaveBeenCalledOnce()
  })
})
