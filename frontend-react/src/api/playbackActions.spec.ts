import { afterEach, describe, expect, it, vi } from "vitest"

import {
  buildProtectionBody,
  createCameraProtection,
  emptyProtectionForm,
  isProtectionExpired,
  localWindowToIso,
  updateRecordingProtection,
  validateProtectionForm,
  type ProtectionForm,
  type RecordingProtectionView,
} from "./protections"
import {
  canStopTrigger,
  createRecordingTrigger,
  listRecordingTriggers,
  preRollShortfall,
  stopBlockedReason,
  stopRecordingTrigger,
  triggerBlockedReason,
  triggerPersistedAnyway,
  triggerStateTone,
  type RecordingTriggerView,
} from "./recordingTriggers"
import { ApiError } from "./client"

/**
 * The three write-time traps, each of which produces a 4xx and no protection:
 *
 * 1. A naive datetime is a hard 422 `timezone_required` — which is exactly what
 *    a `<input type="datetime-local">` produces.
 * 2. `PUT` is a whole-object replace and `expires_at` is no exception: omitting
 *    it **clears** the expiry.
 * 3. The window is half-open `[start, end)`, so an instant is not a window.
 *
 * And the trigger's 503: the row is committed before the enqueue, so a queue
 * failure means the trigger exists. This is the third instance of the pattern
 * seen in notifications (G-17) and backups.
 */

const NOW = new Date("2026-10-02T12:00:00Z")

function form(overrides: Partial<ProtectionForm> = {}): ProtectionForm {
  return {
    ...emptyProtectionForm(),
    startedAt: "2026-10-02T10:00",
    endedAt: "2026-10-02T11:00",
    reason: "取证",
    ...overrides,
  }
}

function trigger(overrides: Partial<RecordingTriggerView> = {}): RecordingTriggerView {
  return {
    id: "t1",
    camera_id: "c1",
    type: "MANUAL",
    source: "api",
    requested_at: "2026-10-02T12:00:00Z",
    pre_roll_seconds: 5,
    post_roll_seconds: 10,
    pre_roll_status: "complete",
    pre_roll_available_seconds: 5,
    planned_start_at: "2026-10-02T11:59:55Z",
    planned_end_at: null,
    state: "ACTIVE",
    reason: null,
    correlation_id: "abc",
    ...overrides,
  }
}

afterEach(() => vi.unstubAllGlobals())

function capture() {
  const seen: { method: string; url: string; body: unknown; headers?: Record<string, string> }[] = []
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      seen.push({
        method: init?.method ?? "GET",
        url: String(input),
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
        headers: init?.headers as Record<string, string> | undefined,
      })
      return new Response("{}", {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    }),
  )
  return seen
}

describe("localWindowToIso", () => {
  it("always produces an offset-bearing ISO string", () => {
    // A bare "2026-10-02T10:00" is what the server rejects with
    // `timezone_required` (core/time.py:48-65).
    const iso = localWindowToIso("2026-10-02T10:00")
    expect(iso).not.toBeNull()
    expect(iso).toMatch(/Z$|[+-]\d{2}:\d{2}$/)
  })

  it("returns null for blank and unparseable input", () => {
    expect(localWindowToIso("")).toBeNull()
    expect(localWindowToIso("   ")).toBeNull()
    expect(localWindowToIso("not a time")).toBeNull()
  })
})

describe("validateProtectionForm", () => {
  it("accepts a well-formed window", () => {
    expect(validateProtectionForm(form(), NOW)).toEqual([])
  })

  it("rejects an instant, because the window is half-open", () => {
    const errors = validateProtectionForm(
      form({ startedAt: "2026-10-02T10:00", endedAt: "2026-10-02T10:00" }),
      NOW,
    )
    expect(errors.map((e) => e.field)).toContain("endedAt")
  })

  it("rejects an inverted window", () => {
    expect(
      validateProtectionForm(
        form({ startedAt: "2026-10-02T12:00", endedAt: "2026-10-02T10:00" }),
        NOW,
      ).map((e) => e.field),
    ).toContain("endedAt")
  })

  it("rejects a whitespace-only reason, which min_length=1 lets through", () => {
    // The schema accepts " "; the service rejects it after strip.
    expect(validateProtectionForm(form({ reason: "   " }), NOW)[0].field).toBe(
      "reason",
    )
  })

  it("rejects an expiry that is not in the future", () => {
    expect(
      validateProtectionForm(form({ expiresAt: "2026-10-01T00:00" }), NOW)
        .map((e) => e.field),
    ).toContain("expiresAt")
  })

  it("treats an empty expiry as 'never', which is legal", () => {
    expect(validateProtectionForm(form({ expiresAt: "" }), NOW)).toEqual([])
  })

  it("requires both ends of the window", () => {
    const errors = validateProtectionForm(
      { ...emptyProtectionForm(), reason: "x" },
      NOW,
    )
    expect(errors.map((e) => e.field)).toEqual(
      expect.arrayContaining(["startedAt", "endedAt"]),
    )
  })
})

describe("buildProtectionBody", () => {
  it("always sends all four fields, because PUT is a whole replace", () => {
    const body = buildProtectionBody(form())
    expect(Object.keys(body).sort()).toEqual([
      "ended_at",
      "expires_at",
      "reason",
      "started_at",
    ])
  })

  it("sends expires_at: null for 'never', not an omitted key", () => {
    // Omitting it would CLEAR the expiry on a PUT (protection.py:234-237);
    // null is the explicit "never" state.
    expect(buildProtectionBody(form({ expiresAt: "" })).expires_at).toBeNull()
  })

  it("converts every timestamp to an offset-bearing ISO", () => {
    const body = buildProtectionBody(form({ expiresAt: "2026-10-03T00:00" }))
    for (const key of ["started_at", "ended_at", "expires_at"] as const) {
      expect(body[key]).toMatch(/Z$|[+-]\d{2}:\d{2}$/)
    }
  })

  it("trims the reason", () => {
    expect(buildProtectionBody(form({ reason: "  取证  " })).reason).toBe("取证")
  })
})

