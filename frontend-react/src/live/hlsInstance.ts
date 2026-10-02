import Hls from "hls.js"

import { LIVE_HLS_CONFIG, type HlsLike } from "./hlsAttachment"
import { setHlsJsSupportProbe } from "./capabilities"

/**
 * Real hls.js wiring, kept apart from the components that use it.
 *
 * The attachment class takes an injected factory precisely so it can be tested
 * without a browser; this is where the production factory is defined. The
 * import is static rather than lazy because a monitoring wall always needs it,
 * and a dynamic import would only move the failure to the first tile that
 * tries to play.
 */
export function createHlsInstance(
  config: typeof LIVE_HLS_CONFIG = LIVE_HLS_CONFIG,
): HlsLike {
  return new Hls(config as never) as unknown as HlsLike
}

/** Lets capability detection agree with the player we actually construct. */
setHlsJsSupportProbe(() => Hls.isSupported())
