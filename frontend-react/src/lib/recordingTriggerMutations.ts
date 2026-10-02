import {
  createRecordingTrigger,
  stopRecordingTrigger,
  triggerPersistedAnyway,
  type RecordingTriggerCreate,
} from "../api/recordingTriggers"
import { RECORDINGS } from "./queries"
import { useSave } from "./save"

/**
 * ## The idempotency key has to outlive the mutation
 *
 * `POST /cameras/{id}/recording-triggers` creates a new ACTIVE row on every
 * call unless an `Idempotency-Key` header is present (`triggers.py:289-290`).
 * Two duplicate manual triggers are indistinguishable in the list, both keep
 * the camera recording, and a double-clicked button is the obvious way to get
 * one. The same four rules as `lib/exportIntent.ts` apply:
 *
 * - stable across retries of the same intent
 * - retired when the intent changes (new reason, different camera)
 * - retired on success
 * - retired when the 503 turns out to mean "it was persisted anyway"
 */
export interface TriggerIntent {
  key: string
  cameraId: string
  reason: string
}

/** A key that is stable for one intent and different for another. */
export function newTriggerIntent(
  cameraId: string,
  reason: string,
): TriggerIntent {
  const random =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(36).slice(2)}`
  return { key: `manual-${cameraId}-${random}`, cameraId, reason }
}

export function useCreateRecordingTrigger(cameraId: string) {
  return useSave<
    { body: RecordingTriggerCreate; intent: TriggerIntent },
    unknown
  >({
    mutationFn: ({ body, intent }) =>
      createRecordingTrigger(cameraId, body, intent.key),
    invalidates: [RECORDINGS.triggers(cameraId)],
    success: () => ({
      title: "已触发手动录制",
      detail: "它会覆盖该机位的计划录制，直到你手动结束——包括计划为「不录制」时。",
    }),
    failure: (error) => {
      // The row is committed before the enqueue (`api.py:984-993`). Reporting
      // this as a failure invites a retry, and a retry without the same key
      // would create a second trigger nobody can tell apart.
      const persisted = triggerPersistedAnyway(error)
      if (persisted) {
        return {
          title: "触发已创建，但任务队列不可用",
          detail: `记录已经落库（${persisted.triggerId ?? "未知 id"}），队列恢复后会被调度器接手。请不要重复触发，也不要在列表里手动结束它。`,
        }
      }
      return { title: "触发手动录制失败", detail: describeTriggerFailure(error) }
    },
  })
}

/**
 * Stopping lets the post-roll tail finish — `planned_end_at = now +
 * post_roll_seconds` (`triggers.py:368-372`) — and a second stop is a silent
 * no-op. Both belong in the message, because "stopped" and "stopped now" are
 * different promises.
 */
export function useStopRecordingTrigger(cameraId: string) {
  return useSave<string, unknown>({
    mutationFn: (triggerId) => stopRecordingTrigger(triggerId),
    invalidates: [RECORDINGS.triggers(cameraId)],
    success: () => ({
      title: "已结束手动录制",
      detail: "前录/后录的尾巴仍会继续录完；再点一次不会有任何变化。",
    }),
    failure: (error) => {
      const persisted = triggerPersistedAnyway(error)
      if (persisted) {
        return {
          title: "结束请求已记录，但任务队列不可用",
          detail: "队列恢复后会接手这次结束。",
        }
      }
      return { title: "结束手动录制失败", detail: describeTriggerFailure(error) }
    },
  })
}

function describeTriggerFailure(error: unknown): string {
  const code = (error as { code?: string } | null)?.code
  switch (code) {
    case "event_recording_not_enabled":
      return "该机位没有开启事件录制，无法手动触发——只有按计划录制的机位不能这样补录。"
    case "idempotency_key_invalid":
      return "幂等键无效（1–256 字符）。"
    case "recording_trigger_not_manual":
      return "只有手动触发可以手动结束。"
    case "recording_trigger_not_active":
      return "该触发已经结束了。"
    case "recording_trigger_not_found":
      // Also what an out-of-scope id returns, deliberately.
      return "找不到该触发，或它不在你的摄像机范围内。"
    case "camera_not_found":
      return "找不到该机位。"
    default:
      return error instanceof Error ? error.message : String(error)
  }
}
