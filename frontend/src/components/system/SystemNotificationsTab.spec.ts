import { mount } from "@vue/test-utils"
import { describe, expect, it } from "vitest"
import { reactive } from "vue"

import {
  type NotificationDelivery,
  type NotificationTarget
} from "../../api/system"
import { i18n } from "../../i18n"
import SystemNotificationsTab, {
  type NotificationForm
} from "./SystemNotificationsTab.vue"

const TARGET: NotificationTarget = {
  id: "t1",
  name: "Ops email",
  kind: "apprise",
  enabled: true,
  config: { password_reset: true },
  url_configured: true,
  credentials_configured: true
}

const DELIVERY: NotificationDelivery = {
  id: "d1",
  alert_id: null,
  purpose: "alert",
  notification_target_id: "t1",
  state: "SENT",
  attempt_count: 1,
  title: "Camera offline",
  body: "Front Door stopped responding",
  last_attempt_at: null,
  sent_at: "2026-09-20T10:00:05Z",
  last_error_code: null,
  provider_message_id: null,
  correlation_id: null,
  created_at: "2026-09-20T10:00:00Z",
  updated_at: "2026-09-20T10:00:05Z"
}

function mountTab(overrides: Record<string, unknown> = {}) {
  const notificationForm = reactive<NotificationForm>({
    name: "",
    url: "",
    passwordReset: false
  })
  const wrapper = mount(SystemNotificationsTab, {
    props: {
      targets: [TARGET],
      deliveries: [DELIVERY],
      notificationForm,
      notificationPanelOpen: false,
      editingNotification: null,
      notificationSaving: false,
      testingNotificationId: null,
      canManage: true,
      ...overrides
    },
    global: { plugins: [i18n], stubs: { UiIcon: true } }
  })
  return { wrapper, notificationForm }
}

describe("SystemNotificationsTab", () => {
  it("renders a target card and the deliveries table", () => {
    const { wrapper } = mountTab()

    expect(wrapper.findAll(".notification-card")).toHaveLength(1)
    expect(wrapper.text()).toContain("Ops email")
    expect(wrapper.find("table").exists()).toBe(true)
  })

  it("colours the enabled chip through StatusPill", () => {
    // This chip used to be a hand-rolled span carrying the same classes.
    const wrapper = mountTab().wrapper
    expect(wrapper.find(".status-pill--ok").exists()).toBe(true)

    const disabled = mountTab({
      targets: [{ ...TARGET, enabled: false }]
    }).wrapper
    expect(disabled.find(".status-pill--muted").exists()).toBe(true)
  })

  it("emits editTarget with the row the operator chose", async () => {
    const { wrapper } = mountTab()

    const edit = wrapper
      .findAll("button")
      .find((b) => b.attributes("title")?.includes("Edit"))!
    await edit.trigger("click")

    expect(wrapper.emitted("editTarget")![0]).toEqual([TARGET])
  })

  it("emits testTarget with the row being tested", async () => {
    const { wrapper } = mountTab()

    // The test control is the only labelled button in the card; the others are
    // icon-only buttons carrying titles.
    const test = wrapper.find(".notification-card__actions button.button--ghost")
    await test.trigger("click")

    expect(wrapper.emitted("testTarget")![0]).toEqual([TARGET])
  })

  it("emits openPanel from the add-target button", async () => {
    const { wrapper } = mountTab()

    await wrapper.find(".system-page-header button").trigger("click")

    expect(wrapper.emitted("openPanel")).toHaveLength(1)
  })

  it("hides the editor until the panel is opened", () => {
    expect(mountTab().wrapper.find(".system-drawer").exists()).toBe(false)

    const open = mountTab({ notificationPanelOpen: true }).wrapper
    expect(open.find(".system-drawer").exists()).toBe(true)
  })

  it("keeps the editor closed without permission even when the flag is set", () => {
    // The permission check is part of the drawer's v-if, so a stale flag cannot
    // expose the form to a read-only operator.
    const { wrapper } = mountTab({
      notificationPanelOpen: true,
      canManage: false
    })

    expect(wrapper.find(".system-drawer").exists()).toBe(false)
  })

  it("binds the editor fields to the form owned by the view", async () => {
    const { wrapper, notificationForm } = mountTab({
      notificationPanelOpen: true
    })

    await wrapper.find(".system-drawer input").setValue("Ops SMS")
    expect(notificationForm.name).toBe("Ops SMS")
  })

  it("emits closePanel from both the close and cancel controls", async () => {
    const { wrapper } = mountTab({ notificationPanelOpen: true })

    await wrapper.find(".storage-editor__header button").trigger("click")
    expect(wrapper.emitted("closePanel")).toHaveLength(1)

    const cancel = wrapper
      .findAll(".storage-editor__actions button")
      .find((b) => b.text().includes("Cancel"))!
    await cancel.trigger("click")
    expect(wrapper.emitted("closePanel")).toHaveLength(2)
  })

  it("emits save on submit and disables the control while saving", async () => {
    const { wrapper } = mountTab({ notificationPanelOpen: true })

    await wrapper.find(".storage-editor__form").trigger("submit")
    expect(wrapper.emitted("save")).toHaveLength(1)

    const saving = mountTab({
      notificationPanelOpen: true,
      notificationSaving: true
    }).wrapper
    expect(
      saving.find("button[type='submit']").attributes("disabled")
    ).toBeDefined()
  })
})
