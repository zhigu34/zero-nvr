import { mount } from "@vue/test-utils"
import { describe, expect, it, vi } from "vitest"

import type { ExportJob } from "../../api/exports"
import type { RecordingProtection } from "../../api/recordings"
import PlaybackActionHistory from "./PlaybackActionHistory.vue"

vi.mock("vue-i18n", () => ({
  useI18n: () => ({ t: (key: string) => key })
}))

const protection = {
  id: "protection-a",
  reason: "Incident",
  started_at: "2026-09-28T00:00:00Z",
  ended_at: "2026-09-28T00:01:00Z",
  expires_at: "2026-09-30T00:00:00Z"
} as RecordingProtection

const exportJob = {
  id: "export-a",
  state: "COMPLETED",
  start_at: "2026-09-28T00:00:00Z",
  requested_duration_ms: 60_000,
  codec_mode: "copy"
} as ExportJob

const baseProps = {
  mode: "protect" as const,
  protections: [protection],
  exports: [] as ExportJob[],
  formatTimestamp: (date: Date) => date.toISOString(),
  translatedStatus: (value: string) => `status:${value}`
}

describe("PlaybackActionHistory", () => {
  it("shows protected ranges and sends edit and remove actions", async () => {
    const wrapper = mount(PlaybackActionHistory, { props: baseProps })

    expect(wrapper.text()).toContain("Incident")
    expect(wrapper.text()).toContain("playback.expires")
    await wrapper.find('button[title="playback.editProtection"]').trigger("click")
    await wrapper.find('button[title="playback.removeProtection"]').trigger("click")

    expect(wrapper.emitted("edit-protection")?.[0]).toEqual([protection])
    expect(wrapper.emitted("remove-protection")?.[0]).toEqual([protection])
  })

  it("shows a completed export with share, download and delete actions", async () => {
    const wrapper = mount(PlaybackActionHistory, {
      props: {
        ...baseProps,
        mode: "export",
        protections: [],
        exports: [exportJob]
      }
    })

    expect(wrapper.text()).toContain("status:COMPLETED")
    expect(wrapper.find('a[title="playback.downloadMp4"]').attributes("href"))
      .toBe("/api/v1/exports/export-a/download")
    await wrapper.find('button[title="playback.manageShareLink"]').trigger("click")
    await wrapper.find('button[title="playback.deleteExport"]').trigger("click")

    expect(wrapper.emitted("open-share")?.[0]).toEqual([exportJob])
    expect(wrapper.emitted("remove-export")?.[0]).toEqual([exportJob])
  })
})
