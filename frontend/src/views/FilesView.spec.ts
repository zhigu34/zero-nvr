import { flushPromises, mount } from "@vue/test-utils"
import { beforeEach, describe, expect, it, vi } from "vitest"

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
  )
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

  it("allows selecting all segments in batch bar", async () => {
    const wrapper = mount(FilesView, {
      global: {
        stubs: {
          UiIcon: true
        }
      }
    })
    await flushPromises()

    const selectAllCheckbox = wrapper.find(".th-check input[type='checkbox']")
    expect(selectAllCheckbox.exists()).toBe(true)

    await selectAllCheckbox.setValue(true)
    await flushPromises()

    // Batch bar should appear
    const batchBar = wrapper.find(".batch-bar")
    expect(batchBar.exists()).toBe(true)
    expect(batchBar.text()).toContain("已勾选")
  })
})
