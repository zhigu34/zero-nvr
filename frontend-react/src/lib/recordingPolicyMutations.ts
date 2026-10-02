import {
  putCameraRecordingPolicy,
  type RecordingPolicyPut,
  type RecordingPolicyView,
} from "../api/recordingPolicies"
import { POLICIES } from "./queries"
import { useSave } from "./save"
import { wasPersisted } from "./cameraMutations"

/**
 * Policy writes.
 *
 * `PUT /cameras/{id}/recording-policy` commits the policy first and then
 * coordinates the media side; if that second half fails the response is 503
 * with `details.policy_persisted = true` (`recordings/api.py:620`). Reporting
 * that as a plain failure would have the operator resubmit a policy that is
 * already stored.
 *
 * The other half of the risk is quieter: when coordination *succeeds* but the
 * camera is offline, the request still returns 200 and the outcome is only in
 * `runtime`. That is handled where it is read, in `judgeRuntime`.
 *
 * ## Four fields are carried, never rebuilt
 *
 * This endpoint is a whole-resource PUT whose schema gives **every** optional
 * field a non-nullable default (`recordings/schemas.py:123-134`), so omitting
 * a key does not mean "leave it alone" — the server writes the default:
 *
 * | field | default | what a save would do |
 * |---|---|---|
 * | `event_recording_enabled` | `False` | silently switch event-triggered recording off |
 * | `event_filter` | `{}` | silently clear the operator's event filter |
 * | `storage_target_id` | `null` | unpin a pinned target; writes fall back to the default |
 * | `retention_policy_id` | `null` | unbind the retention policy |
 *
 * A form that submitted only the fields it renders would do all four with a
 * 200 in response. The recording screen has no UI for three of them, so there
 * is nothing to merge: the correct semantic is to carry the loaded values
 * through unchanged.
 *
 * This hook takes the loaded policy and puts every one of the four back if a
 * caller omits it, so the destructive path is closed at the layer every write
 * goes through — the same shape as `useUpdateAlertPolicy` for the alert
 * `match`.
 */
export function useSaveRecordingPolicy(
  cameraId: string,
  existing?: Partial<
    Pick<
      RecordingPolicyView,
      | "event_recording_enabled"
      | "event_filter"
      | "storage_target_id"
      | "retention_policy_id"
    >
  > | null,
) {
  const carried = existing ?? {}
  return useSave<RecordingPolicyPut, unknown>({
    mutationFn: (body) =>
      putCameraRecordingPolicy(cameraId, {
        ...body,
        // `undefined` here would still become the default server-side, so
        // each fallback is unconditional rather than a spread-when-present.
        event_recording_enabled:
          body.event_recording_enabled ?? carried.event_recording_enabled ?? false,
        event_filter: body.event_filter ?? carried.event_filter ?? {},
        storage_target_id: body.storage_target_id ?? carried.storage_target_id ?? null,
        retention_policy_id:
          body.retention_policy_id ?? carried.retention_policy_id ?? null,
      }),
    invalidates: [POLICIES.list, POLICIES.forCamera(cameraId)],
    success: () => ({
      title: "录制计划已保存",
      // A 200 is not evidence of recording; say where the real answer is.
      detail: "请查看上方「当前状态」确认该机位是否真的在录制。",
    }),
    failure: (error) =>
      wasPersisted(error)
        ? {
            title: "计划已保存，但尚未生效",
            detail:
              "配置已经写入，媒体运行时未接受该操作（通常是媒体服务繁忙）。后台任务会在服务恢复后重试。",
          }
        : {
            title: "录制计划保存失败",
            detail: error instanceof Error ? error.message : String(error),
          },
  })
}
