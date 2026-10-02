import {
  createCameraProtection,
  deleteRecordingProtection,
  updateRecordingProtection,
  type ProtectionBody,
} from "../api/protections"
import { FILES } from "./queries"
import { useSave } from "./save"

/**
 * Writes for recording protections.
 *
 * There is no PATCH. Both create and update go through the same body
 * (`RecordingProtectionCreate` and `RecordingProtectionUpdate` are byte-identical
 * schemas, `recordings/schemas.py:284-307`), and the update is a PUT — a whole
 * -object replace in which an omitted `expires_at` clears the expiry. So
 * `buildProtectionBody` always sends all four fields, and both mutations take
 * the same shape.
 *
 * Neither is idempotent. Overlapping protections are legal — there is no
 * uniqueness constraint, only a `ended_at > started_at` check
 * (`models.py:194-197`) — so a double-click creates two windows, and the
 * operator has no way to tell which one they meant.
 */

export function useCreateCameraProtection(cameraId: string) {
  return useSave<ProtectionBody, unknown>({
    mutationFn: (body) => createCameraProtection(cameraId, body),
    invalidates: [FILES.protections(cameraId)],
    success: () => ({
      title: "保护已建立",
      // Retention skips protected segments (`storage/retention.py:364-380`), so
      // this window is a standing claim on disk space. Saying so is part of the
      // confirmation, not an afterthought.
      detail: "与该区间重叠的录像不会被保留策略清理，磁盘占用会一直增加。",
    }),
    failure: (error) => ({
      title: "建立保护失败",
      detail: describeProtectionFailure(error),
    }),
  })
}

export function useUpdateRecordingProtection(protectionId: string) {
  return useSave<ProtectionBody, unknown>({
    mutationFn: (body) => updateRecordingProtection(protectionId, body),
    invalidates: [["files", "protections"]],
    success: () => ({ title: "保护已更新" }),
    failure: (error) => ({
      title: "更新保护失败",
      detail: describeProtectionFailure(error),
    }),
  })
}

/** Irreversible: the window is gone and the recordings become deletable again. */
export function useDeleteRecordingProtection() {
  return useSave<string, void>({
    mutationFn: (protectionId) => deleteRecordingProtection(protectionId),
    invalidates: [["files", "protections"]],
    success: () => ({
      title: "保护已撤销",
      detail: "该区间的录像重新变成可被保留策略清理。",
    }),
    failure: (error) => ({
      title: "撤销保护失败",
      detail: describeProtectionFailure(error),
    }),
  })
}

function describeProtectionFailure(error: unknown): string {
  const code = (error as { code?: string } | null)?.code
  switch (code) {
    case "recording_protection_range_invalid":
      return "结束时间必须晚于开始时间。"
    case "recording_protection_reason_required":
      return "保护原因不能为空。"
    case "recording_protection_reason_too_long":
      return "保护原因过长。"
    case "recording_protection_expiry_invalid":
      return "失效时间必须是将来的时间。"
    case "recording_deletion_in_progress":
      return "该区间有录像正在被删除，无法建立保护——文件已经在清理路上了。"
    case "timezone_required":
      return "时间必须带时区。若你在改一份已有的保护，请确认起止时间没有被清空。"
    case "recording_protection_not_found":
      // Also what an out-of-scope id returns, deliberately (`api.py:814-820`).
      return "找不到该保护，或它不在你的摄像机范围内。";
    case "camera_not_found":
      return "找不到该机位。"
    default:
      return error instanceof Error ? error.message : String(error)
  }
}
