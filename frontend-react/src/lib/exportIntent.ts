/**
 * Lifecycle of the `Idempotency-Key` used by `POST /exports`.
 *
 * The key is not decoration. `ExportService.create` hashes it together with
 * `requested_by` and returns the existing job on a repeat
 * (`service.py:107-135`), which is what makes a double-click or a retry after
 * an ambiguous network failure safe instead of a second export. But that same
 * mechanism has a failure mode that is invisible until an operator has waited
 * for a file that never arrives, so the key's lifecycle is written out here
 * rather than minted inline at the call site.
 *
 * ## The failure mode
 *
 * `create_export` commits the job **before** queueing it, and only queues
 * when `created` is true (`api.py:195-225`). So when the task queue is down
 * the response is 503 `export_task_queue_unavailable` with
 * `details.export_persisted = true` and the job is sitting in the database in
 * `PENDING` — but it was never handed to a worker, and nothing will ever
 * pick it up.
 *
 * Retrying that request with the same key returns *that same stranded job*
 * with a 201. The operator sees success, the list shows a queued export, and
 * it stays queued forever. A retry that appears to succeed and silently
 * does nothing is worse than the 503 it was meant to recover from.
 *
 * So the rule this module encodes: **after a persisted-503 the key is
 * retired.** The next submit is a genuinely new export, and the stranded job
 * is surfaced by id so the operator can cancel it explicitly.
 */
import type { ApiError } from "../api/client"
import type { ExportCreate } from "../api/exports"

export type ExportIntent = {
  key: string
  /** What the key was minted for; a change forces a new key. */
  signature: string
}

export function newIdempotencyKey(): string {
  const c = globalThis.crypto
  if (c && typeof c.randomUUID === "function") return c.randomUUID()
  // Older Safari and non-secure origins. Only needs to be unique per user,
  // since the backend scopes the hash with `requested_by`.
  return `k-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`
}

/**
 * Stable description of what the key protects. Normalised so that a cosmetic
 * difference (a default `format` left implicit vs. spelled out) does not read
 * as a changed intent and mint a second export for the same range.
 */
export function intentSignature(body: ExportCreate): string {
  return JSON.stringify([
    body.camera_id,
    body.start_at,
    body.end_at,
    body.format ?? "mp4",
    body.codec_mode ?? "auto",
    body.gap_policy ?? "skip",
  ])
}

/**
 * The key to use for this submit, minting one only when the current intent
 * does not already cover it.
 *
 * Reusing a key across *different* parameters is a 409
 * `idempotency_key_conflict` (`service.py:61-71`), so an unchanged signature
 * is the only safe case for reuse.
 */
export function ensureIntent(
  current: ExportIntent | null,
  body: ExportCreate,
): ExportIntent {
  const signature = intentSignature(body)
  if (current && current.signature === signature) return current
  return { key: newIdempotencyKey(), signature }
}

/**
 * Did the request land, with the job stranded outside the queue?
 *
 * The 503 carries the job id on purpose (`api.py:220-224`) so the operator
 * can find and cancel it — using it is the whole point of the flag existing.
 */
export function strandedExportId(error: unknown): string | null {
  if (!(error instanceof Error)) return null
  const apiError = error as ApiError
  if (apiError.status !== 503) return null
  if (apiError.details?.export_persisted !== true) return null
  const id = apiError.details?.export_id
  return typeof id === "string" && id ? id : null
}

/**
 * Whether a failed submit may be retried with the same key.
 *
 * A 4xx means the request was rejected outright — nothing was created, and
 * the operator has to change something first. A transport failure means the
 * outcome is genuinely unknown, which is the case idempotency exists for. A
 * persisted-503 is neither: the job exists and must not be retried into.
 */
export function retryIsSafe(error: unknown): boolean {
  if (strandedExportId(error)) return false
  if (error instanceof Error) {
    const status = (error as ApiError).status
    if (typeof status === "number") return status >= 500
  }
  // Not an HTTP response at all: the request may or may not have arrived.
  return true
}
