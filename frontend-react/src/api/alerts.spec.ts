import { afterEach, describe, expect, it, vi } from "vitest"

import {
  MATCH_KEYS,
  MATCH_KEY_META,
  alertStateLabel,
  createAlertPolicy,
  deleteAlertPolicy,
  listAlertPolicies,
  listAlerts,
  mergeMatch,
  severityLabel,
  unmanagedMatchKeys,
  updateAlertPolicy,
  type AlertMatch,
} from "./alerts"
import { ApiError } from "./client"

/**
 * The load-bearing test in this migration is `mergeMatch`. `PATCH
 * /alert-policies/{id}` replaces `match` wholesale, so an editor that rebuilds
 * the object from its own field list destroys every key it does not know
 * about — and returns 200 while doing it. The Vue screen this replaces did
 * exactly that.
 */

type Call = { url: string; method: string; body: unknown }

function captureFetch(respond?: () => Response) {
  const calls: Call[] = []
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({
        url: String(input),
        method: init?.method ?? "GET",
        body: init?.body ? JSON.parse(String(init.body)) : null,
      })
      return (
        respond?.() ??
        new Response("{}", {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      )
    }),
  )
  return calls
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("mergeMatch", () => {
  it("lets the draft authoritatively replace a known key", () => {
    // `severities` is one of the 12, so the editor owns it: changing one
    // field must not disturb the others, and clearing it must clear it.
    const existing: AlertMatch = { severities: ["critical"], labels: ["car"] }
    expect(mergeMatch(existing, { labels: ["car", "person"], severities: ["critical"] }))
      .toEqual({ severities: ["critical"], labels: ["car", "person"] })
    expect(mergeMatch(existing, { labels: ["car"] })).not.toHaveProperty("severities")
  })

  it("preserves a key added by a future backend release", () => {
    const existing = { labels: ["car"], some_future_key: { nested: true } }
    const merged = mergeMatch(existing, { labels: ["car"] })
    expect(merged.some_future_key).toEqual({ nested: true })
  })

  it("removes a known key the operator cleared", () => {
    const merged = mergeMatch({ labels: ["car"], min_confidence: 0.6 }, {
      labels: [],
      min_confidence: 0.6,
    })
    expect(merged).not.toHaveProperty("labels")
    expect(merged.min_confidence).toBe(0.6)
  })

  it("treats an empty list and a missing key the same, like the backend does", () => {
    // `normalize_match` omits empty lists rather than storing them
    // (`if items: result[key] = items`), so storing `[]` would drift.
    const fromEmpty = mergeMatch({ zones: ["driveway"] }, { zones: [] })
    const fromMissing = mergeMatch({ zones: ["driveway"] }, {})
    expect(fromEmpty).toEqual(fromMissing)
    expect(fromEmpty).not.toHaveProperty("zones")
  })

  it("treats an empty string as unset, which matters for the time window", () => {
    const merged = mergeMatch(
      { time_start: "08:00", time_end: "18:00", timezone: "Asia/Shanghai" },
      { time_start: "09:00", time_end: "", timezone: "Asia/Shanghai" },
    )
    // Clearing one half of the pair is the operator's business; the backend
    // rejects the pair, and the form should show that rather than quietly
    // keeping the old value.
    expect(merged).not.toHaveProperty("time_end")
    expect(merged.time_start).toBe("09:00")
  })

  it("never mutates the object it was given", () => {
    const existing: AlertMatch = { labels: ["car"] }
    mergeMatch(existing, { labels: [] })
    expect(existing).toEqual({ labels: ["car"] })
  })

  it("round-trips a full match unchanged", () => {
    const full: AlertMatch = {
      camera_ids: ["c1"],
      sources: ["frigate"],
      categories: ["person"],
      labels: ["car"],
      zones: ["driveway"],
      min_confidence: 0.7,
      min_duration_seconds: 5,
      severities: ["critical"],
      weekdays: [0, 1, 2],
      time_start: "08:00",
      time_end: "18:00",
      timezone: "Asia/Shanghai",
    }
    expect(mergeMatch(full, full)).toEqual(full)
  })

  it("handles a null existing object for a create", () => {
    expect(mergeMatch(null, { labels: ["car"] })).toEqual({ labels: ["car"] })
    expect(mergeMatch(undefined, {})).toEqual({})
  })
})

