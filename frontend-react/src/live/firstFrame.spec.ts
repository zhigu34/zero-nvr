import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { FirstFrameGate, type FirstFrameElementLike } from "./firstFrame"

class FakeVideo implements FirstFrameElementLike {
  readyState = 0
  error: { code?: number; message?: string } | null = null
  requestVideoFrameCallback?: (cb: () => void) => number
  cancelVideoFrameCallback?: (handle: number) => void
  cancelled: number[] = []

  private handlers = new Map<string, Set<() => void>>()
  private frameCallbacks = new Map<number, () => void>()
  private nextHandle = 1

  addEventListener(type: string, handler: () => void) {
    if (!this.handlers.has(type)) this.handlers.set(type, new Set())
    this.handlers.get(type)!.add(handler)
  }

  removeEventListener(type: string, handler: () => void) {
    this.handlers.get(type)?.delete(handler)
  }

  emit(type: string) {
    for (const handler of this.handlers.get(type) ?? []) handler()
  }

  get listenerCount() {
    let total = 0
    for (const set of this.handlers.values()) total += set.size
    return total
  }

  useVideoFrameCallback() {
    this.requestVideoFrameCallback = (cb) => {
      const handle = this.nextHandle++
      this.frameCallbacks.set(handle, cb)
      return handle
    }
    this.cancelVideoFrameCallback = (handle) => {
      this.cancelled.push(handle)
      this.frameCallbacks.delete(handle)
    }
  }

  presentFrame() {
    const pending = [...this.frameCallbacks.entries()]
    this.frameCallbacks.clear()
    for (const [, cb] of pending) cb()
  }
}

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
})

describe("FirstFrameGate", () => {
  it("resolves immediately when the element already has data", async () => {
    const video = new FakeVideo()
    video.readyState = 4

    const outcome = await new FirstFrameGate(video, {
      timeoutMs: 6_000,
    }).wait()

    expect(outcome).toEqual({ kind: "frame" })
  })

  it("prefers the presented-frame callback", async () => {
    const video = new FakeVideo()
    video.useVideoFrameCallback()
    const gate = new FirstFrameGate(video, { timeoutMs: 6_000 })

    const pending = gate.wait()
    // readyState is still low; only a real presented frame may resolve this.
    expect(video.readyState).toBe(0)
    video.presentFrame()

    expect(await pending).toEqual({ kind: "frame" })
  })

  it("falls back to media events when the frame callback is missing", async () => {
    const video = new FakeVideo()
    const pending = new FirstFrameGate(video, { timeoutMs: 6_000 }).wait()

    // A real browser has already advanced readyState by the time it fires
    // `canplay`; the gate checks it rather than trusting the event name.
    video.readyState = 4
    video.emit("canplay")

    expect(await pending).toEqual({ kind: "frame" })
  })

  it("ignores a progress event fired before data is actually available", async () => {
    const video = new FakeVideo()
    const pending = new FirstFrameGate(video, { timeoutMs: 6_000 }).wait()

    video.readyState = 0
    video.emit("canplay")

    // Still waiting, rather than declaring victory on an empty element.
    let settled = false
    void pending.then(() => {
      settled = true
    })
    await Promise.resolve()
    expect(settled).toBe(false)
  })

  it("declares a timeout instead of waiting forever", async () => {
    const video = new FakeVideo()
    const pending = new FirstFrameGate(video, { timeoutMs: 6_000 }).wait()

    vi.advanceTimersByTimeAsync(6_000)

    // A tile that never paints must say so; silence here is the black box
    // this gate exists to prevent.
    expect(await pending).toEqual({ kind: "timeout", waitedMs: 6_000 })
  })

  it("surfaces a media element error", async () => {
    const video = new FakeVideo()
    const pending = new FirstFrameGate(video, { timeoutMs: 6_000 }).wait()

    video.error = { message: "unsupported codec" }
    video.emit("error")

    expect(await pending).toEqual({
      kind: "error",
      message: "unsupported codec",
    })
  })

  it("supplies a message when the element gives none", async () => {
    const video = new FakeVideo()
    const pending = new FirstFrameGate(video, { timeoutMs: 6_000 }).wait()

    video.emit("error")

    const outcome = await pending
    expect(outcome.kind).toBe("error")
    if (outcome.kind === "error") {
      expect(outcome.message.length).toBeGreaterThan(0)
    }
  })

  it("reports cancellation without treating it as a failure", async () => {
    const video = new FakeVideo()
    const gate = new FirstFrameGate(video, { timeoutMs: 6_000 })
    const pending = gate.wait()

    gate.cancel()

    expect(await pending).toEqual({ kind: "cancelled" })
  })

  it("removes every listener it added", async () => {
    const video = new FakeVideo()
    const gate = new FirstFrameGate(video, { timeoutMs: 6_000 })
    const pending = gate.wait()

    expect(video.listenerCount).toBeGreaterThan(0)
    gate.cancel()
    await pending

    // Leaked listeners on a recycled video element would fire against a gate
    // that has already made up its mind.
    expect(video.listenerCount).toBe(0)
  })

  it("cancels a pending frame callback", async () => {
    const video = new FakeVideo()
    video.useVideoFrameCallback()
    const gate = new FirstFrameGate(video, { timeoutMs: 6_000 })
    const pending = gate.wait()

    gate.cancel()
    await pending

    expect(video.cancelled).toHaveLength(1)
  })

  it("resolves only once", async () => {
    const video = new FakeVideo()
    const gate = new FirstFrameGate(video, { timeoutMs: 6_000 })
    const pending = gate.wait()

    video.readyState = 4
    video.emit("canplay")
    vi.advanceTimersByTimeAsync(6_000)

    expect(await pending).toEqual({ kind: "frame" })
    // A later timeout must not overwrite the verdict.
    expect(await pending).toEqual({ kind: "frame" })
  })

  it("restarts cleanly when reused for a new source", async () => {
    const video = new FakeVideo()
    const gate = new FirstFrameGate(video, { timeoutMs: 6_000 })

    gate.cancel()
    video.readyState = 0

    const pending = gate.wait()
    video.readyState = 4
    video.emit("playing")

    expect(await pending).toEqual({ kind: "frame" })
  })
})
