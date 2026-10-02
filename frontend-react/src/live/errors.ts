/**
 * Classifying why a live tile has no picture.
 *
 * hls.js reports almost everything as "fatal" and leaves recovery to the
 * embedder, so the decision table — retry the network, recover the decoder, or
 * give up — is the part that actually determines whether a tile recovers on
 * its own or needs a human. Getting it wrong in either direction is costly:
 * retrying a corrupt decoder buffer loops forever, while treating a transient
 * network blip as fatal turns a one-second hiccup into a black tile.
 *
 * The classification is kept separate from the hls.js import so it can be
 * tested without a browser, and so the copy that decides *what the operator
 * is told* is not entangled with the copy that decides *what we do next*.
 */

export type HlsErrorKind = "network" | "media" | "other"

export type HlsRecovery =
  /** Restart the load; the manifest or a segment failed to arrive. */
  | { action: "restart" }
  /** Attempt decoder recovery for a corrupted buffer. */
  | { action: "recover_media" }
  /** Non-recoverable in place: tear down and rebuild the whole attachment. */
  | { action: "rebuild" }

export interface HlsErrorLike {
  type: string
  fatal: boolean
  details?: string
}

const NETWORK_TYPES = new Set([
  "networkError",
  "network",
  "NETWORK_ERROR",
])

const MEDIA_TYPES = new Set([
  "mediaError",
  "media",
  "MEDIA_ERROR",
])

export function classifyHlsError(error: HlsErrorLike): HlsErrorKind {
  if (MEDIA_TYPES.has(error.type)) return "media"
  if (NETWORK_TYPES.has(error.type)) return "network"
  return "other"
}

/**
 * A non-fatal error is always recoverable in place — hls.js emits these
 * during normal segment churn and expects the embedder to keep going.
 */
export function planHlsRecovery(error: HlsErrorLike): HlsRecovery {
  const kind = classifyHlsError(error)
  if (!error.fatal) return { action: "restart" }

  switch (kind) {
    case "network":
      return { action: "restart" }
    case "media":
      return { action: "recover_media" }
    case "other":
      return { action: "rebuild" }
  }
}

/* -------------------------------------------------------------------------- */
/* Operator-facing text                                                       */
/* -------------------------------------------------------------------------- */

export interface FailureContext {
  /** The descriptor resolved and a media session exists. */
  hasMediaSession: boolean
  /** The tile produced at least one frame at some point this attempt. */
  everPainted: boolean
  /** HLS keeps failing on a source that is not H.265. */
  isCompatibilitySource?: boolean
}

export function describeStreamFailure(
  kind: HlsErrorKind,
  context: FailureContext,
): string {
  if (!context.hasMediaSession) {
    return "尚未获得播放授权，请检查该机位是否在线"
  }

  switch (kind) {
    case "network":
      return context.everPainted
        ? "画面中断：与媒体服务的连接丢失，正在重试"
        : "无法连接媒体服务，请检查 ZLMediaKit 是否运行"
    case "media":
      return context.isCompatibilitySource
        ? "转码流解码失败"
        : "媒体解码失败，浏览器可能不支持该编码"
    case "other":
      return "播放失败，媒体服务返回了无法识别的错误"
  }
}
