import { afterEach, describe, expect, it, vi } from "vitest"

import {
  createExport,
  exportDownloadPath,
  exportStateLabel,
  exportStateTone,
  isSettled,
  listExports,
  sharedExportPath,
  type ExportShareCreated,
} from "./exports"
import { ApiError } from "./client"

/**
 * The wire contract for exports. The header and the query aliases are the
 * parts that fail silently — a missing `Idempotency-Key` still creates an
 * export, it just creates a second one on every retry.
 */

type Call = { url: string; init: RequestInit | undefined }

function captureFetch(
  respond: (call: Call) => Response = () =>
    new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } }),
) {
  const calls: Call[] = []
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const call = { url: String(input), init }
      calls.push(call)
      return respond(call)
    }),
  )
  return calls
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("POST /exports", () => {
  it("sends the idempotency key as a header, not in the body", async () => {
    const calls = captureFetch()
    await createExport(
      { camera_id: "c1", start_at: "2026-10-01T02:00:00.000Z", end_at: "2026-10-01T03:00:00.000Z" },
      "key-123",
    )
    const headers = calls[0].init?.headers as Record<string, string>
    expect(headers["Idempotency-Key"]).toBe("key-123")
    expect(JSON.parse(String(calls[0].init?.body))).not.toHaveProperty(
      "idempotency_key",
    )
  })

  it("keeps the session cookie on the request", async () => {
    const calls = captureFetch()
    await createExport(
      { camera_id: "c1", start_at: "a", end_at: "b" },
      "k",
    )
    expect(calls[0].init?.credentials).toBe("include")
  })

  it("maps the error envelope, keeping code and details", async () => {
    captureFetch(
      () =>
        new Response(
          JSON.stringify({
            error: {
              code: "export_task_queue_unavailable",
              message: "Export was saved but background processing could not be queued.",
              details: { export_persisted: true, export_id: "exp-7" },
              request_id: "req-9",
            },
          }),
          { status: 503, headers: { "Content-Type": "application/json" } },
        ),
    )
    await expect(
      createExport({ camera_id: "c1", start_at: "a", end_at: "b" }, "k"),
    ).rejects.toMatchObject({
      status: 503,
      code: "export_task_queue_unavailable",
      details: { export_persisted: true, export_id: "exp-7" },
      requestId: "req-9",
    })
  })

  it("maps a FastAPI validation body without losing the field name", async () => {
    captureFetch(
      () =>
        new Response(
          JSON.stringify({
            detail: [
              { loc: ["body", "end_at"], msg: "Input should be a valid datetime" },
            ],
          }),
          { status: 422, headers: { "Content-Type": "application/json" } },
        ),
    )
    const error = await createExport(
      { camera_id: "c1", start_at: "a", end_at: "b" },
      "k",
    ).catch((e: unknown) => e as ApiError)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).code).toBe("validation_error")
    expect((error as ApiError).message).toContain("end_at")
  })
})

describe("GET /exports", () => {
  it("omits state when unfiltered rather than sending an empty one", async () => {
    const calls = captureFetch()
    await listExports()
    expect(calls[0].url).toContain("limit=50")
    expect(calls[0].url).not.toContain("state=")
  })

  it("passes state and cursor through", async () => {
    const calls = captureFetch()
    await listExports({ state: "COMPLETED", cursor: "abc", limit: 10 })
    expect(calls[0].url).toContain("state=COMPLETED")
    expect(calls[0].url).toContain("cursor=abc")
    expect(calls[0].url).toContain("limit=10")
  })
})

describe("paths", () => {
  it("keeps the authenticated download separate from the public one", () => {
    expect(exportDownloadPath("exp-1")).toBe("/api/v1/exports/exp-1/download")
    expect(sharedExportPath("tok-1")).toBe(
      "/api/v1/shared/exports/tok-1/download",
    )
  })
})

describe("state vocabulary", () => {
  it("labels every state the CHECK constraint allows", () => {
    for (const state of [
      "PENDING",
      "RUNNING",
      "COMPLETED",
      "FAILED",
      "CANCELLED",
      "EXPIRED",
    ]) {
      expect(exportStateLabel(state)).not.toBe(state)
    }
  })

  it("passes an unknown state through rather than blanking it", () => {
    // A state added by a newer backend must be visible as itself; rendering an
    // empty cell would read as "no state" rather than "one we do not know".
    expect(exportStateLabel("SOMETHING_NEW")).toBe("SOMETHING_NEW")
    expect(exportStateTone("SOMETHING_NEW")).toBe("unknown")
  })

  it("treats only PENDING and RUNNING as still moving", () => {
    expect(isSettled("PENDING")).toBe(false)
    expect(isSettled("RUNNING")).toBe(false)
    for (const state of ["COMPLETED", "FAILED", "CANCELLED", "EXPIRED"]) {
      expect(isSettled(state)).toBe(true)
    }
  })
})

describe("ExportShareCreated", () => {
  it("carries the token and the public path, and the token is the whole secret", () => {
    const share: ExportShareCreated = {
      id: "s1",
      export_id: "e1",
      expires_at: "2026-10-03T00:00:00.000Z",
      revoked_at: null,
      max_downloads: null,
      download_count: 0,
      last_download_at: null,
      password_protected: false,
      created_at: "2026-10-01T00:00:00.000Z",
      token: "tok",
      download_path: sharedExportPath("tok"),
    }
    expect(share.download_path).toContain(share.token)
  })
})
