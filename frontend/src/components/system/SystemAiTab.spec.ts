import { mount } from "@vue/test-utils"
import { describe, expect, it } from "vitest"
import { reactive } from "vue"

import { type CameraSummary } from "../../api/cameras"
import { type FrigateCameraMapping } from "../../api/system"
import { i18n } from "../../i18n"
import SystemAiTab, { type FrigateForm } from "./SystemAiTab.vue"

const CAMERAS = [
  { id: "cam-1", name: "Front Door" },
  { id: "cam-2", name: "Driveway" }
] as CameraSummary[]

function mountTab(overrides: Record<string, unknown> = {}) {
  const frigateForm = reactive<FrigateForm>({
    enabled: true,
    mode: "external",
    baseUrl: "http://frigate:5000",
    mqttEnabled: false,
    mqttHost: "",
    mqttPort: 1883,
    mqttTopicPrefix: "frigate",
    mqttTls: false,
    bearerToken: "",
    httpUsername: "",
    httpPassword: "",
    mqttUsername: "",
    mqttPassword: ""
  })
  const frigateMappings = reactive<FrigateCameraMapping[]>([])
  const wrapper = mount(SystemAiTab, {
    props: {
      frigateForm,
      frigateConfigured: true,
      frigateVersion: "0.14.1",
      frigateMappings,
      frigateSaving: false,
      frigateTesting: false,
      cameras: CAMERAS,
      ...overrides
    },
    global: { plugins: [i18n], stubs: { UiIcon: true } }
  })
  return { wrapper, frigateForm, frigateMappings }
}

describe("SystemAiTab", () => {
  it("renders the connection form", () => {
    const { wrapper } = mountTab()

    expect(wrapper.find("form.system-form-card").exists()).toBe(true)
    expect(wrapper.findAll("input").length).toBeGreaterThan(0)
  })

  it("binds the base URL to the form owned by the view", async () => {
    const { wrapper, frigateForm } = mountTab()

    // The input carries no `type` attribute, so it is located by its seeded
    // value rather than by a type selector.
    const baseUrl = wrapper
      .findAll("input")
      .find((input) => input.element.value === "http://frigate:5000")
    expect(baseUrl).toBeDefined()

    await baseUrl!.setValue("http://frigate.local:5000")

    expect(frigateForm.baseUrl).toBe("http://frigate.local:5000")
  })

  it("emits save on submit", async () => {
    const { wrapper } = mountTab()

    await wrapper.find("form.system-form-card").trigger("submit")

    expect(wrapper.emitted("save")).toHaveLength(1)
  })

  it("appends a mapping seeded from the first camera", async () => {
    // The mapping helpers moved into this tab, so this is where they are now
    // exercised; the array itself still belongs to the view.
    const { wrapper, frigateMappings } = mountTab()

    await wrapper.find("button.button--compact").trigger("click")

    expect(frigateMappings).toHaveLength(1)
    expect(frigateMappings[0]).toEqual({
      frigate_camera: "",
      camera_id: "cam-1"
    })
  })

  it("removes the mapping at the clicked index", async () => {
    const { wrapper, frigateMappings } = mountTab()
    frigateMappings.push(
      { frigate_camera: "a", camera_id: "cam-1" },
      { frigate_camera: "b", camera_id: "cam-2" }
    )
    await wrapper.vm.$nextTick()

    await wrapper.findAll("button.icon-button--danger")[0].trigger("click")

    expect(frigateMappings).toHaveLength(1)
    expect(frigateMappings[0].frigate_camera).toBe("b")
  })

  it("emits test and backfill from the header actions", async () => {
    const { wrapper } = mountTab()

    const actions = wrapper.findAll(".system-page-actions button")
    await actions[0].trigger("click")
    await actions[1].trigger("click")

    expect(wrapper.emitted("test")).toHaveLength(1)
    expect(wrapper.emitted("backfill")).toHaveLength(1)
  })

  it("hides the connection actions until Frigate is configured", () => {
    const { wrapper } = mountTab({ frigateConfigured: false })

    expect(wrapper.find(".system-page-actions button").exists()).toBe(false)
  })

  it("disables the test button while a test is running", () => {
    const { wrapper } = mountTab({ frigateTesting: true })

    expect(
      wrapper.findAll(".system-page-actions button")[0].attributes("disabled")
    ).toBeDefined()
  })
})
