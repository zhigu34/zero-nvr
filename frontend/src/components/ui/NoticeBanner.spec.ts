import { mount } from "@vue/test-utils"
import { describe, expect, it } from "vitest"

import NoticeBanner from "./NoticeBanner.vue"

interface BannerProps {
  surfaceClass: string
  variant?: "error" | "success"
  iconSize?: number
}

function mountBanner(props: BannerProps, slot = "Something failed") {
  return mount(NoticeBanner, {
    props,
    slots: { default: slot },
    global: { stubs: { UiIcon: { props: ["name", "size"], template: '<i :data-name="name" :data-size="size" />' } } }
  })
}

describe("NoticeBanner", () => {
  it("puts the surface class on the root element", () => {
    // The whole migration depends on this: a parent view's scoped CSS selects
    // the root, which Vue stamps with the parent's scope id. A class emitted on
    // a nested node would silently lose its styling.
    const wrapper = mountBanner({ surfaceClass: "events-error" })

    expect(wrapper.element.tagName).toBe("DIV")
    expect(wrapper.classes()).toContain("events-error")
  })

  it("renders the message inside a span next to the icon", () => {
    const wrapper = mountBanner({ surfaceClass: "events-error" }, "Disk is full")

    expect(wrapper.find("span").text()).toBe("Disk is full")
    expect(wrapper.find("i").attributes("data-name")).toBe("warning")
  })

  it("uses the warning glyph at 15px for errors by default", () => {
    const wrapper = mountBanner({ surfaceClass: "events-error" })

    expect(wrapper.find("i").attributes("data-name")).toBe("warning")
    expect(wrapper.find("i").attributes("data-size")).toBe("15")
  })

  it("uses the smaller check glyph for successes", () => {
    // Success confirmations are intentionally quieter than failure banners.
    const wrapper = mountBanner(
      { surfaceClass: "storage-notice", variant: "success" },
      "Saved"
    )

    expect(wrapper.find("i").attributes("data-name")).toBe("check")
    expect(wrapper.find("i").attributes("data-size")).toBe("14")
  })

  it("lets a surface override the glyph size", () => {
    // The dashboard and system views render these banners larger.
    const wrapper = mountBanner({ surfaceClass: "events-error", iconSize: 16 })

    expect(wrapper.find("i").attributes("data-size")).toBe("16")
  })

  it("accepts a compound surface class", () => {
    // The recovery-kit panel styles a base class plus a variant class.
    const wrapper = mountBanner({
      surfaceClass: "recovery-kit-panel__message recovery-kit-panel__message--error"
    })

    expect(wrapper.classes()).toEqual([
      "recovery-kit-panel__message",
      "recovery-kit-panel__message--error"
    ])
  })
})