describe("endpoints", () => {
  it("uses the documented paths", async () => {
    const seen = capture()
    await listRecordingTriggers("c1")
    await createCameraProtection("c1", buildProtectionBody(form()))
    await updateRecordingProtection("p1", buildProtectionBody(form()))
    await stopRecordingTrigger("t1")

    expect(seen.map((c) => `${c.method} ${c.url}`)).toEqual([
      "GET /api/v1/cameras/c1/recording-triggers",
      "POST /api/v1/cameras/c1/recording-protections",
      "PUT /api/v1/recording-protections/p1",
      "POST /api/v1/recording-triggers/t1/stop",
    ])
  })

  it("sends the Idempotency-Key header when given one", async () => {
    const seen = capture()
    await createRecordingTrigger("c1", { reason: "现场" }, "key-1")
    expect(seen[0].headers?.["Idempotency-Key"]).toBe("key-1")
  })
})

describe("triggerPersistedAnyway", () => {
  it("recognises a 503 whose row was already committed", () => {
    const error = new ApiError(503, "recording_task_queue_unavailable", "x", {
      trigger_persisted: true,
      trigger_id: "t9",
    })
    expect(triggerPersistedAnyway(error)).toEqual({ persisted: true, triggerId: "t9" })
  })

  it("treats a plain 503 as a real failure", () => {
    expect(
      triggerPersistedAnyway(new ApiError(503, "recording_task_queue_unavailable", "x", {})),
    ).toBeNull()
    expect(triggerPersistedAnyway(new Error("network"))).toBeNull()
  })
})

describe("trigger state", () => {
  it("an open-ended trigger is the stoppable one", () => {
    expect(canStopTrigger(trigger())).toBe(true)
    expect(canStopTrigger(trigger({ planned_end_at: "2026-10-02T12:10:00Z" }))).toBe(
      false,
    )
  })

  it("only a MANUAL trigger is stoppable at all", () => {
    expect(canStopTrigger(trigger({ type: "EVENT" }))).toBe(false)
    expect(stopBlockedReason(trigger({ type: "EVENT" }))).toContain("手动")
  })

  it("refuses to stop an already-finished trigger", () => {
    expect(stopBlockedReason(trigger({ planned_end_at: "2026-10-02T12:10:00Z" }))).toContain(
      "已结束",
    )
    expect(stopBlockedReason(trigger())).toBeNull()
  })

  it("maps the known states to tones and degrades unknown ones", () => {
    expect(triggerStateTone("ACTIVE")).toBe("degraded")
    expect(triggerStateTone("COMPLETED")).toBe("online")
    expect(triggerStateTone("FAILED")).toBe("offline")
    // `state` is a free string server-side.
    expect(triggerStateTone("SOMETHING_NEW")).toBe("unknown")
  })

  it("reports a short pre-roll in seconds, not milliseconds", () => {
    // The Vue panel divided by 1000 and called the result ms; the field is a
    // float number of seconds.
    const short = preRollShortfall(
      trigger({ pre_roll_seconds: 10, pre_roll_available_seconds: 2.5 }),
    )
    expect(short).toEqual({ requested: 10, available: 2.5, shortfall: 7.5 })
  })

  it("reports no shortfall when pre-roll was never requested", () => {
    expect(preRollShortfall(trigger({ pre_roll_status: "not_requested" }))).toBeNull()
    expect(preRollShortfall(trigger({ pre_roll_seconds: 0 }))).toBeNull()
  })

  it("never reports a negative shortfall when the pre-roll is over-supplied", () => {
    expect(
      preRollShortfall(trigger({ pre_roll_seconds: 5, pre_roll_available_seconds: 9 }))
        ?.shortfall,
    ).toBe(0)
  })
})

describe("triggerBlockedReason", () => {
  it("blocks a schedule-only camera, which the server refuses with 409", () => {
    expect(
      triggerBlockedReason({ enabled: true, event_recording_enabled: false }),
    ).toContain("事件录制")
  })

  it("blocks a disabled policy", () => {
    expect(triggerBlockedReason({ enabled: false, event_recording_enabled: true })).toContain(
      "停用",
    )
  })

  it("allows a fully enabled policy and says nothing while loading", () => {
    expect(
      triggerBlockedReason({ enabled: true, event_recording_enabled: true }),
    ).toBeNull()
    expect(triggerBlockedReason(null)).toContain("读取")
  })
})

describe("isProtectionExpired", () => {
  const view = (expires_at: string | null): RecordingProtectionView => ({
    id: "p1",
    camera_id: "c1",
    started_at: "2026-10-02T10:00:00Z",
    ended_at: "2026-10-02T11:00:00Z",
    reason: "取证",
    created_by: null,
    expires_at,
    created_at: "2026-10-02T09:00:00Z",
    updated_at: "2026-10-02T09:00:00Z",
  })

  it("treats null as never expiring", () => {
    expect(isProtectionExpired(view(null), NOW)).toBe(false)
  })

  it("treats a past expiry as lapsed and a future one as in force", () => {
    expect(isProtectionExpired(view("2026-10-01T00:00:00Z"), NOW)).toBe(true)
    expect(isProtectionExpired(view("2026-10-03T00:00:00Z"), NOW)).toBe(false)
  })
})
