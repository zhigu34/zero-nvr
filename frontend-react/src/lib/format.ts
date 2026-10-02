/**
 * Display formatting shared across screens.
 *
 * Kept separate from the API modules on purpose: those describe the wire
 * contract and must stay verbatim, while how a timestamp reads on screen is a
 * presentation decision.
 */

export function formatRelative(iso: string | null | undefined): string {
  if (!iso) return "—"
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return "—"
  const diff = Date.now() - then
  if (diff < 0) return "刚刚"
  const sec = Math.floor(diff / 1000)
  if (sec < 60) return `${sec} 秒前`
  const min = Math.floor(sec / 60)
  if (min < 60) return `${min} 分钟前`
  const hour = Math.floor(min / 60)
  if (hour < 24) return `${hour} 小时前`
  const day = Math.floor(hour / 24)
  if (day < 30) return `${day} 天前`
  return new Date(iso).toLocaleDateString("zh-CN")
}

export function formatClock(iso: string | null | undefined): string {
  if (!iso) return "—"
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return "—"
  return d.toLocaleString("zh-CN", { hour12: false })
}

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return "—"
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return "—"
  return d.toLocaleTimeString("zh-CN", { hour12: false })
}

/**
 * Percentages arrive on **two different scales**, and a single unlabelled
 * helper is a trap:
 *
 * - `EventView.confidence` is a 0–1 fraction (so is the `min_confidence`
 *   query parameter).
 * - `StorageTargetTest.used_percent` is 0–100, clamped server-side
 *   (`storage/capacity.py:169` — `min(100.0, max(0.0, used/total*100))`).
 *
 * So the scale is carried in the function name. Passing a 42.5 into the
 * fraction formatter would render "4250%".
 */

/** 0–1 fraction → "83%". For `EventView.confidence`. */
export function formatFraction(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—"
  return `${(value * 100).toFixed(0)}%`
}

/** 0–100 percent → "42%". For `StorageTargetTest.used_percent`. */
export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—"
  return `${value.toFixed(0)}%`
}
