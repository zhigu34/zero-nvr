import { mount } from "@vue/test-utils"
import { describe, expect, it } from "vitest"
import { reactive } from "vue"

import { type CameraProbeResult } from "../../api/cameras"
import { i18n } from "../../i18n"
import CameraOnboardingManualFlow from "./CameraOnboardingManualFlow.vue"

interface Model {
  manualName: string
  manualLocation: string
  manualStorageLabel: string
  primaryName: string
  primaryUrl: string
  secondaryEnabled: boolean
  secondaryName: string
  secondaryUrl: string
}

function mountFlow(
  overrides: {
    probe?: CameraProbeResult | null
    working?: string | null
    canCreate?: boolean
    model?: Partial<Model>
  } = {}
) {
  const model = reactive<Model>({
    manualName: "",
    manualLocation: "",
    manualStorageLabel: "",
    primaryName: "Main stream",
    primaryUrl: "",
    secondaryEnabled: false,
    secondaryName: "Sub stream",
    secondaryUrl: "",
    ...overrides.model
  })
  const wrapper = mount(CameraOnboardingManualFlow, {
    props: {
      manualName: model.manualName,
      manualLocation: model.manualLocation,
      manualStorageLabel: model.manualStorageLabel,
      primaryName: model.primaryName,
      primaryUrl: model.primaryUrl,
      secondaryEnabled: model.secondaryEnabled,
      secondaryName: model.secondaryName,
      secondaryUrl: model.secondaryUrl,
      manualProbe: overrides.probe ?? null,
      working: (overrides.working ?? null) as never,
      canCreateManual: overrides.canCreate ?? true,
      // Keep the reactive object in play so `update:*` handlers write back.
      "onUpdate:manualName": (v: string) => (model.manualName = v),
      "onUpdate:manualLocation": (v: string) => (model.manualLocation = v),
      "onUpdate:manualStorageLabel": (v: string) =>
        (model.manualStorageLabel = v),
      "onUpdate:primaryName": (v: string) => (model.primaryName = v),
      "onUpdate:primaryUrl": (v: string) => (model.primaryUrl = v),
      "onUpdate:secondaryEnabled": (v: boolean) =>
        (model.secondaryEnabled = v),
      "onUpdate:secondaryName": (v: string) => (model.secondaryName = v),
      "onUpdate:secondaryUrl": (v: string) => (model.secondaryUrl = v)
    },
    global: { plugins: [i18n] }
  })
  return { wrapper, model }
}

const PROBE = {
  streams: [{ name: "Main", url: "rtsp://cam/main", codec: "H.265" }]
} as unknown as CameraProbeResult

describe("CameraOnboardingManualFlow", () => {
  it("renders the describe and streams steps", () => {
    const { wrapper } = mountFlow()

    // describe, streams and the probe/actions step
    expect(wrapper.findAll(".onboarding-step")).toHaveLength(3)
    expect(wrapper.find("input[required]").exists()).toBe(true)
  })

  it("writes edits back through the models the parent owns", async () => {
    const { wrapper, model } = mountFlow()

    await wrapper.find("input[placeholder='Garage']").setValue("Driveway")

    expect(model.manualName).toBe("Driveway")
  })

  it("emits test and create from the action buttons", async () => {
    // The test control stays disabled until the camera has a name and a URL.
    const { wrapper } = mountFlow({
      model: { manualName: "Driveway", primaryUrl: "rtsp://cam/main" }
    })

    const buttons = wrapper.findAll("button")
    const test = buttons.find((b) => /test/i.test(b.text()))!
    const create = buttons.find((b) => /create/i.test(b.text()))!

    await test.trigger("click")
    await create.trigger("click")

    expect(wrapper.emitted("test")).toHaveLength(1)
    expect(wrapper.emitted("create")).toHaveLength(1)
  })

  it("keeps the test control disabled until a name and URL are present", () => {
    const { wrapper } = mountFlow({ model: { primaryUrl: "rtsp://cam/main" } })

    const test = wrapper
      .findAll("button")
      .find((b) => /test/i.test(b.text()))!
    expect(test.attributes("disabled")).toBeDefined()
  })

  it("blocks creation when the parent says so", () => {
    const { wrapper } = mountFlow({ canCreate: false })

    const create = wrapper
      .findAll("button")
      .find((b) => /create/i.test(b.text()))!
    expect(create.attributes("disabled")).toBeDefined()
  })

  it("shows the probe result only once a probe exists", () => {
    expect(mountFlow().wrapper.find(".probe-results").exists()).toBe(false)
    expect(
      mountFlow({ probe: PROBE }).wrapper.find(".probe-results").exists()
    ).toBe(true)
  })
})
