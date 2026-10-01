import { mount } from "@vue/test-utils"
import { describe, expect, it } from "vitest"

import { type OnvifInspection } from "../../api/cameras"
import { i18n } from "../../i18n"
import CameraOnboardingInspection from "./CameraOnboardingInspection.vue"

function inspection(overrides: Record<string, unknown> = {}): OnvifInspection {
  return {
    device: {
      manufacturer: "Acme",
      model: "Cam 4K",
      serial_number: "SN-1"
    },
    identity: { state: "new_device" },
    profiles: [
      {
        token: "main",
        name: "Main",
        codec: "H265",
        width: 3840,
        height: 2160,
        fps: 25,
        stream_uri_available: true
      },
      {
        token: "sub",
        name: "Sub",
        codec: "H264",
        stream_uri_available: false
      }
    ],
    ...overrides
  } as unknown as OnvifInspection
}

function mountBlock(
  overrides: {
    inspection?: OnvifInspection | null
    selectedProfiles?: string[]
    confirmExistingIdentity?: boolean
  } = {}
) {
  return mount(CameraOnboardingInspection, {
    props: {
      inspection:
        overrides.inspection === undefined ? inspection() : overrides.inspection,
      selectedProfiles: overrides.selectedProfiles ?? [],
      confirmExistingIdentity: overrides.confirmExistingIdentity ?? false
    },
    global: { plugins: [i18n] }
  })
}

describe("CameraOnboardingInspection", () => {
  it("shows the device summary once inspected", () => {
    const wrapper = mountBlock()

    expect(wrapper.find(".device-summary").text()).toContain("Acme")
    expect(wrapper.find(".device-summary").text()).toContain("SN-1")
  })

  it("shows the not-yet-inspected hint when there is nothing to show", () => {
    const wrapper = mountBlock({ inspection: null })

    expect(wrapper.find(".inspection-card").exists()).toBe(false)
    expect(wrapper.find(".step-empty").exists()).toBe(true)
  })

  it("lists profiles and renders each summary", () => {
    const wrapper = mountBlock()

    const options = wrapper.findAll(".profile-option")
    expect(options).toHaveLength(2)
    // codec · resolution · fps
    expect(options[0].text()).toContain("H265")
    expect(options[0].text()).toContain("3840×2160")
    expect(options[0].text()).toContain("25 fps")
    // A profile with no resolution falls back to the shared label, not "null".
    expect(options[1].text()).not.toContain("null")
  })

  it("disables a profile whose stream URI is unavailable", () => {
    const wrapper = mountBlock()

    const boxes = wrapper.findAll(".profile-option input")
    expect(boxes[0].attributes("disabled")).toBeUndefined()
    expect(boxes[1].attributes("disabled")).toBeDefined()
    expect(wrapper.findAll(".profile-option")[1].classes()).toContain(
      "profile-option--disabled"
    )
  })

  it("emits the selected profile tokens", async () => {
    const wrapper = mountBlock()

    await wrapper.findAll(".profile-option input")[0].setValue(true)

    expect(wrapper.emitted("update:selectedProfiles")).toBeTruthy()
  })

  it("offers the identity confirmation only for a probable match", async () => {
    const probable = mountBlock({
      inspection: inspection({
        identity: { state: "probable_match_requires_confirmation" }
      })
    })
    const checkbox = probable.find("input[type='checkbox']")
    expect(checkbox.exists()).toBe(true)

    await checkbox.setValue(true)
    expect(probable.emitted("update:confirmExistingIdentity")).toBeTruthy()

    // A brand-new device needs no confirmation at all.
    expect(
      mountBlock().find(".notice input[type='checkbox']").exists()
    ).toBe(false)
  })

  it("reports an identity conflict distinctly", () => {
    const conflict = mountBlock({
      inspection: inspection({ identity: { state: "identity_conflict" } })
    })

    expect(conflict.find(".notice--error").exists()).toBe(true)
  })
})
