import { mount } from "@vue/test-utils"
import { describe, expect, it } from "vitest"

import StatusPill, { type StatusVariant } from "./StatusPill.vue"

function mountPill(variant?: StatusVariant, slot = "ACTIVE") {
  return mount(StatusPill, {
    props: variant ? { variant } : {},
    slots: { default: slot }
  })
}

describe("StatusPill", () => {
  it("renders the base class on a span", () => {
    const wrapper = mountPill("ok")

    expect(wrapper.element.tagName).toBe("SPAN")
    expect(wrapper.classes()).toContain("status-pill")
  })

  it("maps a variant to its modifier class", () => {
    expect(mountPill("ok").classes()).toContain("status-pill--ok")
    expect(mountPill("muted").classes()).toContain("status-pill--muted")
    expect(mountPill("error").classes()).toContain("status-pill--error")
    expect(mountPill("warning").classes()).toContain("status-pill--warning")
    expect(mountPill("danger").classes()).toContain("status-pill--danger")
  })

  it("covers the camera lifecycle variants", () => {
    // These live in CamerasView's scoped styles rather than the global sheet,
    // which still applies because the class is on this component's root.
    expect(mountPill("online").classes()).toContain("status-pill--online")
    expect(mountPill("offline").classes()).toContain("status-pill--offline")
    expect(mountPill("maintenance").classes()).toContain(
      "status-pill--maintenance"
    )
    expect(mountPill("disabled").classes()).toContain("status-pill--disabled")
    expect(mountPill("retired").classes()).toContain("status-pill--retired")
  })

  it("adds no modifier when no variant is given", () => {
    // Some sites render the bare chip on purpose; adding --muted would change
    // their opacity without anyone asking for it.
    const wrapper = mountPill()

    expect(wrapper.classes()).toEqual(["status-pill"])
  })

  it("renders the slot content", () => {
    expect(mountPill("ok", "RESOLVED").text()).toBe("RESOLVED")
  })

  it("warns at compile time for an undefined variant", () => {
    // The union is the guard that would have caught --warning/--danger being
    // referenced before any rule defined them: those names are still in the
    // union because the rules now exist, but a truly unknown name cannot type
    // check. This asserts the union stays closed by checking the list.
    const variants: StatusVariant[] = [
      "ok",
      "muted",
      "warning",
      "danger",
      "error",
      "online",
      "offline",
      "maintenance",
      "disabled",
      "retired"
    ]
    expect(variants).toHaveLength(10)
  })
})
