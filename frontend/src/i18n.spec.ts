import { describe, expect, it } from "vitest"

import { i18n } from "./i18n"

/**
 * Guards the message catalogue against the two defects that motivated this
 * suite:
 *
 *  1. A key referenced from a component but absent from a locale. vue-i18n then
 *     renders the *key path* itself, so an operator sees `storage.mode` where a
 *     column heading belongs.
 *  2. The same defect hidden behind a fallback: `t("storage.mode") || "清理模式"`
 *     never falls back, because `t()` returns the truthy key string.
 *
 * It also pins en/zh parity so a key added to one locale cannot silently fall
 * back to the key path for the other.
 */

// Load the sources through Vite so the spec needs no Node APIs (the app's
// tsconfig only pulls in `vite/client`).
const sources = import.meta.glob(["./**/*.vue", "./**/*.ts"], {
  query: "?raw",
  import: "default",
  eager: true
}) as Record<string, string>

/** Static `t("a.b")` keys. Dynamic `t(`a.${x}`)` keys are resolved at runtime. */
function referencedKeys(): Map<string, string[]> {
  const keys = new Map<string, string[]>()
  for (const [file, text] of Object.entries(sources)) {
    if (file.endsWith(".spec.ts") || file.endsWith("/i18n.ts")) continue
    for (const match of text.matchAll(
      /(?<![A-Za-z0-9_$.])t\(\s*"([a-zA-Z][\w.]*\.[\w.]+)"/g
    )) {
      const key = match[1]
      const where = keys.get(key) ?? []
      where.push(file)
      keys.set(key, where)
    }
  }
  return keys
}

const en = i18n.global.getLocaleMessage("en-US") as Record<string, unknown>
const zh = i18n.global.getLocaleMessage("zh-CN") as Record<string, unknown>

function flatten(obj: Record<string, unknown>, prefix = ""): Set<string> {
  const out = new Set<string>()
  for (const [k, v] of Object.entries(obj)) {
    const path = prefix ? `${prefix}.${k}` : k
    if (v && typeof v === "object") {
      for (const nested of flatten(v as Record<string, unknown>, path)) {
        out.add(nested)
      }
    } else {
      out.add(path)
    }
  }
  return out
}

const enKeys = flatten(en)
const zhKeys = flatten(zh)

describe("i18n catalogue", () => {
  it("resolves every statically referenced key in both locales", () => {
    const missing: string[] = []
    for (const [key, files] of referencedKeys()) {
      if (!enKeys.has(key)) missing.push(`${key} [en] used by ${files[0]}`)
      if (!zhKeys.has(key)) missing.push(`${key} [zh] used by ${files[0]}`)
    }
    expect(missing).toEqual([])
  })

  it("keeps English and Chinese in parity", () => {
    // A key present in only one locale renders the key path for the other.
    expect([...enKeys].filter((k) => !zhKeys.has(k))).toEqual([])
    expect([...zhKeys].filter((k) => !enKeys.has(k))).toEqual([])
  })

  it("keeps the keys the retention table needs", () => {
    // These were the ones actually broken: the header rendered `storage.mode`
    // because t() returns the key when the message is missing.
    expect(en["storage"]).toMatchObject({
      mode: "Cleanup mode",
      webdavRequired: "WebDAV required",
      actions: "Actions"
    })
    expect(zh["storage"]).toMatchObject({
      mode: "清理模式",
      webdavRequired: "WebDAV 强制前置",
      actions: "操作"
    })
  })

  it("has no t() call whose fallback can never fire", () => {
    // `t("missing") || "text"` looks defensive, but t() returns the truthy key,
    // so the fallback is dead code and the untranslated key is shown instead.
    const offenders: string[] = []
    for (const [file, text] of Object.entries(sources)) {
      if (file.endsWith(".spec.ts")) continue
      for (const match of text.matchAll(/t\(\s*"[^"]+"\s*\)\s*\|\|/g)) {
        offenders.push(
          `${file}:${text.slice(0, match.index).split("\n").length}`
        )
      }
    }
    expect(offenders).toEqual([])
  })

  it("translates every gap reason the backend timeline can emit", () => {
    // TimelineGapReason in backend/app/modules/recordings/schemas.py. An
    // unmapped code is not a missing label: PlaybackView falls back to the
    // raw code, so a Chinese operator reads "not scheduled" in the tooltip.
    for (const reason of [
      "not_scheduled",
      "no_event",
      "source_lost",
      "runtime_restart",
      "storage_failure",
      "missing_media",
      "purged",
      "unknown"
    ]) {
      const key = `playback.reasonMap.${reason}`
      expect(enKeys.has(key), key).toBe(true)
      expect(zhKeys.has(key), key).toBe(true)
    }
  })

  it("covers the localised toast messages added for the Chinese-heavy views", () => {
    for (const key of [
      "cameras.toast.probeDone",
      "events.toast.batchAcknowledged",
      "files.toast.segmentLocated",
      "schedules.toast.batchPartial"
    ]) {
      expect(enKeys.has(key)).toBe(true)
      expect(zhKeys.has(key)).toBe(true)
    }
  })
})
