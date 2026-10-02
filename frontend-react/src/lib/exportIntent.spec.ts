import { describe, expect, it } from "vitest"

import { ApiError } from "../api/client"
import {
  ensureIntent,
  intentSignature,
  newIdempotencyKey,
  retryIsSafe,
  strandedExportId,
  type ExportIntent,
} from "./exportIntent"
import type { ExportCreate } from "../api/exports"

/**
 * The scenario these exist for: a 503 that says the job was saved but not
 * queued. Retrying it with the same key returns that same stuck job with a
 * 201, so the operator is told the export started when it never will. If
 * `retryIsSafe` ever answers "yes" for that error, the UI loses the only
 * warning it gets.
 */

const BODY: ExportCreate = {
  camera_id: "cam-1",
  start_at: "2026-10-01T02:00:00.000Z",
  end_at: "2026-10-01T03:00:00.000Z",
  codec_mode: "auto",
  gap_policy: "skip",
}

const STRANDED = new ApiError(503, "export_task_queue_unavailable", "queued", {
  export_persisted: true,
  export_id: "export-9",
})

describe("intentSignature", () => {
  it("ignores defaults the caller left implicit", () => {
    expect(intentSignature({ ...BODY, format: undefined, codec_mode: undefined })).toBe(
      intentSignature({ ...BODY, format: "mp4", codec_mode: "auto" }),
    )
  })

  it("changes when any meaningful field changes", () => {
    const base = intentSignature(BODY)
    expect(intentSignature({ ...BODY, end_at: "2026-10-01T04:00:00.000Z" })).not.toBe(base)
    expect(intentSignature({ ...BODY, gap_policy: "fail" })).not.toBe(base)
    expect(intentSignature({ ...BODY, camera_id: "cam-2" })).not.toBe(base)
  })
})

describe("ensureIntent", () => {
  it("mints a key for a first submit", () => {
    const intent = ensureIntent(null, BODY)
    expect(intent.key).toBeTruthy()
    expect(intent.signature).toBe(intentSignature(BODY))
  })

  it("reuses the key for a retry of the same intent", () => {
    const first = ensureIntent(null, BODY)
    const second = ensureIntent(first, { ...BODY })
    expect(second).toBe(first)
  })

  it("mints a new key when the operator edits the range", () => {
    const first = ensureIntent(null, BODY)
    const second = ensureIntent(first, { ...BODY, end_at: "2026-10-01T05:00:00.000Z" })
    expect(second.key).not.toBe(first.key)
  })

  it("mints a new key after a success, so the same range can be re-exported", () => {
    // Retiring the intent on success is what keeps idempotency from turning
    // into "this range can only ever be exported once".
    const first = ensureIntent(null, BODY)
    expect(ensureIntent(null, BODY).key).not.toBe(first.key)
  })

  it("never returns the same key for two different requests", () => {
    const a = ensureIntent(null, BODY)
    const b = ensureIntent(a, { ...BODY, codec_mode: "h264" })
    expect(b.key).not.toBe(a.key)
  })
})

describe("newIdempotencyKey", () => {
  it("produces distinct values", () => {
    const keys = new Set(Array.from({ length: 200 }, newIdempotencyKey))
    expect(keys.size).toBe(200)
  })

  it("stays inside the backend's 256-character limit", () => {
    expect(newIdempotencyKey().length).toBeLessThanOrEqual(256)
  })
})

describe("strandedExportId", () => {
  it("reads the job id out of a persisted-503", () => {
    expect(strandedExportId(STRANDED)).toBe("export-9")
  })

  it("ignores a 503 that did not persist anything", () => {
    expect(
      strandedExportId(new ApiError(503, "boom", "no", { export_persisted: false })),
    ).toBeNull()
    expect(strandedExportId(new ApiError(503, "boom", "no", null))).toBeNull()
  })

  it("ignores other statuses carrying the same details", () => {
    expect(
      strandedExportId(
        new ApiError(500, "boom", "no", { export_persisted: true, export_id: "x" }),
      ),
    ).toBeNull()
  })

  it("ignores non-errors", () => {
    expect(strandedExportId(new Error("network"))).toBeNull()
    expect(strandedExportId("nope")).toBeNull()
    expect(strandedExportId(null)).toBeNull()
  })
})

describe("retryIsSafe", () => {
  it("refuses a retry into a stranded job", () => {
    expect(retryIsSafe(STRANDED)).toBe(false)
  })

  it("allows a transport failure, which is what idempotency is for", () => {
    expect(retryIsSafe(new TypeError("Failed to fetch"))).toBe(true)
  })

  it("refuses a 4xx, because nothing was created and the input is wrong", () => {
    expect(retryIsSafe(new ApiError(400, "export_range_too_large", "too big"))).toBe(
      false,
    )
    expect(retryIsSafe(new ApiError(422, "timezone_required", "no tz"))).toBe(false)
  })

  it("allows a 5xx that persisted nothing", () => {
    expect(retryIsSafe(new ApiError(500, "boom", "no", null))).toBe(true)
  })
})

describe("interaction with the backend's conflict rule", () => {
  it("never reuses a key across differing parameters, which would be a 409", () => {
    // `service.py:61-71` rejects a reused key whose request differs. Walking
    // the same sequence the UI walks must stay clear of that path.
    let intent: ExportIntent | null = null
    intent = ensureIntent(intent, BODY)
    const sameKey = intent.key
    intent = ensureIntent(intent, { ...BODY, codec_mode: "h264" })
    expect(intent.key).not.toBe(sameKey)
    intent = ensureIntent(intent, BODY)
    expect(intent.key).not.toBe(sameKey)
  })
})
