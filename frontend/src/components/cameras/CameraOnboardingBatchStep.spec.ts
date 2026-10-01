import { mount } from "@vue/test-utils"
import { describe, expect, it } from "vitest"

import {
  type DiscoveryCandidate,
  type DiscoverySession
} from "../../api/cameras"
import { i18n } from "../../i18n"
import CameraOnboardingBatchStep from "./CameraOnboardingBatchStep.vue"
import { type BatchResult } from "./onboarding"

function candidate(id: string, host: string | null, name?: string): DiscoveryCandidate {
  return {
    id,
    host,
    display_info: name ? { name } : {},
    ports: []
  } as unknown as DiscoveryCandidate
}

const DISCOVERY = {
  candidates: [
    candidate("c1", "10.0.0.11", "Lobby"),
    candidate("c2", "10.0.0.12")
  ]
} as unknown as DiscoverySession

function mountStep(
  overrides: {
    selected?: string[]
    results?: BatchResult[]
    canManageStorage?: boolean
    working?: string | null
    discovery?: DiscoverySession
  } = {}
) {
  const wrapper = mount(CameraOnboardingBatchStep, {
    props: {
      discovery: overrides.discovery ?? DISCOVERY,
      batchGroups: [],
      batchStorageTargets: [],
      batchResults: overrides.results ?? [],
      canManageStorage: overrides.canManageStorage ?? true,
      working: (overrides.working ?? null) as never,
      batchCredential: (id: string) => ({ username: "", password: "" }),
      candidateName: (c: DiscoveryCandidate) =>
        (c.display_info.name as string) || c.host || "device",
      batchStateLabel: (state: string) => state.toUpperCase(),
      batchSelectedIds: overrides.selected ?? [],
      batchNameTemplate: "{name}",
      batchUsername: "",
      batchPassword: "",
      batchGroupId: "",
      batchRecordingMode: "continuous",
      batchStorageTargetId: "",
      batchTimeSyncMode: "monitor"
    },
    global: { plugins: [i18n] }
  })
  return wrapper
}

describe("CameraOnboardingBatchStep", () => {
  it("lists every discovered candidate", () => {
    const wrapper = mountStep()

    expect(wrapper.findAll(".probe-card")).toHaveLength(2)
    // The name falls back to the host when discovery reported none.
    expect(wrapper.text()).toContain("Lobby")
    expect(wrapper.text()).toContain("10.0.0.12")
  })

  it("shows credential overrides only for selected devices", async () => {
    const wrapper = mountStep()
    expect(wrapper.findAll(".check-row + .form-grid")).toHaveLength(0)

    await wrapper.setProps({ batchSelectedIds: ["c1"] })
    expect(wrapper.findAll(".form-grid").length).toBeGreaterThan(0)
  })

  it("disables a device without a reachable address", () => {
    const wrapper = mountStep({
      discovery: { candidates: [candidate("c1", null)] } as unknown as DiscoverySession
    })

    expect(
      wrapper.find(".check-row input[type='checkbox']").attributes("disabled")
    ).toBeDefined()
  })

  it("emits run only once a reachable device is selected", async () => {
    const wrapper = mountStep()
    const run = wrapper.find("button.button--primary")

    // Nothing selected yet, so the import control is disabled.
    expect(run.attributes("disabled")).toBeDefined()
    await run.trigger("click")
    expect(wrapper.emitted("run")).toBeUndefined()

    await wrapper.setProps({ batchSelectedIds: ["c1"] })
    const enabled = wrapper.find("button.button--primary")
    await enabled.trigger("click")
    expect(wrapper.emitted("run")).toHaveLength(1)
  })

  it("keeps the import control disabled while another action runs", () => {
    const wrapper = mountStep({ selected: ["c1"], working: "discover" })

    expect(
      wrapper.find("button.button--primary").attributes("disabled")
    ).toBeDefined()
  })

  it("locks the storage target without permission", () => {
    const allowed = mountStep({ canManageStorage: true })
    const locked = mountStep({ canManageStorage: false })

    // The storage target is the select whose control is permission-gated; the
    // group, recording-mode and time-sync selects are not.
    const disabled = (w: ReturnType<typeof mountStep>) =>
      w
        .findAll("select")
        .filter((s) => s.attributes("disabled") !== undefined)

    expect(disabled(allowed)).toHaveLength(0)
    expect(disabled(locked)).toHaveLength(1)
  })

  it("renders a per-device result through the parent's labeller", () => {
    const wrapper = mountStep({
      results: [
        {
          candidate_id: "c1",
          label: "Lobby",
          state: "partial",
          message: "created, credential failed",
          camera_ids: ["cam-1"]
        }
      ]
    })

    expect(wrapper.find(".field-hint strong").text()).toBe("PARTIAL")
    expect(wrapper.text()).toContain("created, credential failed")
  })
})
