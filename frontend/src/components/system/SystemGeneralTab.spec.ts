import { mount } from "@vue/test-utils"
import { describe, expect, it } from "vitest"
import { reactive } from "vue"

import { i18n } from "../../i18n"
import SystemGeneralTab, {
  type GeneralForm,
  type RuntimeTuningForm
} from "./SystemGeneralTab.vue"

function mountTab(overrides: Record<string, unknown> = {}) {
  const generalForm = reactive<GeneralForm>({ systemName: "NVR" })
  const runtimeForm = reactive<RuntimeTuningForm>({
    prebufferFragmentSeconds: 5,
    prebufferBufferSeconds: 35,
    turnCredentialTtlSeconds: 600,
    playbackCacheMiB: 4096,
    playbackCacheTtlSeconds: 21600,
    playbackRestoreLockTtlSeconds: 900,
    liveTranscodeMaxDerivatives: 2,
    liveTranscodeIdleTtlSeconds: 20,
    liveTranscodeLeaseTtlSeconds: 30,
    liveTranscodeStartupTimeoutSeconds: 10,
    liveTranscodeCpuThreads: 2,
    liveTranscodeVideoBitrateKbps: 4000
  })
  const wrapper = mount(SystemGeneralTab, {
    props: {
      generalForm,
      runtimeForm,
      generalSaving: false,
      runtimeSaving: false,
      canManage: true,
      ...overrides
    },
    global: { plugins: [i18n] }
  })
  return { wrapper, generalForm, runtimeForm }
}

describe("SystemGeneralTab", () => {
  it("renders the system name field and both forms", () => {
    const { wrapper } = mountTab()

    expect(wrapper.find("input[maxlength='128']").exists()).toBe(true)
    expect(wrapper.findAll("form.system-form-card")).toHaveLength(2)
  })

  it("binds the name field to the passed form object", async () => {
    // The view owns the form; the tab mutates its property through v-model.
    const { wrapper, generalForm } = mountTab()

    await wrapper.find("input[maxlength='128']").setValue("Front Desk")

    expect(generalForm.systemName).toBe("Front Desk")
  })

  it("emits saveGeneral on submit of the first form", async () => {
    const { wrapper } = mountTab()

    await wrapper.findAll("form.system-form-card")[0].trigger("submit")

    expect(wrapper.emitted("saveGeneral")).toHaveLength(1)
    expect(wrapper.emitted("saveRuntime")).toBeUndefined()
  })

  it("emits saveRuntime on submit of the runtime form", async () => {
    const { wrapper } = mountTab()

    await wrapper.findAll("form.system-form-card")[1].trigger("submit")

    expect(wrapper.emitted("saveRuntime")).toHaveLength(1)
  })

  it("disables the save button while saving or without permission", () => {
    const saving = mountTab({ generalSaving: true }).wrapper
    expect(saving.find("button[type='submit']").attributes("disabled")).toBeDefined()

    const readOnly = mountTab({ canManage: false }).wrapper
    expect(readOnly.find("button[type='submit']").attributes("disabled")).toBeDefined()
  })

  it("renders the runtime tuning inputs bound to the runtime form", async () => {
    const { wrapper, runtimeForm } = mountTab()

    const numeric = wrapper.findAll("input[type='number']")
    expect(numeric.length).toBeGreaterThan(0)

    await numeric[0].setValue("9")
    expect(runtimeForm.prebufferFragmentSeconds).toBe(9)
  })
})
