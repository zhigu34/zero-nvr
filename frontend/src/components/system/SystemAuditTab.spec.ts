import { mount } from "@vue/test-utils"
import { describe, expect, it } from "vitest"
import { reactive } from "vue"

import { type AuditEvent } from "../../api/system"
import { i18n } from "../../i18n"
import SystemAuditTab, { type AuditFilters } from "./SystemAuditTab.vue"

const EVENT: AuditEvent = {
  id: "e1",
  occurred_at: "2026-09-20T17:30:45Z",
  actor_type: "user",
  actor_id: null,
  action: "camera.update",
  resource_type: "camera",
  resource_id: null,
  camera_id: null,
  result: "success",
  reason: null,
  source_ip: "10.0.0.5",
  request_id: null,
  before: null,
  after: null,
  metadata: null
} as AuditEvent

function mountTab(overrides: Record<string, unknown> = {}) {
  const auditFilters = reactive<AuditFilters>({
    period: "7d",
    action: "",
    resourceType: "",
    result: ""
  })
  const wrapper = mount(SystemAuditTab, {
    props: {
      auditEvents: [EVENT],
      auditFilters,
      auditLoading: false,
      auditLoadingMore: false,
      auditNextCursor: null,
      ...overrides
    },
    global: { plugins: [i18n], stubs: { UiIcon: true } }
  })
  return { wrapper, auditFilters }
}

describe("SystemAuditTab", () => {
  it("renders the toolbar, the filters and one row per event", () => {
    const { wrapper } = mountTab()

    expect(wrapper.find(".audit-toolbar").exists()).toBe(true)
    // period, action, resource type and result
    expect(wrapper.findAll(".audit-filter")).toHaveLength(4)
    expect(wrapper.findAll(".audit-list article")).toHaveLength(1)
    // `pretty` title-cases the token and turns separators into spacing, so
    // `camera.update` reads as `Camera · Update`.
    expect(wrapper.find(".audit-list__main strong").text()).toBe("Camera · Update")
  })

  it("binds filters to the object owned by the view", async () => {
    const { wrapper, auditFilters } = mountTab()

    await wrapper.findAll("select")[0].setValue("30d")

    expect(auditFilters.period).toBe("30d")
  })

  it("asks for a reload when a filter changes", async () => {
    const { wrapper } = mountTab()

    await wrapper.findAll("select")[0].setValue("24h")

    expect(wrapper.emitted("reload")).toHaveLength(1)
  })

  it("emits resetFilters from the clear button", async () => {
    const { wrapper } = mountTab()

    await wrapper.find(".audit-toolbar__actions button").trigger("click")

    expect(wrapper.emitted("resetFilters")).toHaveLength(1)
  })

  it("shows the empty state when there are no events", () => {
    const { wrapper } = mountTab({ auditEvents: [] })

    expect(wrapper.find(".audit-empty").exists()).toBe(true)
    expect(wrapper.find(".audit-list").exists()).toBe(false)
  })

  it("offers load-more only when a cursor exists", async () => {
    expect(mountTab().wrapper.find(".audit-load-more").exists()).toBe(false)

    const { wrapper } = mountTab({ auditNextCursor: "cursor-1" })
    expect(wrapper.find(".audit-load-more").exists()).toBe(true)

    await wrapper.find(".audit-load-more").trigger("click")
    expect(wrapper.emitted("loadMore")).toHaveLength(1)
  })

  it("disables the refresh control while loading", () => {
    const button = mountTab({ auditLoading: true }).wrapper.find(
      ".system-page-header button"
    )
    expect(button.attributes("disabled")).toBeDefined()
  })
})
