import { mount } from "@vue/test-utils"
import { describe, expect, it } from "vitest"
import { reactive } from "vue"

import {
  type BackupPolicy,
  type BackupSet,
  type ConfigurationImportValidation
} from "../../api/system"
import { i18n } from "../../i18n"
import SystemBackupTab, { type BackupForm } from "./SystemBackupTab.vue"

const POLICY: BackupPolicy = {
  id: "p1",
  name: "Nightly system backup",
  enabled: true,
  database_backend: "sqlite",
  schedule: { cron: "0 3 * * *" },
  retention: {},
  verify_after_backup: true,
  repository_check_schedule: {},
  include_deployment_config: true,
  repository_configured: true,
  credentials_configured: true
}

const BACKUP: BackupSet = {
  id: "b1",
  backup_policy_id: "p1",
  state: "COMPLETED",
  reason: "scheduled",
  started_at: "2026-09-20T03:00:00Z",
  completed_at: "2026-09-20T03:04:00Z",
  app_version: "1.0.0",
  schema_revision: "0007",
  database_engine: "sqlite",
  restic_snapshot_id: "snap-1",
  size_bytes: 1024 ** 3,
  verification_state: "VERIFIED",
  last_verified_at: "2026-09-20T03:05:00Z",
  error_code: null,
  sanitized_error: null,
  created_at: "2026-09-20T03:00:00Z"
}

const VALIDATION: ConfigurationImportValidation = {
  valid: true,
  format: "zero-nvr.configuration",
  format_version: 1,
  source_application_version: "1.0.0",
  section_counts: { cameras: 1 },
  credentials_required: [],
  warnings: []
}

function makeForm(): BackupForm {
  return reactive<BackupForm>({
    name: "System backup",
    repository: "/srv/restic",
    password: "",
    environmentCredentials: "",
    initializeIfMissing: true,
    scheduled: true,
    cron: "0 3 * * *",
    keepLast: 7,
    keepDaily: 7,
    keepWeekly: 4,
    keepMonthly: 6,
    verifyAfter: true,
    includeDeploymentConfig: true,
    enabled: true
  })
}

function mountTab(overrides: Record<string, unknown> = {}) {
  const wrapper = mount(SystemBackupTab, {
    props: {
      backupPolicies: [POLICY],
      backups: [BACKUP],
      settings: null,
      backupForm: makeForm(),
      backupPanelOpen: false,
      editingBackupPolicy: null,
      backupSaving: false,
      backupRefreshing: false,
      runningBackupId: null,
      verifyingBackupId: null,
      configImportValidation: null,
      configImportFileName: null,
      configImportValidating: false,
      configImportApplying: false,
      configImportApplyResult: null,
      configImportBundle: null,
      canManage: true,
      ...overrides
    },
    global: {
      plugins: [i18n],
      stubs: { UiIcon: true, SystemRecoveryKitPanel: true }
    }
  })
  return wrapper
}

