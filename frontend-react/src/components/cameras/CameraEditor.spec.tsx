import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { CameraEditor } from "./CameraEditor"
import { ToastProvider } from "../ui/Toast"
import type { CameraDetail } from "../../api/cameras"

/**
 * The editor is mostly about fields the backend will *not* accept. These
 * assert that the form refuses to offer them, rather than offering them and
 * letting the values disappear on the next reload.
 */

const BASE: CameraDetail = {
  id: "cam-1",
  name: "前门人行入口",
  enabled: true,
  maintenance: false,
  manufacturer: null,
  model: null,
  form_factor: "box",
  location: "一层东侧",
  storage_label: null,
  adapter_type: "manual_rtsp",
  time_sync_mode: "ignore",
  ptz_capable: false,
  ip: "192.168.1.50",
  port: 554,
  rtsp_path: "/stream",
  sub_rtsp_path: null,
  video_codec: "h264",
  width: 1920,
  height: 1080,
  fps: 25,
  audio_codec: null,
  connectivity_status: "online",
  retired_at: null,
  last_probe_at: null,
  last_online_at: null,
  streams: [],
  bindings: [],
}

let patched: Record<string, unknown> | null = null

beforeEach(() => {
  patched = null
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (init?.method === "PATCH") {
        patched = init.body ? JSON.parse(String(init.body)) : {}
        return new Response(JSON.stringify(BASE), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      }
      return new Response(JSON.stringify(url.includes("/cameras/") ? BASE : []), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    }),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

function renderEditor(camera: CameraDetail = BASE) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <CameraEditor camera={camera} onClose={() => {}} />
      </ToastProvider>
    </QueryClientProvider>,
  )
}

describe("CameraEditor", () => {
  it("offers editable identity fields", () => {
    renderEditor()
    expect((screen.getByLabelText("名称") as HTMLInputElement).value).toBe(
      "前门人行入口",
    )
    expect((screen.getByLabelText("位置") as HTMLInputElement).value).toBe(
      "一层东侧",
    )
  })

  it("does not offer an RTSP field, because PATCH cannot change it", () => {
    renderEditor()
    // Offering a field the endpoint ignores would look like it saved.
    expect(screen.queryByLabelText(/RTSP 地址/)).toBeNull()
    expect(screen.getByText("RTSP 地址不可在此修改")).toBeTruthy()
  })

  it("does not offer manufacturer or model, which would be silently dropped", () => {
    renderEditor()
    expect(screen.queryByLabelText("厂商")).toBeNull()
    expect(screen.queryByLabelText("型号")).toBeNull()
    expect(screen.getByText("厂商与型号无法编辑")).toBeTruthy()
  })

  it("offers only ignore for a manual RTSP camera's time sync", () => {
    renderEditor()
    const select = screen.getByLabelText("时钟同步") as HTMLSelectElement
    expect(
      Array.from(select.options).map((option) => option.value),
    ).toEqual(["ignore"])
  })

  it("offers all three modes for an ONVIF camera", () => {
    renderEditor({ ...BASE, adapter_type: "onvif", time_sync_mode: "monitor" })
    const select = screen.getByLabelText("时钟同步") as HTMLSelectElement
    expect(
      Array.from(select.options).map((option) => option.value),
    ).toEqual(["manage_ntp", "monitor", "ignore"])
  })

  it("sends only the fields the endpoint accepts", async () => {
    renderEditor()
    fireEvent.change(screen.getByLabelText("名称"), {
      target: { value: "前门（改）" },
    })
    fireEvent.click(screen.getByRole("button", { name: "保存" }))

    await waitFor(() => {
      expect(patched).not.toBeNull()
    })
    expect(patched).toMatchObject({ name: "前门（改）" })
    // Never present: the backend would accept and discard them.
    expect(patched).not.toHaveProperty("manufacturer")
    expect(patched).not.toHaveProperty("model")
    expect(patched).not.toHaveProperty("form_factor")
  })

  it("sends an explicit null to clear a field", async () => {
    renderEditor()
    fireEvent.change(screen.getByLabelText("位置"), { target: { value: "" } })
    fireEvent.click(screen.getByRole("button", { name: "保存" }))

    await waitFor(() => {
      expect(patched).not.toBeNull()
    })
    // `exclude_unset` means omitting the key would leave the old value in
    // place; clearing requires an explicit null.
    expect(patched).toMatchObject({ location: null })
  })

  it("blocks saving while the name is invalid", () => {
    renderEditor()
    fireEvent.change(screen.getByLabelText("名称"), { target: { value: "  " } })

    const save = screen.getByRole("button", { name: "保存" }) as HTMLButtonElement
    expect(save.disabled).toBe(true)
    expect(screen.getByText("机位名称不能为空")).toBeTruthy()
  })

  it("explains the restore behaviour on a retired camera", () => {
    renderEditor({ ...BASE, retired_at: "2026-10-01T00:00:00Z" })
    expect(screen.getByText("机位已退役")).toBeTruthy()
    expect(screen.getByText(/恢复后机位仍为停用状态/)).toBeTruthy()
  })

  it("lists existing stream bindings read-only", () => {
    renderEditor({
      ...BASE,
      bindings: [
        { purpose: "RECORD", stream_profile_id: "p1", selection_mode: "manual" },
        { purpose: "LIVE_LOW", stream_profile_id: null, selection_mode: "auto" },
      ],
    })
    expect(screen.getByText("当前码流用途绑定")).toBeTruthy()
    expect(screen.getByText("未绑定")).toBeTruthy()
  })

  it("re-seeds when a different camera is shown", () => {
    const { rerender } = renderEditor()
    rerender(
      <QueryClientProvider client={new QueryClient()}>
        <ToastProvider>
          <CameraEditor
            camera={{ ...BASE, id: "cam-2", name: "后院周界", location: null }}
            onClose={() => {}}
          />
        </ToastProvider>
      </QueryClientProvider>,
    )
    expect((screen.getByLabelText("名称") as HTMLInputElement).value).toBe(
      "后院周界",
    )
  })
})
