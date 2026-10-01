import { mount } from "@vue/test-utils"
import { describe, expect, it } from "vitest"
import { reactive } from "vue"

import { i18n } from "../../i18n"
import SystemTimeTab, { type TimeForm } from "./SystemTimeTab.vue"

/**
 * Build the form here and return that same instance, so assertions read the
 * object the component actually bound to (passing a replacement through
 * `overrides` would leave this helper returning the original).
 */
function mountTab(
  options: {
    servers?: string[]
    mode?: TimeForm["ntpMode"]
    props?: Record<string, unknown>
  } = {}
) {
  const timeForm = reactive<TimeForm>({
    recordingTimezone: "UTC",
    ntpMode: options.mode ?? "dhcp",
    ntpServers: options.servers ?? ["a"]
  })
  const wrapper = mount(SystemTimeTab, {
    props: {
      timeForm,
      timeSaving: false,
      ntpApplying: false,
      ntpApplyResult: null,
      hostClockHealth: null,
      cameraClockHealth: null,
      cameraClockLoading: false,
      canManage: true,
      ...options.props
    },
    global: { plugins: [i18n], stubs: { UiIcon: true } }
  })
  return { wrapper, timeForm }
}

/** The manual-server list only renders in manual NTP mode. */
function mountManual(servers: string[] = ["a", "b", "c"]) {
  return mountTab({ servers, mode: "manual" })
}

describe("SystemTimeTab", () => {
  it("renders the policy form and the clock report", () => {
    const { wrapper } = mountTab()

    expect(wrapper.find("form.system-form-card").exists()).toBe(true)
    expect(wrapper.find("input[placeholder='America/Los_Angeles']").exists()).toBe(
      true
    )
    expect(wrapper.text()).toContain("Check camera clocks")
  })

  it("binds the timezone to the form owned by the view", async () => {
    const { wrapper, timeForm } = mountTab()

    await wrapper.find("select").setValue("manual")

    expect(timeForm.ntpMode).toBe("manual")
  })

  it("shows the manual server list only in manual mode", () => {
    expect(mountManual().wrapper.find(".time-ntp-list").exists()).toBe(true)
    expect(mountTab().wrapper.find(".time-ntp-list").exists()).toBe(false)
  })

  it("appends an NTP server up to the limit of four", async () => {
    // The list helpers moved into this tab with the markup.
    const { wrapper, timeForm } = mountManual(["a"])

    const add = wrapper.find(".time-ntp-list__heading button")
    await add.trigger("click")
    expect(timeForm.ntpServers).toHaveLength(2)

    await add.trigger("click")
    await add.trigger("click")
    expect(timeForm.ntpServers).toHaveLength(4)

    // The backend rejects more than four, so the control stops adding.
    await add.trigger("click")
    expect(timeForm.ntpServers).toHaveLength(4)
  })

  it("never leaves the NTP list empty when removing", async () => {
    const { wrapper, timeForm } = mountManual(["only"])

    await wrapper.find('button[title="Remove server"]').trigger("click")

    expect(timeForm.ntpServers).toHaveLength(1)
    expect(timeForm.ntpServers[0]).toBe("")
  })

  it("reorders servers and ignores a move past either end", async () => {
    const { wrapper, timeForm } = mountManual(["a", "b", "c"])

    const ups = wrapper.findAll('button[title="Move server up"]')
    expect(ups).toHaveLength(3)
    // The first entry cannot move up, and the markup disables that control.
    expect(ups[0].attributes("disabled")).toBeDefined()

    await ups[2].trigger("click")
    expect(timeForm.ntpServers).toEqual(["a", "c", "b"])

    // Moving the first entry up is a no-op, not an error.
    await wrapper.findAll('button[title="Move server up"]')[0].trigger("click")
    expect(timeForm.ntpServers).toEqual(["a", "c", "b"])
  })

  it("emits save with and without the apply-to-cameras flag", async () => {
    const { wrapper } = mountTab()

    await wrapper.find("form").trigger("submit")
    expect(wrapper.emitted("save")![0]).toEqual([false])

    const applyAll = wrapper
      .findAll("button")
      .find((b) => b.text().includes("apply to cameras"))!
    await applyAll.trigger("click")
    expect(wrapper.emitted("save")![1]).toEqual([true])
  })

  it("emits checkClocks from the drift refresh control", async () => {
    const { wrapper } = mountTab()

    await wrapper.find(".system-page-header button").trigger("click")

    expect(wrapper.emitted("checkClocks")).toHaveLength(1)
  })

  it("disables the save controls without permission", () => {
    const { wrapper } = mountTab({ props: { canManage: false } })

    expect(
      wrapper.find("button[type='submit']").attributes("disabled")
    ).toBeDefined()
  })
})