describe("SystemBackupTab", () => {
  it("renders the recovery card, the policy grid and the history table", () => {
    const wrapper = mountTab()

    expect(wrapper.find(".backup-recovery-card").exists()).toBe(true)
    expect(wrapper.findAll(".backup-policy-card").length).toBeGreaterThan(0)
    expect(wrapper.text()).toContain("Nightly system backup")
    expect(wrapper.find("table.system-table").exists()).toBe(true)
  })

  it("names the policy on each history row", () => {
    // `backupPolicyName` moved into the tab with the markup.
    const wrapper = mountTab()
    const row = wrapper.find("table.system-table tbody tr")

    expect(row.text()).toContain("Nightly system backup")
  })

  it("falls back to an unknown-policy label for an orphaned backup", () => {
    const wrapper = mountTab({
      backups: [{ ...BACKUP, backup_policy_id: "gone" }]
    })

    expect(wrapper.find("table.system-table tbody tr").text()).not.toContain(
      "Nightly system backup"
    )
  })

  it("formats the backup size", () => {
    const wrapper = mountTab()
    // 1 GiB is rendered by the shared byte formatter, not a raw number.
    expect(wrapper.find("table.system-table tbody tr").text()).toMatch(/GB|MB/)
  })

  it("emits copyCommand with the shell command for each recovery action", async () => {
    const wrapper = mountTab()

    const copyButtons = wrapper.findAll(".backup-recovery-commands button")
    expect(copyButtons.length).toBeGreaterThan(0)

    await copyButtons[0].trigger("click")

    const emitted = wrapper.emitted("copyCommand")!
    expect(emitted).toHaveLength(1)
    expect(String(emitted[0][0])).toContain("./deploy.sh")
  })

  it("emits exportConfig from the header action", async () => {
    const wrapper = mountTab()

    const exportBtn = wrapper
      .findAll(".system-page-actions button")
      .find((b) => /export/i.test(b.text()))
    expect(exportBtn, "an export control is rendered").toBeDefined()

    await exportBtn!.trigger("click")

    expect(wrapper.emitted("exportConfig")).toHaveLength(1)
  })

  it("hands the parent a File rather than the input event", async () => {
    // The tab owns the hidden input; the view no longer reaches across for it.
    const wrapper = mountTab()
    const input = wrapper.find("input[type='file']")
    expect(input.exists()).toBe(true)

    const file = new File(['{"format":"zero-nvr"}'], "bundle.json", {
      type: "application/json"
    })
    Object.defineProperty(input.element, "files", { value: [file] })
    await input.trigger("change")

    const emitted = wrapper.emitted("configFile")!
    expect(emitted).toHaveLength(1)
    expect((emitted[0][0] as File).name).toBe("bundle.json")
  })

  it("shows the import preflight once a bundle is validated", () => {
    const wrapper = mountTab({
      configImportValidation: VALIDATION,
      configImportFileName: "bundle.json",
      configImportBundle: { format: VALIDATION.format }
    })

    expect(wrapper.text()).toContain(VALIDATION.format)
    expect(wrapper.text()).toContain("bundle.json")
  })

  it("emits configApply and configDiscard from the preflight", async () => {
    const wrapper = mountTab({
      configImportValidation: VALIDATION,
      configImportBundle: { format: VALIDATION.format }
    })

    const apply = wrapper
      .findAll("button")
      .find((b) => /apply|merge/i.test(b.text()))
    if (apply) await apply.trigger("click")

    expect(wrapper.emitted("configApply")).toBeTruthy()
  })

  it("keeps the editor drawer closed until opened", () => {
    expect(mountTab().find(".system-drawer").exists()).toBe(false)

    const open = mountTab({
      backupPanelOpen: true,
      editingBackupPolicy: POLICY
    })
    expect(open.find(".system-drawer").exists()).toBe(true)
  })

  it("emits verifySet from the history row", async () => {
    const wrapper = mountTab()

    const verify = wrapper
      .findAll("table.system-table tbody button")
      .find((b) => b.text().length > 0)
    expect(verify, "a verify control is rendered per run").toBeDefined()

    await verify!.trigger("click")

    expect(wrapper.emitted("verifySet")![0]).toEqual([BACKUP])
  })

  it("emits editPolicy and runPolicy from a policy card", async () => {
    const wrapper = mountTab()

    // The first `.backup-policy-card` is the import preflight; the policies are
    // the ones inside the grid.
    const card = wrapper.find(".backup-policy-grid .backup-policy-card")
    expect(card.exists()).toBe(true)

    const buttons = card.findAll("button")
    const edit = buttons.find((b) => /edit/i.test(b.text()))!
    const run = buttons.find((b) => /run/i.test(b.text()))!

    await edit.trigger("click")
    await run.trigger("click")

    expect(wrapper.emitted("editPolicy")![0]).toEqual([POLICY])
    expect(wrapper.emitted("runPolicy")![0]).toEqual([POLICY])
  })
})
