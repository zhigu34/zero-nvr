import { mount } from "@vue/test-utils"
import { afterEach, describe, expect, it, vi } from "vitest"
import { defineComponent, ref } from "vue"

import { useFullscreen } from "./useFullscreen"

const exitFullscreen = vi.fn().mockResolvedValue(undefined)

function setFullscreenElement(element: Element | null): void {
  Object.defineProperty(document, "fullscreenElement", {
    configurable: true,
    get: () => element
  })
}

interface HarnessOptions {
  perTile?: boolean
}

function makeHarness({ perTile = false }: HarnessOptions = {}) {
  return defineComponent({
    setup() {
      const element = ref<HTMLElement | null>(null)
      const active = ref(false)
      const controls = useFullscreen(
        element,
        active,
        perTile
          ? { isActive: (target) => document.fullscreenElement === target }
          : {}
      )
      return { element, active, controls }
    },
    template: `
      <div>
        <div ref="element" class="target"></div>
        <span class="state">{{ active ? "active" : "inactive" }}</span>
      </div>
    `
  })
}

describe("useFullscreen", () => {
  afterEach(() => {
    setFullscreenElement(null)
    exitFullscreen.mockClear()
    vi.restoreAllMocks()
  })

  it("requests fullscreen on the tracked element", async () => {
    const requestFullscreen = vi.fn().mockResolvedValue(undefined)
    const wrapper = mount(makeHarness())
    const target = wrapper.find(".target").element as HTMLElement
    target.requestFullscreen = requestFullscreen

    await wrapper.vm.controls.enter()

    expect(requestFullscreen).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it("toggles by exiting when something is already fullscreen", async () => {
    const wrapper = mount(makeHarness())
    setFullscreenElement(wrapper.find(".target").element)
    document.exitFullscreen = exitFullscreen

    await wrapper.vm.controls.toggle()

    expect(exitFullscreen).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it("marks active for any fullscreen element by default", async () => {
    const wrapper = mount(makeHarness())
    // A different element going fullscreen still counts.
    setFullscreenElement(document.createElement("section"))

    wrapper.vm.controls.sync()
    await wrapper.vm.$nextTick()

    expect(wrapper.find(".state").text()).toBe("active")
    wrapper.unmount()
  })

  it("marks active only for its own element in per-tile mode", async () => {
    // A camera tile must not report itself fullscreen when another tile is.
    const wrapper = mount(makeHarness({ perTile: true }))
    setFullscreenElement(document.createElement("section"))

    wrapper.vm.controls.sync()
    await wrapper.vm.$nextTick()
    expect(wrapper.find(".state").text()).toBe("inactive")

    setFullscreenElement(wrapper.find(".target").element)
    wrapper.vm.controls.sync()
    await wrapper.vm.$nextTick()
    expect(wrapper.find(".state").text()).toBe("active")
    wrapper.unmount()
  })

  it("stops tracking after unmount", async () => {
    const wrapper = mount(makeHarness())
    wrapper.unmount()

    setFullscreenElement(document.createElement("section"))
    document.dispatchEvent(new Event("fullscreenchange"))

    // No throw and no state write: the listener was removed on teardown.
    expect(wrapper.vm.active).toBe(false)
  })
})
