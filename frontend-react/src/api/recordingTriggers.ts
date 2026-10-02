/**
 * Manual recording-trigger contract. Mirrors
 * `backend/app/modules/recordings/{api,triggers,schemas}.py`.
 *
 * ## What a manual trigger actually is
 *
 * It does **not** create a segment. It writes a `RecordingTrigger` row
 * (`type="MANUAL"`, `source="api"`, `state="ACTIVE"`, `correlation_id=uuid4().hex`
 * — `triggers.py:292-307`) and the arbiter keeps the camera recording for the
 * trigger's whole lifetime, **overriding `baseline_mode: "disabled"`**
 * (`arbiter.py:71-86`). A forgotten trigger records indefinitely; that is why
 * the list view and the stop action matter as much as the create one.
 *
 * It never touches `event_filter` — that is only consulted for event triggers
 * (`triggers.py:92-107`). It does **not** bypass the policy *configuration*
 * check: `create_manual` requires `policy.enabled` **and**
 * `policy.event_recording_enabled`, else 409 `event_recording_not_enabled`
 * (`triggers.py:79-88, 266-269`). "Schedule-only" cameras cannot be recorded
 * manually, and the UI should check the policy before offering the button.
 *
 * ## A 503 here means the trigger exists
 *
 * The row is committed before the enqueue, so a queue failure returns 503 with
 * `details.trigger_persisted: true` and `details.trigger_id` (`api.py:984-993`).
 * This is the third instance of the G-17 / G-23 pattern in this codebase; see
 * `triggerPersistedAnyway`.
 *
 * ## Stopping is not stopping
 *
 * `POST /recording-triggers/{id}/stop` sets `planned_end_at = now +
 * post_roll_seconds` and `state = "COMPLETED"` (`triggers.py:368-372`) — the
 * post-roll tail still records. And a second stop is a **silent no-op**: the
 * row comes back unchanged, which also means no audit event and no
 * `schedule_manual_boundary` reschedule (`api.py:1069-1070, 1096-1103`).
 *
 * ## The list is silently capped
 *
 * `GET /cameras/{id}/recording-triggers` hard-caps at 100 rows server-side and
 * exposes neither `limit` nor a cursor (`triggers.py:51-64`). Unlike
 * protections, which are uncapped, an old trigger simply falls off the end.
 * The panel must not imply it is showing everything.
 *
 * ## Out of scope is 404, not 403
 *
 * A trigger or protection belonging to another camera returns 404
 * (`api.py:1054-1060`). A permissions problem therefore masquerades as "not
 * found", which is worth knowing when a list looks empty for the wrong reason.
 */
import { api, ApiError } from "./client"

/* -------------------------------------------------------------------------- */
/* Wire shapes                                                                */
/* -------------------------------------------------------------------------- */

/** The only real `Literal` in this response family (`schemas.py:186`). */
export type PreRollStatus = "not_requested" | "pending" | "complete" | "degraded"

export type RecordingTriggerView = {
  id: string
  camera_id: string
  /** Free string — render unknown values, never switch exhaustively. */
  type: string
  source: string
  /** Server clock at request time; not settable by the client. */
  requested_at: string
  /** Integer seconds, copied from the policy. */
  pre_roll_seconds: number
  post_roll_seconds: number
  pre_roll_status: PreRollStatus
  /** Float seconds — the pre-roll actually available, which can be short. */
  pre_roll_available_seconds: number
  /** In the past: `requested_at - pre_roll_seconds`. */
  planned_start_at: string
  /** `null` while the trigger is open-ended, which is not a failure. */
  planned_end_at: string | null
  /** Free string. `ACTIVE` / `COMPLETED` / `CANCELLED` / `FAILED` in practice. */
  state: string
  reason: string | null
  correlation_id: string
}

export type RecordingTriggerCreate = {
  /** Free text, max 512 characters. */
  reason?: string | null
}

export const TRIGGER_REASON_MAX = 512

/* -------------------------------------------------------------------------- */
/* Endpoints                                                                  */
/* -------------------------------------------------------------------------- */

/** `recording.view`, camera-scoped. Server-capped at 100 rows, no pagination. */
export function listRecordingTriggers(
  cameraId: string,
  signal?: AbortSignal,
) {
  return api.get<RecordingTriggerView[]>(
    `/cameras/${cameraId}/recording-triggers`,
    signal,
  )
}

