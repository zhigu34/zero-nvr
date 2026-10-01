import { mount } from "@vue/test-utils"
import { describe, expect, it } from "vitest"

import {
  type SystemHealth,
  type SystemInfo,
  type SystemUpdateInfo
} from "../../api/system"
import { i18n } from "../../i18n"
import SystemOverviewTab from "./SystemOverviewTab.vue"

interface OverviewProps {
  health?: SystemHealth | null
  info?: SystemInfo | null
  updateInfo?: SystemUpdateInfo | null
  loading?: boolean
  canViewSecretStore?: boolean
}

function mountTab(overrides: OverviewProps = {}) {
  return mount(SystemOverviewTab, {
    props: {
      health: null,
      info: null,
      updateInfo: null,
      loading: false,
      canViewSecretStore: false,
      ...overrides
    },
    global: {
      plugins: [i18n],
      stubs: {
        UiIcon: true,
        SystemSecretStorePanel: {
          name: "SystemSecretStorePanel",
          template: '<div class="secret-store-stub" />'
        }
      }
    }
  })
}

const HEALTHY: SystemHealth = {
  status: "OK",
  components: {
    database: { status: "OK", message: "", details: {} },
    storage: {
      status: "DEGRADED",
      message: "",
      details: {
        target_details: [
          {
            id: "t1",
            name: "Local NVMe",
            level: "warning",
            used_percent: 82.4,
            free_bytes: 1024 ** 3,
            warning_percent: 80,
            high_percent: 90,
            critical_percent: 95
          }
        ]
      }
    },
    worker: { status: "OK", message: "Running", details: {} }
  }
}

describe("SystemOverviewTab", () => {
  it("renders the four summary cards and the health components", () => {
    const wrapper = mountTab({ health: HEALTHY })

    expect(wrapper.findAll(".system-overview-card")).toHaveLength(4)
    expect(wrapper.findAll(".health-component")).toHaveLength(3)
  })

  it("colours the orb from the overall status", () => {
    expect(mountTab({ health: HEALTHY }).find(".system-health-orb--ok").exists()).toBe(
      true
    )
    // A missing health payload must not produce an undefined modifier.
    expect(
      mountTab({ health: null }).find(".system-health-orb--disabled").exists()
    ).toBe(true)
  })

  it("renders storage target rows with their detail and thresholds", () => {
    // The storage readers moved into this tab with the markup, so this is the
    // only place they are exercised now.
    const wrapper = mountTab({ health: HEALTHY })

    const rows = wrapper.findAll(".storage-health-row")
    expect(rows).toHaveLength(1)
    expect(rows[0].text()).toContain("Local NVMe")
    expect(rows[0].find("small").exists()).toBe(true)
  })

  it("drops a malformed storage target instead of rendering blanks", () => {
    const wrapper = mountTab({
      health: {
        status: "OK",
        components: {
          storage: {
            status: "OK",
            message: "",
            details: { target_details: [{ id: "t1" }, "junk", null] }
          }
        }
      }
    })

    expect(wrapper.findAll(".storage-health-row")).toHaveLength(0)
  })

  it("emits refresh from the header button", async () => {
    const wrapper = mountTab({ health: HEALTHY })

    await wrapper.find(".system-page-header button").trigger("click")

    expect(wrapper.emitted("refresh")).toHaveLength(1)
  })

  it("disables the refresh button while loading", () => {
    const button = mountTab({ health: HEALTHY, loading: true }).find(
      ".system-page-header button"
    )
    expect(button.attributes("disabled")).toBeDefined()
  })

  it("only mounts the secret-store panel when permitted", () => {
    expect(mountTab({ canViewSecretStore: true }).find(".secret-store-stub").exists()).toBe(
      true
    )
    expect(mountTab({ canViewSecretStore: false }).find(".secret-store-stub").exists()).toBe(
      false
    )
  })

  it("falls back to em dashes when version and update data are absent", () => {
    const text = mountTab({ health: null }).text()
    expect(text).toContain("—")
  })
})