describe("unmanagedMatchKeys", () => {
  it("names the keys the form cannot show", () => {
    expect(
      unmanagedMatchKeys({ labels: ["car"], future_key: 1, severities: [] }),
    ).toEqual(["future_key"])
  })

  it("returns nothing for a clean object", () => {
    const clean: AlertMatch = { labels: [], min_confidence: 0.5 }
    expect(unmanagedMatchKeys(clean)).toEqual([])
  })
})

describe("MATCH_KEY_META", () => {
  it("describes every key the backend accepts", () => {
    // A key with no metadata would render as an unlabelled input.
    for (const key of MATCH_KEYS) {
      expect(MATCH_KEY_META[key]).toBeTruthy()
      expect(MATCH_KEY_META[key].label).toBeTruthy()
      expect(MATCH_KEY_META[key].importNote).toBeTruthy()
    }
  })

  it("refuses to offer a copy for zones", () => {
    // The D-2 finding: the two sides read different fields for the same
    // event, so "copy" would produce a rule that looks identical and behaves
    // differently.
    expect(MATCH_KEY_META.zones.importable).toBe(false)
  })

  it("allows a copy only for the two keys that mean the same thing", () => {
    const importable = MATCH_KEYS.filter((k) => MATCH_KEY_META[k].importable)
    expect(importable.sort()).toEqual(["labels", "min_confidence"])
  })
})

describe("wire shapes", () => {
  it("PATCHes the merged match, not the draft", async () => {
    const calls = captureFetch()
    await updateAlertPolicy("p1", {
      match: mergeMatch({ future_key: 1 }, { labels: ["car"] }),
    })
    expect(calls[0].method).toBe("PATCH")
    expect(calls[0].body).toEqual({
      match: { future_key: 1, labels: ["car"] },
    })
  })

  it("uses the snake_case filter names on the alert list", async () => {
    const calls = captureFetch()
    await listAlerts({ cameraId: "c1", state: "OPEN", severity: "critical" })
    expect(calls[0].url).toContain("camera_id=c1")
    expect(calls[0].url).toContain("state=OPEN")
    expect(calls[0].url).toContain("severity=critical")
  })

  it("lists policies as a plain array", async () => {
    const calls = captureFetch(
      () =>
        new Response("[]", {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
    )
    await listAlertPolicies()
    expect(calls[0].url).toBe("/api/v1/alert-policies")
  })

  it("posts and deletes on the policy resource", async () => {
    const calls = captureFetch()
    await createAlertPolicy({ name: "夜间", match: { min_confidence: 0.8 } })
    expect(calls[0].method).toBe("POST")
    await deleteAlertPolicy("p1")
    expect(calls[1].method).toBe("DELETE")
  })

  it("surfaces the 400 the backend raises for an unknown match key", async () => {
    captureFetch(
      () =>
        new Response(
          JSON.stringify({
            error: {
              code: "alert_policy_match_invalid",
              message: "Alert policy contains unsupported match fields.",
            },
          }),
          { status: 400, headers: { "Content-Type": "application/json" } },
        ),
    )
    await expect(
      updateAlertPolicy("p1", { match: { nope: 1 } as AlertMatch }),
    ).rejects.toMatchObject({ code: "alert_policy_match_invalid" })
  })
})

describe("vocabulary", () => {
  it("degrades unknown severities and states to themselves", () => {
    expect(severityLabel("catastrophic")).toBe("catastrophic")
    expect(alertStateLabel("WEIRD")).toBe("WEIRD")
  })
})

describe("ApiError is still the rejection type", () => {
  it("keeps the shared client's error shape", async () => {
    captureFetch(
      () =>
        new Response(
          JSON.stringify({ error: { code: "x", message: "y" } }),
          { status: 409, headers: { "Content-Type": "application/json" } },
        ),
    )
    await expect(listAlertPolicies()).rejects.toBeInstanceOf(ApiError)
  })
})
