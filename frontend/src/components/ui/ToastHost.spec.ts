import { mount } from "@vue/test-utils"
import { afterEach, describe, expect, it, vi } from "vitest"
import { defineComponent, nextTick } from "vue"

import { dismissToast, showToast } from "../../composables/useToast"
import ToastHost from "./ToastHost.vue"

const Consumer = defineComponent({
  components: { ToastHost },
  props: { surfaceClass: { type: String, required: true } },
  template: `
    <div>
      <ToastHost :surface-class="surfaceClass" />
      <button type="button" @click="raise">raise</button>
    </div>
  `,
  methods: {
    raise() {
      showToast("Saved")
    }
  }
})

describe("ToastHost", () => {
  afterEach(() => {
    dismissToast()
    vi.useRealTimers()
  })

  it("renders nothing until a message is raised", () => {
    const wrapper = mount(Consumer, { props: { surfaceClass: "toast-popup" } })

    expect(wrapper.find(".toast-popup").exists()).toBe(false)
    wrapper.unmount()
  })

  it("renders the surface class and the message", async () => {
    const wrapper = mount(Consumer, { props: { surfaceClass: "toast-popup" } })

    await wrapper.find("button").trigger("click")
    await nextTick()

    const host = wrapper.find(".toast-popup")
    expect(host.exists()).toBe(true)
    expect(host.text()).toBe("Saved")
    wrapper.unmount()
  })

  it("keeps caller-supplied children in the caller's scope", async () => {
    // FilesView renders its accent dot here on purpose: a nested element needs
    // to belong to the view for the view's scoped rule to style it.
    const WithChildren = defineComponent({
      components: { ToastHost },
      template: `
        <ToastHost surface-class="toast-notification">
          <span class="toast-dot" />
          <span class="message">Custom</span>
        </ToastHost>
      `
    })
    showToast("ignored-by-slot")
    const wrapper = mount(WithChildren)
    await nextTick()

    expect(wrapper.find(".toast-dot").exists()).toBe(true)
    expect(wrapper.find(".message").text()).toBe("Custom")
    wrapper.unmount()
  })

  it("hides again after the dwell time", async () => {
    vi.useFakeTimers()
    const wrapper = mount(Consumer, { props: { surfaceClass: "toast-banner" } })

    showToast("Gone soon", 500)
    await nextTick()
    expect(wrapper.find(".toast-banner").exists()).toBe(true)

    vi.advanceTimersByTime(500)
    await nextTick()
    expect(wrapper.find(".toast-banner").exists()).toBe(false)
    wrapper.unmount()
  })
})
