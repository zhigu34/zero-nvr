import { mount } from "@vue/test-utils"
import { describe, expect, it } from "vitest"

import EmptyState from "./EmptyState.vue"

describe("EmptyState", () => {
  it("puts the surface class on the root element", () => {
    // The root is what a parent view's scoped rule selects; the descendants
    // come from the caller so their own scoped rules keep matching.
    const wrapper = mount(EmptyState, {
      props: { surfaceClass: "storage-empty" },
      slots: { default: "<strong>Nothing here</strong>" }
    })

    expect(wrapper.element.tagName).toBe("DIV")
    expect(wrapper.classes()).toContain("storage-empty")
  })

  it("adds the large modifier only when asked", () => {
    const plain = mount(EmptyState, { props: { surfaceClass: "empty-state" } })
    expect(plain.classes()).not.toContain("empty-state--large")

    const large = mount(EmptyState, {
      props: { surfaceClass: "empty-state", large: true }
    })
    expect(large.classes()).toContain("empty-state--large")
  })

  it("keeps the caller's title and hint elements", () => {
    // `.empty-state strong` and `.empty-state p` are descendant rules; they
    // only apply if these elements belong to the owning view.
    const wrapper = mount(EmptyState, {
      props: { surfaceClass: "empty-state" },
      slots: {
        default: "<strong>No cameras</strong><p>Add one to get started</p>"
      }
    })

    expect(wrapper.find("strong").text()).toBe("No cameras")
    expect(wrapper.find("p").text()).toBe("Add one to get started")
  })

  it("supports multiple surface classes", () => {
    const wrapper = mount(EmptyState, {
      props: { surfaceClass: "empty-state extra" }
    })

    expect(wrapper.classes()).toEqual(["empty-state", "extra"])
  })
})
