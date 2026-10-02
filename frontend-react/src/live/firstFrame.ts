/**
 * The first-frame gate.
 *
 * "Attached" and "playing" are different claims. A tile can hold a perfectly
 * valid HLS attachment and still never show anything: the camera may be
 * pointed at nothing, the profile may be misconfigured, the browser may decode
 * the container to an empty stream. Attaching successfully is therefore not
 * evidence that the operator can see the camera, and a tile that reports
 * "attached" without a frame is a silent black box.
 *
 * This gate resolves on the first of four outcomes so the caller always has
 * something to tell the user.
 */

export type FirstFrameOutcome =
  | { kind: "frame" }
  | { kind: "timeout"; waitedMs: number }
  | { kind: "error"; message: string }
  | { kind: "cancelled" }

export interface FirstFrameElementLike {
  readyState: number
  error: { code?: number; message?: string } | null
  addEventListener(type: string, handler: () => void): void
  removeEventListener(type: string, handler: () => void): void
  requestVideoFrameCallback?: (cb: () => void) => number
  cancelVideoFrameCallback?: (handle: number) => void
}

export interface FirstFrameGateOptions {
  /** How long to wait before declaring the stream dead. */
  timeoutMs: number
  /** Read the element's current readiness; defaults to `readyState >= 2`. */
  isReady?: (element: FirstFrameElementLike) => boolean
}

/** `HTMLMediaElement.HAVE_CURRENT_DATA` */
const HAVE_CURRENT_DATA = 2

export class FirstFrameGate {
  private resolve: ((outcome: FirstFrameOutcome) => void) | null = null
  private timer: ReturnType<typeof setTimeout> | null = null
  private frameHandle: number | null = null
  private settled = false

  private readonly listeners: Array<[string, () => void]> = []
  private readonly onFrameCallback: () => void
  private readonly onProgress: () => void

  constructor(
    private readonly element: FirstFrameElementLike,
    private readonly options: FirstFrameGateOptions,
  ) {
    this.onFrameCallback = () => this.settle({ kind: "frame" })
    this.onProgress = () => {
      if (this.isReady()) this.settle({ kind: "frame" })
    }
  }

  private isReady(): boolean {
    if (this.options.isReady) return this.options.isReady(this.element)
    return this.element.readyState >= HAVE_CURRENT_DATA
  }

  /**
   * Waits for the first painted frame.
   *
   * `requestVideoFrameCallback` is preferred because it fires when a frame is
   * actually *presented*, not when the decoder has buffered something. Where
   * it is unavailable, the readiness check on media events is the fallback —
   * less precise, but it is the difference between working and not working in
   * older engines.
   */
  wait(): Promise<FirstFrameOutcome> {
    this.cancel()
    // `cancel()` marks the previous attempt settled; this one starts over.
    // Without this reset every later settle() would short-circuit on the
    // previous attempt's verdict and the gate would never resolve.
    this.settled = false

    if (this.isReady()) {
      return Promise.resolve({ kind: "frame" })
    }

    const promise = new Promise<FirstFrameOutcome>((resolve) => {
      this.resolve = resolve
    })

    if (typeof this.element.requestVideoFrameCallback === "function") {
      this.frameHandle = this.element.requestVideoFrameCallback(
        this.onFrameCallback,
      )
    } else {
      this.listen("loadeddata", this.onProgress)
      this.listen("canplay", this.onProgress)
      this.listen("playing", this.onProgress)
    }

    this.listen("error", () => {
      this.settle({
        kind: "error",
        message: this.element.error?.message ?? "媒体元素报告解码错误",
      })
    })

    this.timer = setTimeout(() => {
      this.settle({ kind: "timeout", waitedMs: this.options.timeoutMs })
    }, this.options.timeoutMs)

    return promise
  }

  private listen(type: string, handler: () => void): void {
    this.element.addEventListener(type, handler)
    this.listeners.push([type, handler])
  }

  private settle(outcome: FirstFrameOutcome): void {
    if (this.settled) return
    this.settled = true
    this.cleanup()
    this.resolve?.(outcome)
    this.resolve = null
  }

  /** Releases the gate without a verdict — used when the tile unmounts. */
  cancel(): void {
    if (this.settled) return
    this.settled = true
    this.cleanup()
    this.resolve?.({ kind: "cancelled" })
    this.resolve = null
  }

  private cleanup(): void {
    if (this.timer !== null) {
      clearTimeout(this.timer)
      this.timer = null
    }
    if (this.frameHandle !== null && this.element.cancelVideoFrameCallback) {
      this.element.cancelVideoFrameCallback(this.frameHandle)
    }
    this.frameHandle = null
    for (const [type, handler] of this.listeners) {
      this.element.removeEventListener(type, handler)
    }
    this.listeners.length = 0
  }
}
