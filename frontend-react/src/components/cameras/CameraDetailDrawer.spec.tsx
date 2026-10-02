/**
 * One channel, one surface.
 *
 * The drawer replaced a docked editor that sat beside the table. The test that
 * matters most is therefore not "does a tab render" but "is there exactly one
 * place to change this camera" — a name edited here and a binding edited there
 * is how the two drift apart.
 */
import { fireEvent, screen, waitFor } from "@testing-library/react"
import { describe, expect, it, vi, afterEach } from "vitest"

import { QueryClientProvider } from "@tanstack/react-query"

import { renderWithProviders } from "../../test-utils"
import { ToastProvider } from "../ui/Toast"
import { ConfirmProvider } from "../ui/Confirm"
import type { CameraDetail } from "../../api/cameras"
import { CameraDetailDrawer } from "./CameraDetailDrawer"

function camera(over: Partial<CameraDetail> = {}): CameraDetail {
  return {
    id: "cam-1",
    name: "前门",
    enabled: true,
    maintenance: false,
    retired_at: null,
    location: "一层东侧",
    storage_label: null,
    adapter_type: "onvif",
    time_sync_mode: "monitor",
    ptz_capable: false,
    manufacturer: "海康威视",
    model: "DS-2CD",
    form_factor: "dome",
    ip: "192.168.1.64",
    port: 554,
    rtsp_path: null,
    sub_rtsp_path: null,
    video_codec: "H.264",
    width: 1920,
    height: 1080,
    fps: 25,
    audio_codec: "aac",
    connectivity_status: "online",
    last_probe_at: null,
    last_online_at: null,
    streams: [],
    bindings: [],
    ...over,
  }
}

const HEALTH = {
  camera_id: "cam-1",
  control: { state: "unknown", reason: "awaiting_control_observation", details: {} },
  media: { state: "unknown", reason: "awaiting_media_observation", details: {} },
  recording: { state: "unknown", reason: "awaiting_recording_observation", details: {} },
  events: { state: "unknown", reason: "event_subscription_unobserved", details: {} },
  ptz: { state: "unknown", reason: "awaiting_ptz_observation", details: {} },
  clock: { state: "unknown", reason: "clock_not_measured", details: {} },
}

const CLOCK = {
  camera_id: "cam-1",
  device_id: "dev-1",
  health: "healthy",
  quality: "good",
  sync_mode: "monitor",
  measured_at: "2026-03-04T05:06:07.000Z",
  offset_ms: 12,
  uncertainty_ms: 30,
  rtt_ms: 4,
  device_timezone: "Asia/Shanghai",
  device_time_source: "ntp",
  error_code: null,
}

/** Real payloads per endpoint, so each panel renders rather than erroring. */
function stubEndpoints() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      const body = url.includes("/health")
        ? HEALTH
        : url.includes("/clock")
          ? CLOCK
          : {}
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    }),
  )
}

function renderDrawer(c: CameraDetail = camera()) {
  return renderWithProviders(<CameraDetailDrawer camera={c} onClose={() => {}} />)
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("CameraDetailDrawer", () => {
  it("opens on 概览 and names the channel", () => {
    stubEndpoints()
    renderDrawer()
    expect(screen.getByRole("dialog")).toBeTruthy()
    expect(screen.getByText("前门")).toBeTruthy()
    expect(screen.getByRole("tab", { name: "概览" }).getAttribute("aria-selected")).toBe("true")
  })

  it("hosts the edit form, so a channel has one place to be changed", () => {
    stubEndpoints()
    renderDrawer()
    // The form is the same one the docked panel used to own.
    expect(screen.getByLabelText("名称")).toBeTruthy()
    expect(screen.getByLabelText("位置")).toBeTruthy()
    expect(screen.getByRole("button", { name: "保存机位信息" })).toBeTruthy()
  })

  it("reports the recording gap when a purpose is unbound", () => {
    stubEndpoints()
    // RECORD bound, the other five not — and RECORD unbound is what stops
    // recording, so the callout has to name it rather than just count.
    renderDrawer(
      camera({
        bindings: [
          { purpose: "LIVE_HIGH", stream_profile_id: "p1", selection_mode: "auto" },
        ],
      }),
    )
    expect(screen.getByText("5 个用途未绑定")).toBeTruthy()
    expect(screen.getByText(/录像.*未绑定|未绑定：录像/)).toBeTruthy()
  })

  it("says nothing is bound when nothing is bound", () => {
    stubEndpoints()
    renderDrawer()
    expect(screen.getByText(/还没有任何用途绑定/)).toBeTruthy()
    // "Not bound" is a fact about the channel, not an error, but it does mean
    // nothing records — so the gap still has to be visible.
    expect(screen.getByText("6 个用途未绑定")).toBeTruthy()
  })

  it("switches to the stream, health and clock panels", async () => {
    stubEndpoints()
    renderDrawer()

    fireEvent.click(screen.getByRole("tab", { name: "码流" }))
    expect(screen.getByText("可用媒体配置")).toBeTruthy()
    // Replace-not-merge is the single most destructive thing on this panel.
    expect(screen.getByText("保存是整体替换，不是合并")).toBeTruthy()

    fireEvent.click(screen.getByRole("tab", { name: "健康" }))
    expect(await screen.findByText("能力健康")).toBeTruthy()
    // Six layers, each with its own state — the projection is not a verdict.
    expect(screen.getAllByRole("group", { name: /^健康层/ })).toHaveLength(6)

    fireEvent.click(screen.getByRole("tab", { name: "时钟" }))
    expect(await screen.findByText("时钟偏差")).toBeTruthy()
    // The measured value, not just a section heading.
    expect(screen.getByText(/12/)).toBeTruthy()
  })

  it("returns to 概览 when a different channel is shown", () => {
    stubEndpoints()
    const { rerender, client } = renderDrawer()
    fireEvent.click(screen.getByRole("tab", { name: "健康" }))
    expect(screen.getByRole("tab", { name: "健康" }).getAttribute("aria-selected")).toBe("true")

    // `renderWithProviders` returns a `rerender` that replaces the *element*,
    // not the wrapper, so the providers are re-established by hand here.
    rerender(
      <QueryClientProvider client={client}>
        <ToastProvider>
          <ConfirmProvider>
            <CameraDetailDrawer
              camera={camera({ id: "cam-2", name: "后院" })}
              onClose={() => {}}
            />
          </ConfirmProvider>
        </ToastProvider>
      </QueryClientProvider>,
    )
    // Staying on the previous channel's tab would show the wrong subject.
    expect(screen.getByRole("tab", { name: "概览" }).getAttribute("aria-selected")).toBe("true")
    expect(screen.getByText("后院")).toBeTruthy()
  })

  it("closes on Escape", () => {
    stubEndpoints()
    const onClose = vi.fn()
    renderWithProviders(
      <CameraDetailDrawer camera={camera()} onClose={onClose} />,
    )
    fireEvent.keyDown(window, { key: "Escape" })
    expect(onClose).toHaveBeenCalled()
  })
})
