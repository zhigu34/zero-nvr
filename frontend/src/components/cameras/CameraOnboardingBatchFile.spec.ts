import { mount } from "@vue/test-utils"
import { describe, expect, it } from "vitest"

import { i18n } from "../../i18n"
import CameraOnboardingBatchFile from "./CameraOnboardingBatchFile.vue"
import { type FileBatchResult, type FileImportRow } from "./onboarding"

function row(line: number, errors: string[] = []): FileImportRow {
  return {
    line,
    kind: "onvif",
    name: "",
    host: `10.0.0.${line}`,
    onvif_port: 80,
    rtsp_port: 554,
    username: "",
    password: "",
    main_path: "",
    sub_path: "",
    main_url: "",
    sub_url: "",
    location: "",
    storage_label: "",
    errors
  }
}

function mountStep(
  overrides: {
    rows?: FileImportRow[]
    results?: FileBatchResult[]
    name?: string
    canImport?: boolean
    canManageStorage?: boolean
    working?: string | null
  } = {}
) {
  return mount(CameraOnboardingBatchFile, {
    props: {
      batchGroups: [],
      batchStorageTargets: [],
      fileBatchName: overrides.name ?? "",
      fileBatchRows: overrides.rows ?? [],
      fileBatchResults: overrides.results ?? [],
      canFileBatchImport: overrides.canImport ?? false,
      canManageStorage: overrides.canManageStorage ?? true,
      working: (overrides.working ?? null) as never,
      batchStateLabel: (s: string) => s.toUpperCase(),
      batchGroupId: "",
      batchRecordingMode: "continuous",
      batchStorageTargetId: "",
      batchTimeSyncMode: "monitor"
    },
    global: { plugins: [i18n] }
  })
}

describe("CameraOnboardingBatchFile", () => {
  it("renders the three steps", () => {
    const wrapper = mountStep()

    expect(wrapper.findAll(".onboarding-step")).toHaveLength(3)
    expect(wrapper.find("input[type='file']").exists()).toBe(true)
  })

  it("hands the parent a File rather than the input event", async () => {
    const wrapper = mountStep()
    const input = wrapper.find("input[type='file']")

    const file = new File(["type,name\n"], "cameras.csv", { type: "text/csv" })
    Object.defineProperty(input.element, "files", { value: [file] })
    await input.trigger("change")

    const emitted = wrapper.emitted("fileSelected")!
    expect(emitted).toHaveLength(1)
    expect((emitted[0][0] as File).name).toBe("cameras.csv")
  })

  it("emits downloadTemplate and blocks it while busy", async () => {
    const wrapper = mountStep()
    const button = wrapper.find("button.button--secondary")
    expect(button.attributes("disabled")).toBeUndefined()

    await button.trigger("click")
    expect(wrapper.emitted("downloadTemplate")).toHaveLength(1)

    expect(
      mountStep({ working: "import" })
        .find("button.button--secondary")
        .attributes("disabled")
    ).toBeDefined()
  })

  it("summarises the parsed file with ready and invalid counts", () => {
    // Both counts moved into this component from the panel.
    const wrapper = mountStep({
      name: "cameras.csv",
      rows: [row(1), row(2, ["bad host"]), row(3)]
    })

    // `csvLoaded` renders "{file}: {total} row(s), {valid} ready, {invalid} invalid."
    expect(wrapper.text()).toContain("cameras.csv: 3 row(s), 2 ready, 1 invalid.")
  })

  it("lists rows and shows per-row errors", () => {
    const wrapper = mountStep({ rows: [row(1), row(2, ["bad host"])] })

    expect(wrapper.findAll(".probe-card")).toHaveLength(2)
    expect(wrapper.find(".notice--error").text()).toContain("bad host")
  })

  it("gates the import control on the parent's flag", async () => {
    const blocked = mountStep()
    expect(
      blocked.find("button.button--primary").attributes("disabled")
    ).toBeDefined()

    const allowed = mountStep({ canImport: true })
    await allowed.find("button.button--primary").trigger("click")
    expect(allowed.emitted("run")).toHaveLength(1)
  })

  it("locks the storage target without permission", () => {
    const disabledSelects = (w: ReturnType<typeof mountStep>) =>
      w.findAll("select").filter((s) => s.attributes("disabled") !== undefined)

    expect(disabledSelects(mountStep({ canManageStorage: true }))).toHaveLength(0)
    expect(disabledSelects(mountStep({ canManageStorage: false }))).toHaveLength(1)
  })

  it("renders per-row import results", () => {
    const wrapper = mountStep({
      results: [
        {
          line: 1,
          label: "Line 1",
          state: "failed",
          message: "unreachable",
          camera_ids: []
        }
      ]
    })

    expect(wrapper.findAll(".probe-card").length).toBeGreaterThan(0)
    expect(wrapper.text()).toContain("unreachable")
  })
})
