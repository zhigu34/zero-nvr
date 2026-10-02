import { useState } from "react"
import {
  Ban,
  ChevronDown,
  ChevronRight,
  Download,
  Link2,
  TriangleAlert,
} from "lucide-react"

import {
  exportDownloadPath,
  exportStateLabel,
  exportStateTone,
  isSettled,
  type ExportView,
} from "../../api/exports"
import { formatBytes } from "../../api/storage"
import { formatClock, formatRelative } from "../../lib/format"
import { formatSpan } from "../../lib/exportValidation"
import { Badge, Button } from "../ui/primitives"
import { Callout, EmptyState, StatusDot, StatusLabel } from "../ui/display"
import { SharePanel } from "./SharePanel"
import { cn } from "../../lib/utils"

/**
 * The export job list.
 *
 * **No progress bar.** `ExportView` has `state`, `started_at` and
 * `completed_at` and nothing else — a percentage would have to be extrapolated
 * from elapsed time, which is a fabricated number wearing a progress bar's
 * clothing. The state and the elapsed clock are shown instead, which is the
 * same information the backend actually has.
 *
 * The one thing worth noticing here is what a stuck job looks like. A 503
 * after commit leaves a row in `PENDING` that no worker will ever claim, and
 * it is indistinguishable from a slow one unless the age is visible — so
 * `PENDING` past a couple of minutes says so in words.
 */
export function ExportJobList({
  jobs,
  cameraNames,
  onCancel,
  cancelling,
}: {
  jobs: readonly ExportView[]
  cameraNames: ReadonlyMap<string, string>
  onCancel: (id: string) => void
  cancelling: string | null
}) {
  const [expanded, setExpanded] = useState<string | null>(null)

  if (jobs.length === 0) {
    return (
      <EmptyState
        icon={<Download />}
        title="还没有导出任务"
        description="在「录像浏览」里选中一段录像，用行末的下载按钮把它的起止时间带到这里，或直接在右侧填写范围后创建。"
      />
    )
  }

  return (
    <ul className="space-y-2">
      {jobs.map((job) => {
        const open = expanded === job.id
        const expired = Date.parse(job.expires_at) <= Date.now()
        const settled = isSettled(job.state)
        const shareable = job.state === "COMPLETED"
        const downloadable = shareable && !expired
        const stranded =
          job.state === "PENDING" &&
          Date.now() - Date.parse(job.created_at) > 2 * 60 * 1000

        return (
          <li key={job.id} className="rounded-lg border border-border">
            <div className="flex flex-wrap items-center gap-2 px-3 py-2.5">
              <StatusDot tone={exportStateTone(job.state)} />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="text-sm font-medium">
                    {cameraNames.get(job.camera_id) ?? job.camera_id}
                  </span>
                  <StatusLabel tone={exportStateTone(job.state)} className="text-xs">
                    {exportStateLabel(job.state)}
                  </StatusLabel>
                  {job.error_code && (
                    <Badge variant="outline" className="font-mono text-[10px]">
                      {job.error_code}
                    </Badge>
                  )}
                </div>
                <p className="mt-0.5 text-xs tabular-nums text-muted-foreground">
                  {formatClock(job.start_at)} → {formatClock(job.end_at)}
                  <span className="mx-1.5">·</span>
                  请求 {formatSpan(job.requested_duration_ms)}
                  {job.actual_duration_ms !== null && (
                    <>
                      <span className="mx-1.5">·</span>
                      实际 {formatSpan(job.actual_duration_ms)}
                    </>
                  )}
                </p>
                <p className="mt-0.5 text-[11px] text-muted-foreground">
                  {job.selected_segment_count !== null
                    ? `${job.selected_segment_count} 个片段 · ${formatBytes(job.size_bytes)}`
                    : "尚未解析片段"}
                  <span className="mx-1.5">·</span>
                  {job.codec_mode}
                  <span className="mx-1.5">·</span>
                  缺口{job.gap_policy === "fail" ? "报错" : "跳过"}
                  <span className="mx-1.5">·</span>
                  {formatRelative(job.created_at)}创建
                  {settled && job.completed_at && (
                    <>
                      <span className="mx-1.5">·</span>
                      {formatRelative(job.completed_at)}结束
                    </>
                  )}
                </p>
              </div>

              <div className="flex shrink-0 items-center gap-1">
                {!settled && (
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    title="取消该导出"
                    disabled={cancelling === job.id}
                    onClick={() => onCancel(job.id)}
                  >
                    <Ban className="size-3.5" />
                  </Button>
                )}
                {shareable && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setExpanded(open ? null : job.id)}
                  >
                    {open ? <ChevronDown /> : <ChevronRight />} <Link2 /> 分享
                  </Button>
                )}
                {downloadable ? (
                  <a href={exportDownloadPath(job.id)} download>
                    <Button variant="outline" size="sm">
                      <Download /> 下载
                    </Button>
                  </a>
                ) : (
                  shareable && (
                    <Button variant="outline" size="sm" disabled title="导出文件已过期">
                      <Download /> 已过期
                    </Button>
                  )
                )}
              </div>
            </div>

            {stranded && (
              <div className="px-3 pb-2.5">
                <Callout tone="degraded" title="这条导出已排队很久">
                  它可能是在任务队列不可用时被记录下来、从未真正开始处理。
                  再等下去不会自行完成——请取消后重新创建。
                </Callout>
              </div>
            )}

            {open && shareable && (
              <div className="border-t border-border p-3">
                <SharePanel job={job} />
              </div>
            )}
          </li>
        )
      })}
    </ul>
  )
}

export function ExportJobListSkeleton() {
  return (
    <div className="space-y-2">
      {[0, 1].map((i) => (
        <div
          key={i}
          className={cn("h-16 animate-pulse rounded-lg border border-border")}
        />
      ))}
      <p className="flex items-center justify-center gap-1.5 py-2 text-xs text-muted-foreground">
        <TriangleAlert className="size-3.5" /> 正在读取导出任务…
      </p>
    </div>
  )
}
