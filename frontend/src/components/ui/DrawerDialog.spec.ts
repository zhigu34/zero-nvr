import { mount } from "@vue/test-utils"
import { afterEach, describe, expect, it } from "vitest"
import { defineComponent, nextTick, ref } from "vue"

import DrawerDialog from "./DrawerDialog.vue"

const Harness = defineComponent({
  components: { DrawerDialog },
  setup() {
    const open = ref(true)
    const dismissals = ref(0)
    return { open, dismissals }
  },
  template: `
    <DrawerDialog
      :open="open"
      backdrop-class="unifi-drawer-backdrop"
      @dismiss="dismissals += 1; open = false"
    >
      <aside class="unifi-drawer"><strong>Panel</strong></aside>
    </DrawerDialog>
  `
})

function pressEscape(): void {
  window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }))
}

describe("DrawerDialog", () => {
  afterEach(() => {
    document.body.innerHTML = ""
  })

  it("renders the backdrop class on the root and slots the panel", () => {
    const wrapper = mount(Harness)

    expect(wrapper.find(".unifi-drawer-backdrop").exists()).toBe(true)
    // The panel stays the caller's element so its scoped rules keep applying.
    const panel = wrapper.find("aside.unifi-drawer")
    expect(panel.exists()).toBe(true)
    expect(panel.text()).toContain("Panel")
    wrapper.unmount()
  })

  it("emits dismiss on a backdrop click, not on a click inside the panel", async () => {
    const wrapper = mount(Harness, { attachTo: document.body })

    await wrapper.find(".unifi-drawer").trigger("click")
    expect(wrapper.vm.dismissals).toBe(0)

    await wrapper.find(".unifi-drawer-backdrop").trigger("click")
    expect(wrapper.vm.dismissals).toBe(1)
    wrapper.unmount()
  })

  it("emits dismiss on Escape", async () => {
    const wrapper = mount(Harness, { attachTo: document.body })

    pressEscape()
    await nextTick()

    expect(wrapper.vm.dismissals).toBe(1)
    wrapper.unmount()
  })

  it("stops listening for Escape once closed", async () => {
    // A closed drawer must not swallow Escape from whatever the operator is
    // actually looking at.
    const wrapper = mount(Harness, { attachTo: document.body })
    wrapper.vm.open = false
    await nextTick()

    pressEscape()
    await nextTick()

    expect(wrapper.vm.dismissals).toBe(0)
    wrapper.unmount()
  })

  it("stops listening after unmount", async () => {
    const wrapper = mount(Harness, { attachTo: document.body })
    wrapper.unmount()

    pressEscape()
    await nextTick()

    expect(wrapper.vm.dismissals).toBe(0)
  })

  it("can opt out of backdrop and Escape dismissal", async () => {
    const Strict = defineComponent({
      components: { DrawerDialog },
      setup() {
        const dismissals = ref(0)
        return { dismissals }
      },
      template: `
        <DrawerDialog
          :open="true"
          backdrop-class="unifi-drawer-backdrop"
          :close-on-backdrop="false"
          :close-on-escape="false"
          @dismiss="dismissals += 1"
        >
          <aside class="unifi-drawer">Panel</aside>
        </DrawerDialog>
      `
    })
    const wrapper = mount(Strict, { attachTo: document.body })

    await wrapper.find(".unifi-drawer-backdrop").trigger("click")
    pressEscape()
    await nextTick()

    expect(wrapper.vm.dismissals).toBe(0)
    wrapper.unmount()
  })
})
