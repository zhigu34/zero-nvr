import {
  cancelExport,
  createExport,
  createExportShare,
  revokeExportShare,
  type ExportCreate,
  type ExportShareCreate,
  type ExportView,
} from "../api/exports"
import { FILES } from "./queries"
import { useSave } from "./save"
import { strandedExportId } from "./exportIntent"

/**
 * Writes for the file/export screen.
 *
 * The create mutation takes the idempotency key from its caller rather than
 * minting one internally, because the key's lifetime is longer than a single
 * mutation: it has to survive a retry of the same intent and die when the
 * intent changes. See `lib/exportIntent.ts` for why that matters — in
 * particular why retrying a stranded job with the same key looks like success
 * and never produces a file.
 */

/**
 * `POST /exports` commits the job before queueing it, so a 503 with
 * `export_persisted: true` means the row exists and no worker will ever see it.
 * That is reported as its own outcome, and the stranded id is handed back so
 * the screen can offer cancelling it — retrying the request cannot fix this,
 * because the retry returns the same stranded job.
 */
export function useCreateExport() {
  return useSave<
    { body: ExportCreate; idempotencyKey: string },
    ExportView
  >({
    mutationFn: ({ body, idempotencyKey }) =>
      createExport(body, idempotencyKey),
    invalidates: [FILES.exports("")],
    success: (job) => ({
      title: "导出任务已创建",
      detail:
        job.state === "COMPLETED"
          ? "已完成，可直接下载或创建分享链接。"
          : "正在后台处理，完成后可下载或创建分享链接。",
    }),
    failure: (error) => {
      const stranded = strandedExportId(error)
      if (stranded) {
        return {
          title: "导出已记录，但未开始处理",
          detail:
            "任务队列当前不可用，这条导出不会被自动执行。" +
            "再次提交会创建一条新任务（重试同一条只会拿回这条卡住的），" +
            `卡住的记录可在列表中取消（id ${stranded}）。`,
        }
      }
      return {
        title: "创建导出失败",
        detail: error instanceof Error ? error.message : String(error),
      }
    },
  })
}

/** `DELETE /exports/{id}` cancels the job and unlinks its output. */
export function useCancelExport() {
  return useSave<string, void>({
    mutationFn: (exportId) => cancelExport(exportId),
    invalidates: [FILES.exports("")],
    success: () => ({ title: "导出任务已取消" }),
    failure: (error) => ({
      title: "取消失败",
      detail: error instanceof Error ? error.message : String(error),
    }),
  })
}

/**
 * Share links.
 *
 * Only a COMPLETED export can be shared (`shares.py:53` refuses anything
 * else), and the returned token is the only copy — it is never readable
 * again, so the screen has to show it at creation time rather than
 * "manage links" implying the URL can be recovered later.
 */
export function useCreateExportShare(exportId: string) {
  return useSave<ExportShareCreate, Awaited<ReturnType<typeof createExportShare>>>({
    mutationFn: (body) => createExportShare(exportId, body),
    invalidates: [FILES.shares(exportId), FILES.exports("")],
    success: (share) => ({
      title: "分享链接已创建",
      detail: `有效期至 ${new Date(share.expires_at).toLocaleString("zh-CN")}。链接只显示这一次，请立即复制。`,
    }),
    failure: (error) => ({
      title: "创建分享链接失败",
      detail: error instanceof Error ? error.message : String(error),
    }),
  })
}

export function useRevokeExportShare(exportId: string) {
  return useSave<string, void>({
    mutationFn: (shareId) => revokeExportShare(exportId, shareId),
    invalidates: [FILES.shares(exportId)],
    success: () => ({ title: "分享链接已撤销" }),
    failure: (error) => ({
      title: "撤销失败",
      detail: error instanceof Error ? error.message : String(error),
    }),
  })
}
