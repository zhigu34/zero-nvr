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
