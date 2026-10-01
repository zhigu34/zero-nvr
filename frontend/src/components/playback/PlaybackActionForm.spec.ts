import { mount } from "@vue/test-utils"
import { describe, expect, it, vi } from "vitest"

import PlaybackActionForm from "./PlaybackActionForm.vue"

vi.mock("vue-i18n", () => ({
  useI18n: () => ({ t: (key: string) => key })
}))

const baseProps = {
  mode: "protect" as const,
  editingProtectionId: null,
  saving: false,
  actionStart: "2026-09-28T08:00:00",
  actionEnd: "2026-09-28T08:01:00",
  protectionReason: "Incident",
  protectionExpiresAt: "",
  exportCodecMode: "auto" as const,
  exportGapPolicy: "skip" as const
}

describe("PlaybackActionForm", () => {
  it("updates protection fields and emits save or cancel", async () => {
    const wrapper = mount(PlaybackActionForm, { props: baseProps })

    await wrapper.find('input[maxlength="1024"]').setValue("Updated incident")
    await wrapper.find('input[step="60"]').setValue("2026-09-29T08:00")
    await wrapper.find("form").trigger("submit")
    await wrapper.find('button[type="button"]').trigger("click")

    expect(wrapper.emitted("update:protectionReason")?.[0]).toEqual(["Updated incident"])
    expect(wrapper.emitted("update:protectionExpiresAt")?.[0]).toEqual(["2026-09-29T08:00"])
    expect(wrapper.emitted("save-protection")).toHaveLength(1)
    expect(wrapper.emitted("close")).toHaveLength(1)
  })

  it("updates export options and disables the submit button while saving", async () => {
    const wrapper = mount(PlaybackActionForm, {
      props: { ...baseProps, mode: "export", saving: true }
    })

    await wrapper.findAll("select")[0].setValue("h264")
    await wrapper.findAll("select")[1].setValue("fail")
    expect(wrapper.find('button[type="submit"]').attributes("disabled"))
      .toBeDefined()
    await wrapper.find("form").trigger("submit")

    expect(wrapper.emitted("update:exportCodecMode")?.[0]).toEqual(["h264"])
    expect(wrapper.emitted("update:exportGapPolicy")?.[0]).toEqual(["fail"])
    expect(wrapper.emitted("save-export")).toHaveLength(1)
  })
})
