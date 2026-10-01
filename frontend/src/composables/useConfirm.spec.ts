import { mount } from "@vue/test-utils"
import { afterEach, describe, expect, it, vi } from "vitest"
import { defineComponent } from "vue"

import { confirmAction, useConfirmDialog } from "./useConfirm"

const Host = defineComponent({
  setup() {
    const { state, accept, dismiss } = useConfirmDialog()
    return { state, accept, dismiss }
  },
  template: `
    <div>
      <span class="open">{{ state.open ? "yes" : "no" }}</span>
      <span class="message">{{ state.message }}</span>
      <span class="danger">{{ state.danger ? "yes" : "no" }}</span>
      <button class="accept" type="button" @click="accept">accept</button>
      <button class="dismiss" type="button" @click="dismiss">dismiss</button>
    </div>
  `
})

describe("useConfirm", () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it("falls back to the browser prompt when no dialog host is mounted", async () => {
    // A component mounted in isolation has no AppShell, so the dialog does not
    // exist. Assuming consent here would turn an unanswered question into a
    // destructive action, so the native prompt is used instead.
    const stub = vi.spyOn(window, "confirm").mockReturnValue(true)

    await expect(confirmAction({ message: "Delete it?" })).resolves.toBe(true)
    expect(stub).toHaveBeenCalledWith("Delete it?")
  })

  it("propagates a declined browser prompt", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false)

    await expect(confirmAction({ message: "Delete it?" })).resolves.toBe(false)
  })

  it("opens the dialog and resolves true on accept", async () => {
    const host = mount(Host)
    expect(host.find(".open").text()).toBe("no")

    const pending = confirmAction({ message: "Delete camera?", danger: true })
    await host.vm.$nextTick()
    expect(host.find(".open").text()).toBe("yes")
    expect(host.find(".message").text()).toBe("Delete camera?")
    expect(host.find(".danger").text()).toBe("yes")

    await host.find(".accept").trigger("click")
    await expect(pending).resolves.toBe(true)
    expect(host.find(".open").text()).toBe("no")
    host.unmount()
  })

  it("resolves false on dismiss", async () => {
    const host = mount(Host)

    const pending = confirmAction({ message: "Delete camera?" })
    await host.vm.$nextTick()
    await host.find(".dismiss").trigger("click")

    await expect(pending).resolves.toBe(false)
    host.unmount()
  })

  it("resolves a superseded prompt as false rather than leaving it hanging", async () => {
    const host = mount(Host)

    const first = confirmAction({ message: "First?" })
    await host.vm.$nextTick()
    const second = confirmAction({ message: "Second?" })

    // The first caller must not proceed on an answer that was never given.
    await expect(first).resolves.toBe(false)
    expect(host.find(".message").text()).toBe("Second?")

    await host.find(".accept").trigger("click")
    await expect(second).resolves.toBe(true)
    host.unmount()
  })

  it("resolves a pending prompt when the host unmounts", async () => {
    const host = mount(Host)

    const pending = confirmAction({ message: "Still waiting?" })
    await host.vm.$nextTick()
    host.unmount()

    await expect(pending).resolves.toBe(false)
  })
})
