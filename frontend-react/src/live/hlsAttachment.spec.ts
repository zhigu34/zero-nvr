import { describe, expect, it, vi } from "vitest"

import {
  HlsEvents,
  LIVE_HLS_CONFIG,
  LiveHlsAttachment,
  type HlsLike,
} from "./hlsAttachment"

function fakeElement() {
  const el = document.createElement("video")
  // jsdom implements neither of these meaningfully.
  Object.defineProperty(el, "load", { value: vi.fn(), writable: true })
  Object.defineProperty(el, "pause", { value: vi.fn(), writable: true })
  return el
}

function fakeHls() {
  const handlers = new Map<string, (event: unknown) => void>()
  const hls: HlsLike & {
    handlers: typeof handlers
    destroyed: boolean
    emit: (type: string, payload: unknown) => void
  } = {
    handlers,
    destroyed: false,
    on(event, handler) {
      handlers.set(event, handler)
    },
    destroy() {
      hls.destroyed = true
    },
    loadSource: vi.fn(),
    attachMedia: vi.fn(),
    startLoad: vi.fn(),
    stopLoad: vi.fn(),
    recoverMediaError: vi.fn(),
    emit(type, payload) {
      handlers.get(type)?.(payload)
    },
  }
  return hls
}

function setup(options: { useNativeHls?: boolean } = {}) {
  const hls = fakeHls()
  const onFailure = vi.fn()
  const createHls = vi.fn(() => hls)
  const attachment = new LiveHlsAttachment({
    createHls,
    useNativeHls: options.useNativeHls ?? false,
    onFailure,
  })
  return { hls, onFailure, createHls, attachment }
}

describe("LiveHlsAttachment", () => {
  it("attaches through hls.js when the engine needs it", () => {
    const { attachment, hls, createHls } = setup()
    const element = fakeElement()

    attachment.attach(element, "/zlm/zero-nvr/live/hls.m3u8?zn_sig=x")

    expect(createHls).toHaveBeenCalledWith(LIVE_HLS_CONFIG)
    expect(hls.attachMedia).toHaveBeenCalledWith(element)
    expect(hls.loadSource).toHaveBeenCalledWith(
      "/zlm/zero-nvr/live/hls.m3u8?zn_sig=x",
    )
    expect(attachment.getState()).toEqual({ kind: "attached" })
  })

  it("uses a buffer profile suited to a live wall", () => {
    // A deep buffer on a monitoring wall is a liability: the point is to see
    // now, and the back buffer only needs to cover a small seek.
    expect(LIVE_HLS_CONFIG.liveSyncDurationCount).toBeLessThanOrEqual(3)
    expect(LIVE_HLS_CONFIG.maxBufferLength).toBeLessThanOrEqual(30)
  })

  it("delegates to the element when the engine has native HLS", () => {
    const { attachment, createHls } = setup({ useNativeHls: true })
    const element = fakeElement()

    attachment.attach(element, "/zlm/x/hls.m3u8")

    expect(createHls).not.toHaveBeenCalled()
    expect(element.src).toContain("/zlm/x/hls.m3u8")
    expect(attachment.getState()).toEqual({ kind: "attached" })
  })

  it("destroys the previous player before attaching a new source", () => {
    const { attachment, hls } = setup()

    attachment.attach(fakeElement(), "/zlm/first.m3u8")
    attachment.attach(fakeElement(), "/zlm/second.m3u8")

    // Two live hls.js instances on one tile both hold MediaSource handles.
    expect(hls.destroyed).toBe(true)
  })

  it("empties the element on detach so the old source cannot resume", () => {
    const { attachment } = setup()
    const element = fakeElement()

    attachment.attach(element, "/zlm/x/hls.m3u8")
    attachment.detach()

    expect(element.hasAttribute("src")).toBe(false)
    expect(element.pause).toHaveBeenCalled()
    expect(attachment.getState()).toEqual({ kind: "idle" })
  })

  it("ignores a non-fatal error entirely", () => {
    const { attachment, hls } = setup()
    attachment.attach(fakeElement(), "/zlm/x.m3u8")

    hls.emit(HlsEvents.ERROR, { type: "networkError", fatal: false })

    // hls.js emits these during normal segment churn.
    expect(hls.recoverMediaError).not.toHaveBeenCalled()
    expect(attachment.getState()).toEqual({ kind: "attached" })
  })

  it("recovers the decoder on a fatal media error", () => {
    const { attachment, hls } = setup()
    attachment.attach(fakeElement(), "/zlm/x.m3u8")

    hls.emit(HlsEvents.ERROR, { type: "mediaError", fatal: true })

    expect(hls.recoverMediaError).toHaveBeenCalled()
    expect(attachment.getState()).toEqual({ kind: "attached" })
  })

  it("reloads on a fatal network error", () => {
    const { attachment, hls } = setup()
    attachment.attach(fakeElement(), "/zlm/x.m3u8")
    const startLoad = hls.startLoad as unknown as ReturnType<typeof vi.fn>
    startLoad.mockClear()

    hls.emit(HlsEvents.ERROR, { type: "networkError", fatal: true })

    expect(startLoad).toHaveBeenCalled()
    expect(attachment.getState()).toEqual({ kind: "attached" })
  })

  it("rebuilds and reports when the error is unrecognised", () => {
    const { attachment, hls, onFailure } = setup()
    attachment.attach(fakeElement(), "/zlm/x.m3u8")

    hls.emit(HlsEvents.ERROR, { type: "somethingNew", fatal: true })

    expect(hls.destroyed).toBe(true)
    expect(attachment.getState().kind).toBe("failed")
    // A tile must never go quietly dark.
    expect(onFailure).toHaveBeenCalledWith(
      "媒体服务返回了无法识别的错误",
    )
  })

  it("reports a failure when the player cannot even be constructed", () => {
    const onFailure = vi.fn()
    const attachment = new LiveHlsAttachment({
      createHls: () => {
        throw new Error("worker blocked")
      },
      useNativeHls: false,
      onFailure,
    })

    attachment.attach(fakeElement(), "/zlm/x.m3u8")

    expect(attachment.getState()).toEqual({
      kind: "failed",
      reason: "初始化 HLS 播放器失败：worker blocked",
    })
    expect(onFailure).toHaveBeenCalled()
  })

  it("survives a player that throws on destroy", () => {
    const onFailure = vi.fn()
    const attachment = new LiveHlsAttachment({
      createHls: () => ({
        on: vi.fn(),
        destroy: () => {
          throw new Error("already gone")
        },
        loadSource: vi.fn(),
        attachMedia: vi.fn(),
        startLoad: vi.fn(),
        stopLoad: vi.fn(),
        recoverMediaError: vi.fn(),
      }),
      useNativeHls: false,
      onFailure,
    })

    expect(() => {
      attachment.attach(fakeElement(), "/zlm/x.m3u8")
      attachment.detach()
    }).not.toThrow()
    expect(attachment.getState()).toEqual({ kind: "idle" })
  })

  it("does not report a failure when detached during unmount", () => {
    const { attachment, onFailure } = setup()
    attachment.attach(fakeElement(), "/zlm/x.m3u8")

    attachment.detach()

    // Unmounting is not a failure; surfacing it as one would flash an error
    // every time a tile scrolls out of view.
    expect(onFailure).not.toHaveBeenCalled()
  })
})
