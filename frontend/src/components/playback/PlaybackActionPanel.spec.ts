import { mount } from "@vue/test-utils"
import { describe, expect, it, vi } from "vitest"

import type { ExportJob, ExportShare, ExportShareCreated } from "../../api/exports"
import type { RecordingProtection } from "../../api/recordings"
import PlaybackActionPanel from "./PlaybackActionPanel.vue"

vi.mock("vue-i18n", () => ({
  useI18n: () => ({ t: (key: string) => key })
}))

const protection = {
  id: "protection-a",
  reason: "Incident",
  started_at: "2026-09-28T00:00:00Z",
  ended_at: "2026-09-28T00:01:00Z",
  expires_at: null
} as RecordingProtection

const exportJob = {
  id: "export-a",
  state: "COMPLETED",
  start_at: "2026-09-28T00:00:00Z",
  requested_duration_ms: 60_000,
  codec_mode: "copy"
} as ExportJob

const share = {
  id: "share-a",
  expires_at: "2026-09-30T00:00:00Z",
  revoked_at: null,
  max_downloads: null,
  download_count: 0,
  password_protected: false
} as ExportShare

const createdShare = {
  ...share,
  download_path: "/shares/share-a",
  token: "one-time-token"
} as ExportShareCreated

const baseProps = {
  actionMode: "protect" as const,
  cameraName: "Lobby",
  editingProtectionId: null,
  actionStart: "2026-09-28T08:00:00",
  actionEnd: "2026-09-28T08:01:00",
  protectionReason: "Incident",
  protectionExpiresAt: "",
  exportCodecMode: "auto" as const,
  exportGapPolicy: "skip" as const,
  actionSaving: false,
  cameraProtections: [protection],
  cameraExports: [] as ExportJob[],
  shareExport: null as ExportJob | null,
  sharePassword: "",
  shareExpiresHours: 24,
  shareMaxDownloads: 0,
  shareSaving: false,
  shareCopied: false,
  createdShare: null as ExportShareCreated | null,
  exportShares: [] as ExportShare[],
  formatTimestamp: (date: Date) => date.toISOString(),
  translatedStatus: (value: string) => value,
  shareUrl: (item: ExportShareCreated) => `https://example.test${item.download_path}`
}

describe("PlaybackActionPanel", () => {
  it("edits protection fields and sends protection actions", async () => {
    const wrapper = mount(PlaybackActionPanel, { props: baseProps })

    await wrapper.find('input[maxlength="1024"]').setValue("Updated incident")
    await wrapper.find(".playback-action-form").trigger("submit")
    await wrapper.find('button[title="playback.editProtection"]').trigger("click")
    await wrapper.find('button[title="playback.removeProtection"]').trigger("click")
    await wrapper.find("header button").trigger("click")

    expect(wrapper.emitted("update:protectionReason")?.[0]).toEqual(["Updated incident"])
    expect(wrapper.emitted("save-protection")).toHaveLength(1)
    expect(wrapper.emitted("edit-protection")?.[0]).toEqual([protection])
    expect(wrapper.emitted("remove-protection")?.[0]).toEqual([protection])
    expect(wrapper.emitted("close")).toHaveLength(1)
  })

  it("sends export and share actions while rendering a completed export", async () => {
    const wrapper = mount(PlaybackActionPanel, {
      props: {
        ...baseProps,
        actionMode: "export",
        cameraProtections: [],
        cameraExports: [exportJob],
        shareExport: exportJob,
        createdShare,
        exportShares: [share]
      }
    })

    await wrapper.find(".playback-action-form").trigger("submit")
    await wrapper.find('button[title="playback.manageShareLink"]').trigger("click")
    await wrapper.find('button[title="playback.deleteExport"]').trigger("click")
    await wrapper.find('.playback-share-editor input[type="password"]').setValue("secret")
    await wrapper.find(".playback-share-editor form").trigger("submit")
    await wrapper.find(".playback-share-created button").trigger("click")
    await wrapper.find('button[title="playback.revokeShare"]').trigger("click")

    expect(wrapper.find('a[title="playback.downloadMp4"]').attributes("href"))
      .toBe("/api/v1/exports/export-a/download")
    expect(wrapper.emitted("save-export")).toHaveLength(1)
    expect(wrapper.emitted("open-share")?.[0]).toEqual([exportJob])
    expect(wrapper.emitted("remove-export")?.[0]).toEqual([exportJob])
    expect(wrapper.emitted("update:sharePassword")?.[0]).toEqual(["secret"])
    expect(wrapper.emitted("save-share")).toHaveLength(1)
    expect(wrapper.emitted("copy-share-link")).toHaveLength(1)
    expect(wrapper.emitted("revoke-share")?.[0]).toEqual([share])
  })
})
