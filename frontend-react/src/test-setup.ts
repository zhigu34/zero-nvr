// jsdom does not implement matchMedia; the theme hook reads it to pick a
// default when nothing is stored yet.
if (!window.matchMedia) {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
}

// TanStack Router's scroll restoration calls window.scrollTo on every
// navigation; jsdom throws "not implemented" for it and floods the output.
window.scrollTo = (() => {}) as typeof window.scrollTo

// jsdom implements HTMLMediaElement as a stub whose load/play/pause raise
// "not implemented". The playback surface calls them on every attach, so the
// noise would bury real assertions. The stubs are inert on purpose: media
// behaviour is covered by the pure modules (master clock, drift, resync) and
// by the transport layer's own tests with an injected player.
if (typeof HTMLMediaElement !== "undefined") {
  HTMLMediaElement.prototype.load = function load() {}
  HTMLMediaElement.prototype.play = function play() {
    return Promise.resolve()
  }
  HTMLMediaElement.prototype.pause = function pause() {}
}
