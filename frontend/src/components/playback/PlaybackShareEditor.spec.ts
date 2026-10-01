import { mount } from "@vue/test-utils"
import { describe, expect, it, vi } from "vitest"

import type { ExportJob, ExportShare, ExportShareCreated } from "../../api/exports"
import PlaybackShareEditor from "./PlaybackShareEditor.vue"

vi.mock("vue-i18n", () => ({
  useI18n: () => ({ t: (key: string) => key })
}))

const exportJob = {
  id: "export-a",
  start_at: "2026-09-28T00:00:00Z"
} as ExportJob

const createdShare = {
  id: "share-a",
  token: "one-time-token",
  download_path: "/shares/share-a"
} as ExportShareCreated

const share = {
  id: "share-b",
  expires_at: "2026-10-01T00:00:00Z",
  revoked_at: null,
  max_downloads: 3,
  download_count: 1,
  password_protected: true
} as ExportShare

const baseProps = {
  shareExport: exportJob,
  sharePassword: "",
  shareExpiresHours: 24,
  shareMaxDownloads: 0,
  shareSaving: false,
  shareCopied: false,
  createdShare: null as ExportShareCreated | null,
  exportShares: [] as ExportShare[],
  formatTimestamp: (date: Date) => date.toISOString(),
  shareUrl: (item: ExportShareCreated) => `https://example.test${item.download_path}`
}

describe("PlaybackShareEditor", () => {
  it("updates share options and sends save and close actions", async () => {
    const wrapper = mount(PlaybackShareEditor, { props: baseProps })

    await wrapper.find('input[type="password"]').setValue("secret")
    await wrapper.find("select").setValue("72")
    await wrapper.find('input[type="number"]').setValue("5")
    await wrapper.find("form").trigger("submit")
    await wrapper.find('button[title="playback.closeShareEditor"]').trigger("click")

    expect(wrapper.emitted("update:sharePassword")?.[0]).toEqual(["secret"])
    expect(wrapper.emitted("update:shareExpiresHours")?.[0]).toEqual([72])
    expect(wrapper.emitted("update:shareMaxDownloads")?.[0]).toEqual([5])
    expect(wrapper.emitted("save")).toHaveLength(1)
    expect(wrapper.emitted("close")).toHaveLength(1)
  })

  it("shows the one-time URL and existing shares with revoke action", async () => {
    const wrapper = mount(PlaybackShareEditor, {
      props: {
        ...baseProps,
        createdShare,
        exportShares: [share]
      }
    })

    expect(wrapper.find('.playback-share-created input').attributes("value"))
      .toBe("https://example.test/shares/share-a")
    expect(wrapper.text()).toContain("playback.passwordProtected")
    expect(wrapper.text()).toContain("playback.downloadsLimited")

    await wrapper.find(".playback-share-created button").trigger("click")
    await wrapper.find('button[title="playback.revokeShare"]').trigger("click")
    expect(wrapper.emitted("copy")).toHaveLength(1)
    expect(wrapper.emitted("revoke")?.[0]).toEqual([share])
  })
})
