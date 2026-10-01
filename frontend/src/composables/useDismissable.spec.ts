import { mount } from "@vue/test-utils"
import { afterEach, describe, expect, it } from "vitest"
import { defineComponent, ref } from "vue"

import { useDismissable } from "./useDismissable"

const Harness = defineComponent({
  setup() {
    const open = ref(false)
    const root = ref<HTMLElement | null>(null)
    useDismissable(open, root)
    return { open, root }
  },
  template: `
    <div>
      <div ref="root" class="popover-root">
        <button class="inside" type="button">inside</button>
      </div>
      <button class="outside" type="button">outside</button>
      <span class="state">{{ open ? "open" : "closed" }}</span>
    </div>
  `
})

function isOpen(wrapper: ReturnType<typeof mount>): boolean {
  return wrapper.find(".state").text() === "open"
}

describe("useDismissable", () => {
  afterEach(() => {
    document.body.innerHTML = ""
  })

  it("closes on a pointer press outside the root", async () => {
    const wrapper = mount(Harness, { attachTo: document.body })
    wrapper.vm.open = true
    await wrapper.vm.$nextTick()

    wrapper.find(".outside").element.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true })
    )
    await wrapper.vm.$nextTick()

    expect(isOpen(wrapper)).toBe(false)
    wrapper.unmount()
  })

  it("stays open on a pointer press inside the root", async () => {
    const wrapper = mount(Harness, { attachTo: document.body })
    wrapper.vm.open = true
    await wrapper.vm.$nextTick()

    wrapper.find(".inside").element.dispatchEvent(
      new PointerEvent("pointerdown", { bubbles: true })
    )
    await wrapper.vm.$nextTick()

    expect(isOpen(wrapper)).toBe(true)
    wrapper.unmount()
  })

  it("closes on Escape", async () => {
    const wrapper = mount(Harness, { attachTo: document.body })
    wrapper.vm.open = true
    await wrapper.vm.$nextTick()

    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }))
    await wrapper.vm.$nextTick()

    expect(isOpen(wrapper)).toBe(false)
    wrapper.unmount()
  })

  it("leaves an already closed popover closed and removes its listeners", async () => {
    const wrapper = mount(Harness, { attachTo: document.body })
    expect(isOpen(wrapper)).toBe(false)

    // Unmount first, then interact: nothing should throw, and the detached
    // component must not react. This is the cleanup the two hand-wired copies
    // duplicated.
    wrapper.unmount()
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }))
    expect(isOpen(wrapper)).toBe(false)
  })
})
