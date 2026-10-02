import {
  putCameraRecordingPolicy,
  type RecordingPolicyPut,
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
 * ## `event_filter` is carried, never rebuilt
 *
 * This endpoint is a whole-resource PUT and the schema types `event_filter`
 * with `Field(default_factory=dict)` (`recordings/schemas.py:128`) — so
 * omitting the key does not mean "leave it alone", it means "write an empty
 * filter". The service then stores `{}`
 * (`recordings/policy.py:375-379`). A form that submitted only the fields it
 * renders would therefore **silently clear the operator's event filter on
 * every save**, with a 200 in response.
 *
 * The recording screen has no event-filter UI at all, so there is nothing to
 * merge: the correct semantic is to carry the loaded value through unchanged.
 * This hook takes the existing filter and puts it back if a caller omits it,
 * so the destructive path is closed at the layer every write goes through —
 * the same shape as `useUpdateAlertPolicy` for the alert `match`.
 */
export function useSaveRecordingPolicy(
  cameraId: string,
  existingEventFilter: Record<string, unknown> = {},
) {
  return useSave<RecordingPolicyPut, unknown>({
    mutationFn: (body) =>
      putCameraRecordingPolicy(cameraId, {
        ...body,
        // `undefined` here would still become `{}` server-side, so the
        // fallback is unconditional rather than a spread-when-present.
        event_filter: body.event_filter ?? existingEventFilter ?? {},
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
