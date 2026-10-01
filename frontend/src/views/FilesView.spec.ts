import { flushPromises, mount } from "@vue/test-utils"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { createRecordingProtection } from "../api/recordings"
import FilesView from "./FilesView.vue"

const cameraId = "00000000-0000-0000-0000-000000000001"
const mockRouterPush = vi.fn()

vi.mock("vue-router", () => ({
  useRouter: () => ({
    push: mockRouterPush
  }),
  useRoute: () => ({
    query: {
      camera: cameraId
    }
  })
}))

vi.mock("vue-i18n", () => ({
  useI18n: () => ({
    t: (key: string) => key
  })
}))

vi.mock("../api/cameras", () => ({
  listCameras: vi.fn(() =>
    Promise.resolve([
      {
        id: cameraId,
        name: "Lobby Camera",
        enabled: true,
        maintenance: false,
        retired_at: null,
        location: "Lobby",
        storage_label: null,
        adapter_type: "manual_rtsp",
        time_sync_mode: "monitor",
        ptz_capable: false
      }
    ])
  ),
  getCamera: vi.fn(() =>
    Promise.resolve({
      id: cameraId,
      name: "Lobby Camera",
      enabled: true,
      maintenance: false,
      retired_at: null,
      location: "Lobby",
      storage_label: null,
      adapter_type: "manual_rtsp",
      time_sync_mode: "monitor",
      ptz_capable: false,
      streams: [
        {
          id: "stream-1",
          name: "Main",
          role: "record",
          width: 3840,
          height: 2160,
          fps: 25,
          has_audio: true,
          audio_codec: "aac"
        }
      ]
    })
  ),
  verifyCameraStream: vi.fn(() => Promise.resolve({}))
}))

vi.mock("../api/playback", () => ({
  getCameraTimeline: vi.fn(() =>
    Promise.resolve({
      camera_id: cameraId,
      detail: "minute",
      range: {
        start_at: "2026-09-28T00:00:00Z",
        end_at: "2026-09-28T23:59:59Z"
      },
      segments: [
        {
          id: "seg-101",
          playback_ref: "seg-101",
          start_at: "2026-09-28T14:00:00Z",
          end_at: "2026-09-28T14:15:00Z",
          availability: "local"
        },
        {
          id: "seg-102",
          playback_ref: "seg-102",
          start_at: "2026-09-28T14:15:00Z",
          end_at: "2026-09-28T14:30:00Z",
          availability: "remote"
        }
      ],
      recording_ranges: [],
      gaps: [],
      events: []
    })
  ),
  resolveRecordingSegment: vi.fn(() =>
    Promise.resolve({
      status: "playable",
      segment_id: "seg-101",
      segment_start_at: "2026-09-28T14:00:00Z",
      offset_ms: 0,
      transport: "fmp4",
      url: "/zlm/recording.seg-101.mp4",
      expires_at: "2026-09-28T15:00:00Z",
      codec: "h264"
    })
  )
}))

vi.mock("../api/recordings", () => ({
  listRecordingProtections: vi.fn(() => Promise.resolve([])),
  createRecordingProtection: vi.fn(() =>
    Promise.resolve({
      id: "prot-1",
      camera_id: cameraId,
      started_at: "2026-09-28T14:00:00Z",
      ended_at: "2026-09-28T14:15:00Z",
      reason: "Manual lock",
      created_by: null,
      expires_at: null,
      created_at: "2026-09-28T14:00:00Z",
      updated_at: "2026-09-28T14:00:00Z"
    })
  ),
  deleteRecordingProtection: vi.fn(() => Promise.resolve()),
  listCameraRecordings: vi.fn(() =>
    Promise.resolve({
      items: [
        {
          id: "seg-101",
          camera_id: cameraId,
          start_at: "2026-09-28T14:00:00Z",
          end_at: "2026-09-28T14:15:00Z",
          size_bytes: 125829120,
          availability: "local",
          storage_target_id: "local-pool",
          codec: "h264",
          container: "mp4"
        },
        {
          id: "seg-102",
          camera_id: cameraId,
          start_at: "2026-09-28T14:15:00Z",
          end_at: "2026-09-28T14:30:00Z",
          size_bytes: 125829120,
          availability: "remote",
          storage_target_id: "cloud-pool",
          codec: "h265",
          container: "mp4"
        }
      ],
      next_cursor: null
    })
  )
}))