/**
 * `camera.control`, camera-scoped.
 *
 * `idempotencyKey` maps to the `Idempotency-Key` header (`api.py:915-918`).
 * **Without it, every call creates a new ACTIVE row** (`triggers.py:289-290`),
 * and duplicate manual triggers are indistinguishable in the list. A
 * double-clicked button therefore needs a stable key, the same rule
 * `lib/exportIntent.ts` already encodes for exports.
 */
export function createRecordingTrigger(
  cameraId: string,
  body: RecordingTriggerCreate,
  idempotencyKey?: string,
) {
  return api.post<RecordingTriggerView>(
    `/cameras/${cameraId}/recording-triggers`,
    body,
    undefined,
    idempotencyKey ? { "Idempotency-Key": idempotencyKey } : undefined,
  )
}

/**
 * `camera.control`. Idempotent no-op on an already-stopped trigger; the
 * recording continues through the post-roll tail.
 */
export function stopRecordingTrigger(triggerId: string) {
  return api.post<RecordingTriggerView>(`/recording-triggers/${triggerId}/stop`)
}

/* -------------------------------------------------------------------------- */
/* The 503 that means "it worked"                                            */
/* -------------------------------------------------------------------------- */

/** Same shape as `runPersistedAnyway` in `api/backups.ts`. */
export function triggerPersistedAnyway(error: unknown): {
  persisted: true
  triggerId: string | null
} | null {
  if (!(error instanceof ApiError)) return null
  if (error.details?.trigger_persisted !== true) return null
  const id = error.details.trigger_id
  return { persisted: true, triggerId: typeof id === "string" ? id : null }
}

/* -------------------------------------------------------------------------- */
/* Derived state                                                              */
/* -------------------------------------------------------------------------- */

/** An open-ended trigger is one that can still be stopped. */
export function isTriggerActive(trigger: RecordingTriggerView): boolean {
  return trigger.planned_end_at === null
}

/**
 * How much of the requested pre-roll actually exists.
 *
 * `pre_roll_available_seconds` is a float and routinely comes up short — the
 * camera may have been started moments ago. The Vue panel divided by 1000 and
 * called it milliseconds; it is **seconds**, and rounding it away would report a
 * full pre-roll on a camera that has none.
 */
export function preRollShortfall(
  trigger: RecordingTriggerView,
): { requested: number; available: number; shortfall: number } | null {
  if (trigger.pre_roll_status === "not_requested" || trigger.pre_roll_seconds <= 0) {
    return null
  }
  return {
    requested: trigger.pre_roll_seconds,
    available: trigger.pre_roll_available_seconds,
    shortfall: Math.max(
      0,
      trigger.pre_roll_seconds - trigger.pre_roll_available_seconds,
    ),
  }
}

export const PRE_ROLL_STATUS_LABEL: Record<PreRollStatus, string> = {
  not_requested: "未请求前录",
  pending: "前录进行中",
  complete: "前录完整",
  degraded: "前录不足",
}

export const TRIGGER_STATE_LABEL: Record<string, string> = {
  ACTIVE: "进行中",
  COMPLETED: "已结束",
  CANCELLED: "已取消",
  FAILED: "失败",
}

export type HealthTone = "online" | "degraded" | "offline" | "unknown"

export function triggerStateTone(state: string): HealthTone {
  if (state === "ACTIVE") return "degraded"
  if (state === "COMPLETED") return "online"
  if (state === "FAILED") return "offline"
  if (state === "CANCELLED") return "unknown"
  return "unknown"
}

/**
 * Only an ACTIVE trigger can be stopped, and only a MANUAL one is stoppable at
 * all — 409 `recording_trigger_not_manual` otherwise (`triggers.py:348-356`).
 * A CANCELLED or FAILED trigger is not active either
 * (`recording_trigger_not_active`, `:358-363`).
 */
export function canStopTrigger(trigger: RecordingTriggerView): boolean {
  return trigger.type === "MANUAL" && isTriggerActive(trigger)
}

export function stopBlockedReason(
  trigger: RecordingTriggerView,
): string | null {
  if (trigger.type !== "MANUAL") {
    return "只有手动触发可以手动结束。"
  }
  if (!isTriggerActive(trigger)) {
    return "该触发已结束。"
  }
  return null
}

/** Why the manual-trigger button is unavailable, in operator terms. */
export function triggerBlockedReason(policy: {
  enabled?: boolean
  event_recording_enabled?: boolean
} | null): string | null {
  if (!policy) return "正在读取该机位的录制策略。"
  if (!policy.enabled) {
    return "该机位的录制策略已停用，无法手动触发。"
  }
  if (!policy.event_recording_enabled) {
    return "该机位只按计划录制（未开启事件录制），无法手动触发。"
  }
  return null
}
