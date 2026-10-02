import { afterEach, describe, expect, it, vi } from "vitest"
import { listEvents, categoryLabel } from "./events"
import { listCameras, normalizeConnectivity } from "./cameras"
import { formatBytes, CAPACITY_LEVEL_LABEL } from "./storage"
import { formatFraction, formatPercent } from "../lib/format"
import { ApiError } from "./client"

/**
 * These assert the wire contract, not the UI. The backend uses parameter
 * names that differ from its Python signature (`confidence` not
 * `min_confidence`, `from`/`to` not `from_at`/`to_at`), and getting one of
 * them wrong produces a silently unfiltered list rather than an error.
 */

function captureFetch() {
  const calls: string[] = []
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      calls.push(String(input))
      return new Response("{}", {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    }),
  )
  return calls
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("GET /events query string", () => {
  it("uses the wire aliases, not the python parameter names", async () => {
    const calls = captureFetch()
    await listEvents({
      from: "2026-10-01T00:00:00Z",
      to: "2026-10-02T00:00:00Z",
      minConfidence: 0.8,
    })
    const url = calls[0]
    expect(url).toContain("from=2026-10-01T00%3A00%3A00Z")
    expect(url).toContain("to=2026-10-02T00%3A00%3A00Z")
    expect(url).toContain("confidence=0.8")
    // The python names must not leak onto the wire.
    expect(url).not.toContain("from_at")
    expect(url).not.toContain("min_confidence")
  })

  it("sends camera_id and the pagination cursor", async () => {
    const calls = captureFetch()
    await listEvents({ cameraId: "cam-1", cursor: "abc", limit: 25 })
    expect(calls[0]).toContain("camera_id=cam-1")
    expect(calls[0]).toContain("cursor=abc")
    expect(calls[0]).toContain("limit=25")
  })

  it("defaults to a limit the backend accepts and never sends page=2", async () => {
    const calls = captureFetch()
    await listEvents()
    expect(calls[0]).toContain("limit=50")
    expect(calls[0]).not.toContain("page=")
  })

  it("omits filters that were not set rather than sending empty strings", async () => {
    const calls = captureFetch()
    await listEvents({ source: "onvif" })
    expect(calls[0]).toContain("source=onvif")
    expect(calls[0]).not.toContain("category=")
    expect(calls[0]).not.toContain("severity=")
  })

  it("can express a zero confidence floor", async () => {
    const calls = captureFetch()
    await listEvents({ minConfidence: 0 })
    expect(calls[0]).toContain("confidence=0")
  })
})

describe("GET /cameras query string", () => {
  it("omits include_retired unless asked", async () => {
    const calls = captureFetch()
    await listCameras()
    expect(calls[0]).toBe("/api/v1/cameras")
  })

  it("sends include_retired=true when requested", async () => {
    const calls = captureFetch()
    await listCameras({ includeRetired: true })
    expect(calls[0]).toBe("/api/v1/cameras?include_retired=true")
  })
})

describe("connectivity normalisation", () => {
  it("passes through the three known values", () => {
    expect(normalizeConnectivity("online")).toBe("online")
    expect(normalizeConnectivity("offline")).toBe("offline")
    expect(normalizeConnectivity("degraded")).toBe("degraded")
  })

  it("degrades an unrecognised value to unknown rather than blank", () => {
    // The backend types connectivity_status as a bare str, not a Literal, so
    // a new value is possible; the UI must not render an empty status cell.
    expect(normalizeConnectivity("flapping")).toBe("unknown")
    expect(normalizeConnectivity("")).toBe("unknown")
    expect(normalizeConnectivity("ONLINE")).toBe("online")
  })
})

describe("error envelope", () => {
  it("surfaces the backend code and message from {error:{...}}", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              error: {
                code: "invalid_credentials",
                message: "Invalid username or password.",
                details: {},
                request_id: "abc-123",
              },
            }),
            { status: 401, headers: { "Content-Type": "application/json" } },
          ),
      ),
    )
    await expect(listEvents()).rejects.toMatchObject({
      name: "ApiError",
      status: 401,
      code: "invalid_credentials",
      message: "Invalid username or password.",
      requestId: "abc-123",
    })
  })

  it("also handles FastAPI's {detail:[...]} validation shape", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              detail: [
                { loc: ["query", "limit"], msg: "must be less than or equal to 200" },
              ],
            }),
            { status: 422, headers: { "Content-Type": "application/json" } },
          ),
      ),
    )
    const err = await listEvents().catch((e) => e as ApiError)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).code).toBe("validation_error")
    expect((err as ApiError).message).toContain("limit")
  })

  it("flags 401 and 403 as auth failures", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response("{}", {
            status: 403,
            headers: { "Content-Type": "application/json" },
          }),
      ),
    )
    const err = await listEvents().catch((e) => e as ApiError)
    expect((err as ApiError).isAuthFailure).toBe(true)
  })
})

describe("storage formatting", () => {
  it("formats byte counts and passes null through", () => {
    expect(formatBytes(0)).toBe("0 B")
    expect(formatBytes(1024)).toBe("1.0 KB")
    expect(formatBytes(null)).toBe("—")
  })

  it("labels every capacity level the backend can return", () => {
    for (const level of ["normal", "warning", "high", "critical"] as const) {
      expect(CAPACITY_LEVEL_LABEL[level]).toBeTruthy()
    }
  })
})

describe("percentage scale safety", () => {
  it("formats a 0-1 confidence as a percentage", () => {
    expect(formatFraction(0.83)).toBe("83%")
    expect(formatFraction(0)).toBe("0%")
    expect(formatFraction(null)).toBe("—")
  })

  it("formats a 0-100 used_percent as a percentage", () => {
    // storage/capacity.py clamps to 0.0–100.0, so this must NOT be
    // multiplied again — 42.5 would otherwise render as "4250%".
    expect(formatPercent(42.5)).toBe("43%")
    expect(formatPercent(100)).toBe("100%")
    expect(formatPercent(null)).toBe("—")
  })

  it("keeps the two scales from being interchangeable", () => {
    // The whole point of splitting them: the same number means different
    // things on the two contracts.
    expect(formatPercent(0.83)).toBe("1%")
    expect(formatFraction(42.5)).toBe("4250%")
  })
})

describe("category labels", () => {
  it("falls back to the raw category for unknown values", () => {
    expect(categoryLabel("person")).toBe("人员")
    expect(categoryLabel("something_new")).toBe("something_new")
  })
})
