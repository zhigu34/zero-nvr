import { mount } from "@vue/test-utils"
import { describe, expect, it } from "vitest"

import { i18n } from "../../i18n"
import CameraOnboardingConnection from "./CameraOnboardingConnection.vue"

function mountBlock(overrides: { host?: string; working?: string | null } = {}) {
  return mount(CameraOnboardingConnection, {
    props: {
      onvifHost: overrides.host ?? "",
      onvifPort: 80,
      onvifUsername: "",
      onvifPassword: "",
      working: (overrides.working ?? null) as never
    },
    global: { plugins: [i18n] }
  })
}

describe("CameraOnboardingConnection", () => {
  it("renders the host, port and username fields plus the password field", () => {
    const wrapper = mountBlock()

    const grid = wrapper.find(".form-grid")
    expect(grid.findAll("input")).toHaveLength(3)
    expect(wrapper.find("input[type='password']").exists()).toBe(true)
  })

  it("writes edits back through the models the parent owns", async () => {
    const wrapper = mountBlock()

    const host = wrapper.find("input[placeholder='192.168.1.50']")
    await host.setValue("10.0.0.9")

    expect(wrapper.emitted("update:onvifHost")).toBeTruthy()
    expect(wrapper.emitted("update:onvifHost")![0]).toEqual(["10.0.0.9"])
  })

  it("disables the probe until a host is entered", async () => {
    expect(
      mountBlock().find("button.button--primary").attributes("disabled")
    ).toBeDefined()

    const withHost = mountBlock({ host: "10.0.0.9" })
    await withHost.find("button.button--primary").trigger("click")
    expect(
      withHost.find("button.button--primary").attributes("disabled")
    ).toBeUndefined()
    expect(withHost.emitted("inspect")).toHaveLength(1)
  })

  it("disables the probe while another action runs", () => {
    const wrapper = mountBlock({ host: "10.0.0.9", working: "discover" })

    expect(
      wrapper.find("button.button--primary").attributes("disabled")
    ).toBeDefined()
  })
})