describe("FilesView recording files and 288-cell heatmap", () => {
  beforeEach(() => {
    mockRouterPush.mockClear()
    vi.mocked(createRecordingProtection).mockClear()
  })

  it("renders 288 heatmap cells and displays segments table", async () => {
    const wrapper = mount(FilesView, {
      global: {
        stubs: {
          UiIcon: true
        }
      }
    })
    await flushPromises()

    // Verify 288 cells exist
    const heatCells = wrapper.findAll(".heat-cell")
    expect(heatCells).toHaveLength(288)

    // Verify table rows
    const rows = wrapper.findAll(".files-table tbody tr")
    expect(rows.length).toBeGreaterThanOrEqual(2)

    // Inspector card displays active segment facts
    expect(wrapper.find(".inspector-filename").text()).toContain("rec_")
  })

  it("selects the nearest segment when a heatmap slot is clicked", async () => {
    const wrapper = mount(FilesView, {
      global: { stubs: { UiIcon: true } }
    })
    await flushPromises()

    const secondStart = new Date("2026-09-28T14:15:00Z")
    const binIndex = secondStart.getHours() * 12 + Math.floor(secondStart.getMinutes() / 5)
    const cell = wrapper.findAll(".heat-cell")[binIndex]
    await cell.trigger("click")
    await flushPromises()

    expect(cell.classes()).toContain("active")
    expect(wrapper.find(".inspector-filename").text()).toBe(
      wrapper.findAll(".files-table tbody tr")[1].find(".file-name-sub").text()
    )
  })

  it("advances to the next segment when preview playback ends", async () => {
    const wrapper = mount(FilesView, {
      global: { stubs: { UiIcon: true } }
    })
    await flushPromises()

    const video = wrapper.find("video.stage-video")
    expect(video.exists()).toBe(true)
    await video.trigger("ended")
    await flushPromises()

    expect(wrapper.find(".inspector-filename").text()).toBe(
      wrapper.findAll(".files-table tbody tr")[1].find(".file-name-sub").text()
    )
  })

  it("updates the inspector and opens playback from a table row", async () => {
    const wrapper = mount(FilesView, {
      global: { stubs: { UiIcon: true } }
    })
    await flushPromises()

    const rows = wrapper.findAll(".files-table tbody tr")
    expect(rows).toHaveLength(2)
    await rows[1].trigger("click")
    await flushPromises()
    expect(rows[1].classes()).toContain("tr--active")
    expect(wrapper.find(".inspector-filename").text()).toBe(rows[1].find(".file-name-sub").text())

    await rows[1].trigger("dblclick")
    expect(mockRouterPush).toHaveBeenCalledWith(
      expect.objectContaining({ path: "/playback", query: expect.objectContaining({ camera: cameraId }) })
    )
  })

  it("jumps to playback when clicking timeline jump button", async () => {
    const wrapper = mount(FilesView, {
      global: {
        stubs: {
          UiIcon: true
        }
      }
    })
    await flushPromises()

    const jumpBtn = wrapper.find(".action-btn--primary")
    expect(jumpBtn.exists()).toBe(true)
    await jumpBtn.trigger("click")

    expect(mockRouterPush).toHaveBeenCalledWith(
      expect.objectContaining({
        path: "/playback",
        query: expect.objectContaining({
          camera: cameraId
        })
      })
    )
  })

  it("locks the selected segment through the recording API", async () => {
    const wrapper = mount(FilesView, {
      global: { stubs: { UiIcon: true } }
    })
    await flushPromises()

    await wrapper.findAll(".inspector-action-buttons .action-btn")[2].trigger("click")
    await flushPromises()

    expect(createRecordingProtection).toHaveBeenCalledWith(
      cameraId,
      expect.objectContaining({
        started_at: "2026-09-28T14:00:00.000Z",
        ended_at: "2026-09-28T14:15:00.000Z",
        reason: "Manual lock via Files Console"
      })
    )
    expect(wrapper.find(".metadata-rows").text()).toContain("已加锁保护")
  })

  it("does not offer batch actions that have no backend implementation", async () => {
    // The batch bar used to expose export / lock / archive / delete buttons
    // whose handlers only displayed a success toast: no request was sent and
    // there is no batch endpoint to send it to. They were removed rather than
    // left to mislead operators. Re-introducing the UI requires the API first,
    // so this guards against a silent comeback.
    const wrapper = mount(FilesView, {
      global: {
        stubs: {
          UiIcon: true
        }
      }
    })
    await flushPromises()

    expect(wrapper.find(".batch-bar").exists()).toBe(false)
    expect(wrapper.find(".th-check").exists()).toBe(false)

    const actionLabels = wrapper.findAll(".batch-action-btn").map((b) => b.text())
    expect(actionLabels).toEqual([])
  })

  it("opens the month calendar and closes it after selecting a day", async () => {
    const wrapper = mount(FilesView, {
      global: { stubs: { UiIcon: true } }
    })
    await flushPromises()

    await wrapper.find(".calendar-toggle-btn").trigger("click")
    expect(wrapper.find(".files-month-calendar").exists()).toBe(true)
    expect(wrapper.findAll(".cal-day-cell").length).toBeGreaterThanOrEqual(35)

    await wrapper.findAll(".month-nav-btn")[0].trigger("click")
    expect(wrapper.find(".month-title").text()).toContain("月")

    await wrapper.find(".cal-day-cell:not(.cal-day-cell--other)").trigger("click")
    expect(wrapper.find(".files-month-calendar").exists()).toBe(false)
  })
})
