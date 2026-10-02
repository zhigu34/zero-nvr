/**
 * `BindingSummary` 的三态必须分开。
 *
 * ADR-0015 把「通道」和「绑在通道上的设备」拆成两件事。列表这一列是前端在
 * `channel_no` 落地之前唯一能立起这个区分的地方，所以它显示的每一个分支都要
 * 对应契约里真实存在的状态，不能糊。
 */
import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import type { CameraSummary } from "../../api/cameras"
import {
  BindingSummary,
  adapterLabel,
  bindingAddress,
} from "./BindingSummary"

function camera(overrides: Partial<CameraSummary> = {}): CameraSummary {
  return {
    id: "cam-1",
    name: "前门",
    enabled: true,
    maintenance: false,
    retired_at: null,
    location: null,
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
    audio_codec: null,
    connectivity_status: "online",
    last_probe_at: null,
    last_online_at: null,
    ...overrides,
  }
}

describe("adapterLabel", () => {
  it("translates the two known adapters", () => {
    expect(adapterLabel("onvif")).toBe("ONVIF")
    expect(adapterLabel("manual_rtsp")).toBe("手动 RTSP")
  })

  it("passes an unknown adapter through instead of hiding it", () => {
    // A new backend adapter_type must be visible, not silently rendered as a
    // dash that reads like "unbound".
    expect(adapterLabel("rtsp_psk")).toBe("rtsp_psk")
  })

  it("names the null case", () => {
    expect(adapterLabel(null)).toBe("未绑定")
  })
})

describe("bindingAddress", () => {
  it("is null without an address, which is not the same as an unbound channel", () => {
    expect(bindingAddress({ ip: null, port: null })).toBeNull()
  })

  it("falls back to 554 when a cached row lost its port", () => {
    // The backend sets both together (`cameras/api.py:274-276`); this only
    // guards a value cached by an older build.
    expect(bindingAddress({ ip: "10.0.0.9", port: null })).toBe("10.0.0.9:554")
  })
})

describe("BindingSummary", () => {
  it("shows the adapter and the address when bound", () => {
    render(<BindingSummary camera={camera()} />)
    expect(screen.getByText("ONVIF")).toBeTruthy()
    expect(screen.getByText("192.168.1.64:554")).toBeTruthy()
  })

  it("distinguishes an unbound channel from a bound one with no address", () => {
    const { unmount } = render(
      <BindingSummary camera={camera({ adapter_type: null, ip: null })} />,
    )
    expect(screen.getByText("未绑定")).toBeTruthy()
    expect(screen.getByText("通道存在，没有设备")).toBeTruthy()
    // The degraded wording is reserved for the other case; showing it here would
    // report a healthy design state as a misconfiguration.
    expect(screen.queryByText("无启用的地址")).toBeNull()
    unmount()

    render(<BindingSummary camera={camera({ ip: null })} />)
    expect(screen.getByText("无启用的地址")).toBeTruthy()
    expect(screen.getByText("设备记录存在，但没有启用的接入地址")).toBeTruthy()
    expect(screen.queryByText("未绑定")).toBeNull()
  })

  it("lists main and sub paths, and never a duplicate", () => {
    render(
      <BindingSummary
        camera={camera({
          rtsp_path: "/Streaming/Channels/101",
          sub_rtsp_path: "/Streaming/Channels/102",
        })}
      />,
    )
    expect(
      screen.getByText("/Streaming/Channels/101 · /Streaming/Channels/102"),
    ).toBeTruthy()
  })

  it("collapses identical paths to one", () => {
    // The backend already guards this (`cameras/api.py:280`), but a duplicate
    // would render as a visible "a · a".
    render(
      <BindingSummary
        camera={camera({
          rtsp_path: "/live",
          sub_rtsp_path: "/live",
        })}
      />,
    )
    expect(screen.getByText("/live")).toBeTruthy()
  })

  it("omits the path line entirely when the device reports none", () => {
    const { container } = render(<BindingSummary camera={camera()} />)
    expect(container.textContent).toBe("ONVIF192.168.1.64:554")
  })
})
