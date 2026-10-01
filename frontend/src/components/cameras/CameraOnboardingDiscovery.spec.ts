import { mount } from "@vue/test-utils"
import { describe, expect, it } from "vitest"

import {
  type DiscoveryCandidate,
  type DiscoverySession
} from "../../api/cameras"
import { i18n } from "../../i18n"
import CameraOnboardingDiscovery from "./CameraOnboardingDiscovery.vue"

function candidate(id: string, host: string | null, state = "ready") {
  return { id, host, port: 80, state } as unknown as DiscoveryCandidate
}

function session(candidates: DiscoveryCandidate[]) {
  return { candidates } as unknown as DiscoverySession
}

function mountBlock(
  overrides: {
    discovery?: DiscoverySession | null
    selectedCandidateId?: string | null
    working?: string | null
  } = {}
) {
  return mount(CameraOnboardingDiscovery, {
    props: {
      discovery: overrides.discovery ?? session([candidate("c1", "10.0.0.11")]),
      selectedCandidateId: overrides.selectedCandidateId ?? null,
      working: (overrides.working ?? null) as never
    },
    global: { plugins: [i18n] }
  })
}

describe("CameraOnboardingDiscovery", () => {
  it("emits discover from the sweep button", async () => {
    const wrapper = mountBlock()

    await wrapper.find("button.button--secondary").trigger("click")

    expect(wrapper.emitted("discover")).toHaveLength(1)
  })

  it("disables the sweep while another action runs", () => {
    const wrapper = mountBlock({ working: "inspect" })

    expect(
      wrapper.find("button.button--secondary").attributes("disabled")
    ).toBeDefined()
  })

  it("lists candidates and marks the selected one", () => {
    const wrapper = mountBlock({
      discovery: session([candidate("c1", "10.0.0.11"), candidate("c2", "10.0.0.12")]),
      selectedCandidateId: "c2"
    })

    const cards = wrapper.findAll(".candidate-card")
    expect(cards).toHaveLength(2)
    expect(cards[0].classes()).not.toContain("candidate-card--selected")
    expect(cards[1].classes()).toContain("candidate-card--selected")
  })

  it("emits the chosen candidate", async () => {
    const wrapper = mountBlock({
      discovery: session([candidate("c1", "10.0.0.11")])
    })

    await wrapper.find(".candidate-card").trigger("click")

    expect(wrapper.emitted("useCandidate")![0][0]).toMatchObject({ id: "c1" })
  })

  it("disables a candidate with no address", () => {
    const wrapper = mountBlock({
      discovery: session([candidate("c1", null)])
    })

    expect(wrapper.find(".candidate-card").attributes("disabled")).toBeDefined()
  })

  it("shows a hint when a sweep found nothing", () => {
    expect(mountBlock({ discovery: session([]) }).find(".onboarding-hint").exists()).toBe(
      true
    )
    // Before any sweep there is no hint either.
    expect(mountBlock({ discovery: null }).find(".onboarding-hint").exists()).toBe(
      false
    )
  })
})
