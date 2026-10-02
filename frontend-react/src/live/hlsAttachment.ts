/**
 * Attachment lifecycle for one HLS-backed tile.
 *
 * Deliberately not a React hook: the awkward part of live playback is *when*
 * things get torn down, and that has to be exercisable without rendering a
 * component. The hook in `hooks/useLiveStream.ts` owns only the wiring.
 *
 * Two properties this class is responsible for:
 *
 * 1. **Exactly one owner of the media element.** Attaching a new source
 *    detaches the previous one first, because hls.js keeps its own MediaSource
 *    open and two attachments on one `<video>` leave both half-alive.
 * 2. **No silent black tiles.** Every terminal path produces a classified
 *    failure. A tile that cannot play says why and offers a retry; it does not
 *    just stop.
 */

/** The slice of the hls.js surface this class actually uses. */
export interface HlsLike {
  on(event: string, handler: (event: unknown) => void): void
  destroy(): void
  loadSource(url: string): void
  attachMedia(element: HTMLMediaElement): void
  startLoad(): void
  stopLoad(): void
  recoverMediaError(): void
}

export type HlsAttachmentState =
  | { kind: "idle" }
  | { kind: "attaching" }
  | { kind: "attached" }
  | { kind: "failed"; reason: string }

/**
 * Buffering tuned for a live wall rather than for VOD.
 *
 * `liveSyncDurationCount: 2` keeps the player close to the live edge, which
 * matters more here than a deep buffer: on a monitoring wall a frame that is
 * ten seconds late is useless, and the back buffer exists only so a viewer who
 * scrolls a timeline slightly behind does not hit a wall.
 */
export const LIVE_HLS_CONFIG = {
  lowLatencyMode: true,
  backBufferLength: 12,
  maxBufferLength: 18,
  liveSyncDurationCount: 2,
} as const

export interface LiveHlsAttachmentDeps {
  /** Factory for an hls.js instance; injected so tests need no real player. */
  createHls: (config: typeof LIVE_HLS_CONFIG) => HlsLike
  /** True when the element can play HLS without hls.js (Safari). */
  useNativeHls: boolean
  onFailure?: (message: string) => void
}

export class LiveHlsAttachment {
  private hls: HlsLike | null = null
  private element: HTMLMediaElement | null = null
  private state: HlsAttachmentState = { kind: "idle" }

  constructor(private readonly deps: LiveHlsAttachmentDeps) {}

  getState(): HlsAttachmentState {
    return this.state
  }

  /**
   * Binds `url` to `element`, replacing any previous attachment.
   *
   * When the engine handles HLS natively, hls.js is not involved at all: the
   * URL goes on `element.src` directly. Running both would give the element
   * two competing sources.
   */
  attach(element: HTMLMediaElement, url: string): void {
    this.detach()
    this.element = element
    this.state = { kind: "attaching" }

    if (this.deps.useNativeHls) {
      element.src = url
      element.load()
      this.state = { kind: "attached" }
      return
    }

    try {
      // Constructing hls.js spins up a transmux worker, which a strict CSP
      // can refuse. That has to surface as a tile-level failure, not an
      // exception that takes the surrounding view down with it.
      const hls = this.deps.createHls(LIVE_HLS_CONFIG)
      this.hls = hls

      hls.on(HlsEvents.ERROR, (event) => {
        this.handleError(event as { type?: string; fatal?: boolean })
      })

      hls.attachMedia(element)
      hls.loadSource(url)
      hls.startLoad()
      this.state = { kind: "attached" }
    } catch (cause) {
      this.fail(`初始化 HLS 播放器失败：${describe(cause)}`)
    }
  }

  /**
   * Applies the recovery that hls.js asks for, and escalates when it does not
   * work. A media error that survives one recovery attempt is not a decoder
   * hiccup any more, so the attachment is rebuilt instead of retried forever.
   */
  private handleError(event: { type?: string; fatal?: boolean }): void {
    if (!event.fatal || !this.hls) return

    const type = event.type ?? "otherError"
    const isMedia = /media/i.test(type)
    const isNetwork = /network/i.test(type)

    if (isMedia) {
      try {
        this.hls.recoverMediaError()
        return
      } catch {
        // Fall through to a rebuild: a decoder that cannot be recovered is
        // not going to recover on a second identical attempt.
      }
    }

    if (isNetwork) {
      this.hls.startLoad()
      return
    }

    this.fail("媒体服务返回了无法识别的错误")
  }

  /** Detaches without reporting a failure — used on unmount and re-attach. */
  detach(): void {
    if (this.hls) {
      try {
        this.hls.destroy()
      } catch {
        // A player that throws on destroy is already unusable; the element is
        // being released either way.
      }
      this.hls = null
    }
    if (this.element) {
      this.element.removeAttribute("src")
      // A paused, emptied element, so a later attach does not resume the
      // previous source's audio while the new one negotiates.
      this.element.pause?.()
      this.element.load?.()
      this.element = null
    }
    this.state = { kind: "idle" }
  }

  /** Detaches and records a terminal failure for this attempt. */
  fail(message: string): void {
    this.detach()
    this.state = { kind: "failed", reason: message }
    this.deps.onFailure?.(message)
  }
}

/** hls.js event names, kept as literals so the injection seam stays honest. */
export const HlsEvents = {
  ERROR: "hlsError",
  MANIFEST_PARSED: "hlsManifestParsed",
} as const

function describe(cause: unknown): string {
  if (cause instanceof Error) return cause.message
  if (typeof cause === "string") return cause
  return "未知错误"
}
