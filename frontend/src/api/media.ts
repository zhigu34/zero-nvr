const LOOPBACK_HOSTS = new Set([
  "localhost",
  "127.0.0.1",
  "::1",
  "[::1]"
])

export function browserMediaUrl(value: string): string {
  if (typeof window === "undefined" || value.startsWith("/")) {
    return value
  }

  try {
    const url = new URL(value)
    const browserHost = window.location.hostname
    if (
      LOOPBACK_HOSTS.has(url.hostname) &&
      !LOOPBACK_HOSTS.has(browserHost)
    ) {
      url.hostname = browserHost
    }
    return url.toString()
  } catch {
    return value
  }
}
