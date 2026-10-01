import { mount } from "@vue/test-utils"
import { afterEach, describe, expect, it, vi } from "vitest"
import { defineComponent } from "vue"

import { useGlobalRefresh } from "./useGlobalRefresh"

const Harness = defineComponent({
  props: {
    handler: { type: Function, required: true }
  },
  setup(props) {
    useGlobalRefresh(props.handler as () => void)
    return () => null
  }
})

function dispatchRefresh(): void {
  window.dispatchEvent(new CustomEvent("zero-nvr:refresh"))
}

describe("useGlobalRefresh", () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it("invokes the handler when the refresh signal is dispatched", () => {
    const handler = vi.fn()
    mount(Harness, { props: { handler } })

    dispatchRefresh()

    expect(handler).toHaveBeenCalledTimes(1)
  })

  it("does not invoke the handler before mount", () => {
    const handler = vi.fn()
    dispatchRefresh()
    mount(Harness, { props: { handler } })

    expect(handler).not.toHaveBeenCalled()
  })

  it("stops listening after unmount", () => {
    // The hand-wired copies are what this replaces; a missing removeEventListener
    // kept the handler alive against a destroyed component.
    const handler = vi.fn()
    const wrapper = mount(Harness, { props: { handler } })

    dispatchRefresh()
    expect(handler).toHaveBeenCalledTimes(1)

    wrapper.unmount()
    dispatchRefresh()
    expect(handler).toHaveBeenCalledTimes(1)
  })

  it("tolerates an async handler", async () => {
    const handler = vi.fn().mockResolvedValue(undefined)
    mount(Harness, { props: { handler } })

    dispatchRefresh()
    await Promise.resolve()

    expect(handler).toHaveBeenCalledTimes(1)
  })
})
