import { afterEach, describe, expect, it, vi } from "vitest"

import {
  actionGroup,
  actorTypeLabel,
  changedKeys,
  listAuditEvents,
  resultLabel,
  resultTone,
  type AuditEventView,
} from "./audit"

/**
 * Audit actions are dotted strings written at each call site with no enum, and
 * the event carries opaque UUIDs for both actor and camera. The presentation
 * helpers are what stop a wall of entries from being unreadable, and the one
 * they must never do is invent an identity.
 */

afterEach(() => {
  vi.unstubAllGlobals()
})

function event(over: Partial<AuditEventView> = {}): AuditEventView {
  return {
    id: "a1",
    occurred_at: "2026-10-01T00:00:00Z",
    actor_type: "user",
    actor_id: "u1",
    action: "export.create",
    resource_type: "export",
    resource_id: "e1",
    camera_id: "c1",
    request_id: null,
    correlation_id: null,
    source_ip: "10.0.0.1",
    client_info: null,
    result: "SUCCESS",
    reason: null,
    before: null,
    after: null,
    metadata: null,
    ...over,
  }
}

describe("GET /audit query string", () => {
  it("uses the wire aliases from/to, not the python names", async () => {
    const urls: string[] = []
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        urls.push(String(input))
        return new Response(JSON.stringify({ items: [], next_cursor: null }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      }),
    )
    await listAuditEvents({
      from: "2026-10-01T00:00:00Z",
      to: "2026-10-02T00:00:00Z",
      actorId: "u1",
      result: "DENIED",
    })
    expect(urls[0]).toContain("from=2026-10-01T00%3A00%3A00Z")
    expect(urls[0]).toContain("to=2026-10-02T00%3A00%3A00Z")
    expect(urls[0]).toContain("actor_id=u1")
    expect(urls[0]).toContain("result=DENIED")
    expect(urls[0]).not.toContain("from_at")
  })

  it("omits empty filters rather than sending blanks", async () => {
    const urls: string[] = []
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        urls.push(String(input))
        return new Response(JSON.stringify({ items: [], next_cursor: null }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      }),
    )
    await listAuditEvents({ action: "", cameraId: undefined })
    expect(urls[0]).not.toContain("action=")
    expect(urls[0]).not.toContain("camera_id=")
    expect(urls[0]).toContain("limit=100")
  })
})

describe("actionGroup", () => {
  it("groups on the first dotted segment", () => {
    expect(actionGroup("export.create")).toBe("导出")
    expect(actionGroup("export_share.revoke")).toBe("分享链接")
    expect(actionGroup("user.create")).toBe("用户与角色")
  })

  it("files an unknown action under 其他 rather than blanking it", () => {
    // A new backend action must be visible as itself; an empty group reads as
    // "nothing happened".
    expect(actionGroup("telemetry.shipped")).toBe("其他")
  })
})

describe("result vocabulary", () => {
  it("degrades an unknown result to itself", () => {
    expect(resultLabel("WEIRD")).toBe("WEIRD")
    expect(resultTone("WEIRD")).toBe("unknown")
  })

  it("treats DENIED as an error and SUCCESS as fine", () => {
    expect(resultTone("DENIED")).toBe("offline")
    expect(resultTone("SUCCESS")).toBe("online")
  })
})

describe("actorTypeLabel", () => {
  it("passes an unmapped actor type through", () => {
    expect(actorTypeLabel("user")).toBe("用户")
    expect(actorTypeLabel("mystery")).toBe("mystery")
  })
})

describe("changedKeys", () => {
  it("lists only fields that actually differ", () => {
    const keys = changedKeys(
      event({
        before: { name: "旧", enabled: true, untouched: 1 },
        after: { name: "新", enabled: true, untouched: 1 },
      }),
    )
    expect(keys).toEqual(["name"])
  })

  it("treats a missing side as a change", () => {
    expect(changedKeys(event({ before: null, after: { a: 1 } }))).toEqual(["a"])
    expect(changedKeys(event({ before: { a: 1 }, after: null }))).toEqual(["a"])
  })

  it("returns nothing when there are no snapshots at all", () => {
    expect(changedKeys(event())).toEqual([])
  })

  it("compares structurally, so key order does not read as a change", () => {
    expect(changedKeys(event({ before: { a: 1, b: 2 }, after: { b: 2, a: 1 } }))).toEqual(
      [],
    )
  })
})
