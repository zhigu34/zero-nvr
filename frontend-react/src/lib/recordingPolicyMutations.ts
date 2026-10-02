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
 */
export function useSaveRecordingPolicy(cameraId: string) {
  return useSave<RecordingPolicyPut, unknown>({
    mutationFn: (body) => putCameraRecordingPolicy(cameraId, body),
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
