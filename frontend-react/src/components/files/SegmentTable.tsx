import { Clock, Download, Lock, Play, TriangleAlert } from "lucide-react"

import {
  integrityLabel,
  recordingReasonLabel,
  timingSourceLabel,
  timingStatusLabel,
  type RecordingSegmentView,
} from "../../api/playback"
import { overlapsProtection, type RecordingProtectionView } from "../../api/protections"
import { formatBytes } from "../../api/storage"
import { formatSpan } from "../../lib/exportValidation"
import { formatClock } from "../../lib/format"
import { Button, Table, TBody, TD, TH, THead, TR } from "../ui/primitives"
import { EmptyState, StatusDot, StatusLabel } from "../ui/display"
import { cn } from "../../lib/utils"

/**
 * The recording list for one camera over one window.
 *
 * Two columns the old file page showed are gone, and their absence is the
 * contract talking rather than an omission:
 *
 * - **Storage location.** Locations live on a separate endpoint
 *   (`GET /recordings/{id}/locations`), so a column of them costs one request
 *   per visible row. It is not worth N requests to decorate a list; the
 *   segment id in the row is what an operator needs to look one up.
 * - **Resolution.** `RecordingSegmentView` has no such field. The backend
 *   never learned the frame size, so there is nothing to show.
 *
 * What *is* shown instead is the two fields that decide whether a clip is
 * usable as evidence: `timing_status` (ADR-0011 — a PROVISIONAL time origin
 * has not been reconciled against a continuous media session) and
 * `integrity_status`.
 */
export function SegmentTable({
  segments,
  protections,
  loading,
  error,
  onExport,
  onPlay,
  hasNextPage,
  fetchingNextPage,
  onLoadMore,
}: {
  segments: readonly RecordingSegmentView[]
  protections: readonly RecordingProtectionView[]
  loading: boolean
  error: string | null
  onExport: (segment: RecordingSegmentView) => void
  onPlay: (segment: RecordingSegmentView) => void
  hasNextPage: boolean
  fetchingNextPage: boolean
  onLoadMore: () => void
}) {
  if (error) {
    return (
      <div className="p-4">
        <EmptyState
          icon={<TriangleAlert />}
          title="无法读取录像列表"
          description={error}
        />
      </div>
    )
  }

  if (loading && segments.length === 0) {
    return (
      <div className="p-4">
        <EmptyState icon={<Clock />} title="正在读取录像…" />
      </div>
    )
  }

  if (segments.length === 0) {
    return (
      <div className="p-4">
        <EmptyState
          icon={<Clock />}
          title="该时间段没有录像"
          description="机位未录制、未被计划或事件覆盖，或片段已超出保留期被清理。缩小时间范围不会让不存在的录像出现。"
        />
      </div>
    )
  }

  return (
    <div className="min-h-0 flex-1 overflow-auto">
      <Table>
        <THead>
          <TR>
            <TH>开始时间</TH>
            <TH>结束时间</TH>
            <TH className="text-right">时长</TH>
            <TH>编码</TH>
            <TH className="text-right">大小</TH>
            <TH>触发原因</TH>
            <TH>时间基准</TH>
            <TH>完整性</TH>
            <TH className="w-12">保护</TH>
            <TH className="text-right">操作</TH>
          </TR>
        </THead>
        <TBody>
          {segments.map((segment) => {
            const protectedNow = overlapsProtection(
              protections,
              segment.start_at,
              segment.end_at,
            )
            const timing = timingStatusLabel(segment.timing_status)
            const integrity = integrityLabel(segment.integrity_status)
            return (
              <TR
                key={segment.id}
                className={cn(protectedNow && "bg-status-degraded/5")}
              >
                <TD className="tabular-nums">{formatClock(segment.start_at)}</TD>
                <TD className="tabular-nums text-muted-foreground">
                  {formatClock(segment.end_at)}
                </TD>
                <TD className="tabular-nums text-right text-muted-foreground">
                  {formatSpan(segment.duration_ms)}
                </TD>
                <TD>
                  <span className="flex items-center gap-1">
                    <span>{segment.codec ?? "—"}</span>
                    <span className="text-[10px] text-muted-foreground">
                      {segment.container}
                    </span>
                  </span>
                </TD>
                <TD className="tabular-nums text-right">
                  {formatBytes(segment.size_bytes)}
                </TD>
                <TD>
                  <span className="flex flex-wrap gap-1">
                    {segment.recording_reasons.length === 0 ? (
                      <span className="text-xs text-muted-foreground">—</span>
                    ) : (
                      segment.recording_reasons.map((reason) => (
                        <span
                          key={reason}
                          className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground"
                        >
                          {recordingReasonLabel(reason)}
                        </span>
                      ))
                    )}
                  </span>
                </TD>
                <TD>
                  <StatusLabel tone={timing.tone} className="text-xs">
                    {timing.label}
                    <span className="text-[10px] text-muted-foreground">
                      {timingSourceLabel(segment.timing_source)}
                    </span>
                  </StatusLabel>
                </TD>
                <TD>
                  <StatusLabel tone={integrity.tone} className="text-xs">
                    {integrity.label}
                  </StatusLabel>
                </TD>
                <TD>
                  {protectedNow ? (
                    <span title="与保护时间窗重叠，不被保留策略自动清理">
                      <Lock className="size-3.5 text-status-degraded" />
                    </span>
                  ) : (
                    <StatusDot tone="unknown" />
                  )}
                </TD>
                <TD>
                  <div className="flex items-center justify-end gap-1">
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      title="在该时刻回放"
                      onClick={() => onPlay(segment)}
                    >
                      <Play className="size-3.5" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      title="以这段的时间范围创建导出"
                      onClick={() => onExport(segment)}
                    >
                      <Download className="size-3.5" />
                    </Button>
                  </div>
                </TD>
              </TR>
            )
          })}
        </TBody>
      </Table>

      {hasNextPage && (
        <div className="flex justify-center border-t border-border p-3">
          <Button
            variant="outline"
            size="sm"
            onClick={onLoadMore}
            disabled={fetchingNextPage}
          >
            {fetchingNextPage ? "读取中…" : "加载更多"}
          </Button>
        </div>
      )}
    </div>
  )
}
