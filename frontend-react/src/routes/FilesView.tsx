import { useMemo, useRef, useState } from "react"
import { useNavigate } from "@tanstack/react-router"
import { Download, Film, FolderTree, Info, RefreshCw, Search } from "lucide-react"

import {
  useCameraRecordings,
  useCameraProtections,
  useCameras,
  useExports,
  useRecordingDaily,
  useSystemSettings,
} from "../lib/queries"
import { useCancelExport, useCreateExport } from "../lib/exportMutations"
import { formatSpan } from "../lib/format"
import {
  ensureIntent,
  retryIsSafe,
  strandedExportId,
  type ExportIntent,
} from "../lib/exportIntent"
import {
  EXPORT_MAX_RANGE_MS,
  localInputToUtcIso,
  utcIsoToLocalInput,
  validateExportForm,
} from "../lib/exportValidation"
import type { RecordingDayStat, RecordingSegmentView } from "../api/playback"
import { Badge, Button, Input, Select } from "../components/ui/primitives"
import {
  Callout,
  EmptyState,
  PageHeader,
  PrototypeNote,
  Segmented,
  Tabs,
} from "../components/ui/display"
import { SegmentTable } from "../components/files/SegmentTable"
import {
  DayDensityStrip,
  DayHeatmap,
  bucketByLocalHour,
  type DayCell,
} from "../components/files/RecordingDensity"
import { ExportJobList, ExportJobListSkeleton } from "../components/files/ExportJobList"

/**
 * 文件：录像浏览 + 导出 + 分享。
 *
 * The old Vue page was a three-pane file browser with a camera→day→hour tree,
 * tick-N-clips-and-download, per-row progress, a per-row storage-location
 * column and a per-row protection toggle. Four of those have no endpoint
 * behind them, and reproducing them anyway is the failure mode this rewrite
 * exists to avoid. What the contract actually supports:
 *
 * | Old | Now | Why |
 * |---|---|---|
 * | 「全部录像」root listing every camera | one camera at a time | `GET /cameras/{id}/recordings` is the only segment listing |
 * | tick N clips → N mp4s | one camera + one time range → one mp4 | `ExportCreate` takes a range, not segment ids |
 * | 62% progress bar | state + elapsed clock | `ExportView` has no progress field |
 * | 存储位置 per row | dropped | separate endpoint; costs N requests per page |
 * | 分辨率 per row | dropped | `RecordingSegmentView` has no such field |
 * | 保护锁 per row | derived lock marker | a protection is a camera time window; overlap is computed locally |
 *
 * The navigation still works the way an operator expects: a row's download
 * button lifts that segment's own bounds into the export form and switches to
 * the exports tab.
 */

type TabKey = "browse" | "exports"

function browserZone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"
  } catch {
    return "UTC"
  }
}

/** Today 00:00 → now, in the display zone. */
function defaultRange(timeZone: string) {
  const nowLocal = utcIsoToLocalInput(new Date().toISOString(), timeZone)
  const day = nowLocal.slice(0, 10)
  return { start: `${day}T00:00`, end: nowLocal || `${day}T23:59` }
}

/** The `datetime-local` value floored to the start of its own local day. */
function localDayStart(local: string): string {
  return `${(local || "").slice(0, 10)}T00:00`
}

/**
 * The `datetime-local` value ceiled to the end of its own local day.
 *
 * Ceiled rather than used as typed: the density strip answers "how much is on
 * this day", and asking for a day up to 09:00 would report that day as
 * mostly empty when the operator simply had not scrolled the range out.
 */
function localDayEnd(local: string): string {
  return `${(local || "").slice(0, 10)}T23:59`
}

/**
 * Every local day the range touches, paired with its aggregate if there is one.
 *
 * The range is walked day by day **in local terms**, so the strip's labels are
 * the same day labels the operator sees on the range inputs above it. Days
 * without material are still emitted with `stat: null` — a gap in the calendar
 * is information.
 *
 * The walk is bounded at 62 days. A wider range is a typing accident, and
 * rendering 400 cells to answer "which day do I want" is not a useful answer.
 */
const MAX_DENSITY_DAYS = 62

function buildDayCells(
  from: string,
  to: string,
  stats: readonly RecordingDayStat[],
): DayCell[] {
  const byDay = new Map(stats.map((stat) => [stat.day, stat]))
  const fromDay = (from || "").slice(0, 10)
  const toDay = (to || "").slice(0, 10)
  if (!/^\d{4}-\d{2}-\d{2}$/.test(fromDay) || !/^\d{4}-\d{2}-\d{2}$/.test(toDay)) {
    return []
  }

  const cells: DayCell[] = []
  const cursor = new Date(`${fromDay}T00:00:00Z`)
  const end = new Date(`${toDay}T00:00:00Z`)
  while (cursor <= end && cells.length < MAX_DENSITY_DAYS) {
    const day = cursor.toISOString().slice(0, 10)
    cells.push({ day, stat: byDay.get(day) ?? null, inRange: true })
    cursor.setUTCDate(cursor.getUTCDate() + 1)
  }
  return cells
}

export function FilesView() {
  const navigate = useNavigate()
  const settings = useSystemSettings()
  const cameras = useCameras()

  // The system display zone is what every other timestamp on the product is
  // rendered in, so the export form defaults to it rather than to whatever
  // the browser happens to be set to.
  const timeZone =
    settings.data?.general?.display_timezone ?? browserZone()

  const [tab, setTab] = useState<TabKey>("browse")
  const [cameraId, setCameraId] = useState<string | null>(null)
  const [range, setRange] = useState(() => defaultRange(timeZone))
  const [codecMode, setCodecMode] = useState<"auto" | "copy" | "h264">("auto")
  const [gapPolicy, setGapPolicy] = useState<"skip" | "fail">("skip")
  const [stateFilter, setStateFilter] = useState("")
  // The day the density strip has focused. Null = "no specific day", which is
  // the default: the page is range-first, and picking a day is a shortcut into
  // the range rather than a mode the page is trapped in.
  const [focusDay, setFocusDay] = useState<string | null>(null)

  const activeCamera = cameraId ?? cameras.data?.[0]?.id ?? null

  const cameraNames = useMemo(
    () => new Map((cameras.data ?? []).map((c) => [c.id, c.name])),
    [cameras.data],
  )

  // The browse list speaks UTC bounds; the form speaks wall clock. One
  // conversion, here, so the two can never disagree about what is selected.
  const browseBounds = useMemo(() => {
    const from = localInputToUtcIso(range.start, timeZone)
    const to = localInputToUtcIso(range.end, timeZone)
    return from && to ? { from, to } : null
  }, [range.start, range.end, timeZone])

  const segments = useCameraRecordings(
    activeCamera,
    browseBounds ?? { from: "", to: "" },
  )
  const protections = useCameraProtections(activeCamera)
  const exportsQuery = useExports(stateFilter || undefined)
  const createExport = useCreateExport()
  const cancelExport = useCancelExport()

  /**
   * The density strip covers the selected range's own extent in local days —
   * the same days the browse list is already scoped to, so the two can never
   * disagree about what is being shown.
   */
  const dailyRange = useMemo(() => {
    const from = localInputToUtcIso(localDayStart(range.start), timeZone)
    const to = localInputToUtcIso(localDayEnd(range.end), timeZone)
    return from && to ? { from, to, timeZone } : null
  }, [range.start, range.end, timeZone])

  const daily = useRecordingDaily(activeCamera, dailyRange ?? { from: "", to: "", timeZone })

  const validation = validateExportForm({
    start: range.start,
    end: range.end,
    timeZone,
    codecMode,
    gapPolicy,
  })

  /**
   * The idempotency key outlives a single mutation on purpose: it must
   * survive a retry of the same intent and be retired when the intent ends.
   * See `lib/exportIntent.ts` for why a stranded 503 must retire it rather
   * than reuse it.
   */
  const intentRef = useRef<ExportIntent | null>(null)
  const [lastStranded, setLastStranded] = useState<string | null>(null)

  const rows = segments.data?.pages.flatMap((page) => page.items) ?? []

  /** Every local day the selected range touches, whether or not it has material. */
  const densityDays = useMemo(
    () => buildDayCells(range.start, range.end, daily.data ?? []),
    [range.start, range.end, daily.data],
  )

  /**
   * The heatmap buckets the segments the browse list already holds, not a
   * second request: those rows carry exact bounds, and the first page alone is
   * an honest sample of *what was loaded* rather than a claim about the day.
   * When more pages exist the panel says so instead of implying it is whole.
   */
  const focusBuckets = useMemo(
    () =>
      focusDay
        ? bucketByLocalHour(rows, timeZone, focusDay)
        : [],
    [rows, timeZone, focusDay],
  )

  function submit() {
    if (!activeCamera || !validation.ok) return
    const body = {
      camera_id: activeCamera,
      start_at: validation.startUtc,
      end_at: validation.endUtc,
      format: "mp4" as const,
      codec_mode: codecMode,
      gap_policy: gapPolicy,
    }
    const intent = ensureIntent(intentRef.current, body)
    intentRef.current = intent
    createExport.mutate(
      { body, idempotencyKey: intent.key },
      {
        onSuccess: () => {
          // Retired so the same range can be exported again on purpose.
          intentRef.current = null
          setLastStranded(null)
        },
        onError: (error) => {
          const stranded = strandedExportId(error)
          if (stranded) {
            setLastStranded(stranded)
            intentRef.current = null
          } else if (!retryIsSafe(error)) {
            // A rejected request is not a retry candidate at all.
            intentRef.current = null
          }
        },
      },
    )
  }

  function exportSegment(segment: RecordingSegmentView) {
    setRange({
      start: utcIsoToLocalInput(segment.start_at, timeZone),
      end: utcIsoToLocalInput(segment.end_at, timeZone),
    })
    setTab("exports")
  }

  const exportRows = exportsQuery.data?.pages.flatMap((page) => page.items) ?? []

  return (
    <div className="flex h-full flex-col">
      <div className="shrink-0 border-b border-border px-4 py-3">
        <PageHeader
          title="文件"
          description="按机位浏览录像，并把一段时间范围导出为单个 mp4 或公开分享链接。"
          actions={
            <>
              <Badge variant="outline">{timeZone}</Badge>
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  void segments.refetch()
                  void exportsQuery.refetch()
                }}
              >
                <RefreshCw /> 刷新
              </Button>
            </>
          }
        />
      </div>

      <div className="shrink-0 border-b border-border px-4">
        <Tabs
          active={tab}
          onChange={(key) => setTab(key as TabKey)}
          tabs={[
            { key: "browse", label: "录像浏览" },
            { key: "exports", label: "导出与分享", count: exportRows.length },
          ]}
        />
      </div>

      {/* ------------------------------------------------------ range bar */}
      <div className="flex shrink-0 flex-wrap items-end gap-3 border-b border-border px-4 py-3">
        <label className="space-y-1">
          <span className="text-[11px] text-muted-foreground">机位</span>
          <Select
            className="w-56"
            value={activeCamera ?? ""}
            aria-label="选择机位"
            onChange={(e) => setCameraId(e.target.value || null)}
          >
            {(cameras.data ?? []).map((camera) => (
              <option key={camera.id} value={camera.id}>
                {camera.name}
              </option>
            ))}
          </Select>
        </label>

        <label className="space-y-1">
          <span className="text-[11px] text-muted-foreground">开始（{timeZone}）</span>
          <Input
            type="datetime-local"
            className="w-52"
            value={range.start}
            aria-label="开始时间"
            onChange={(e) => setRange((prev) => ({ ...prev, start: e.target.value }))}
          />
        </label>

        <label className="space-y-1">
          <span className="text-[11px] text-muted-foreground">结束（{timeZone}）</span>
          <Input
            type="datetime-local"
            className="w-52"
            value={range.end}
            aria-label="结束时间"
            onChange={(e) => setRange((prev) => ({ ...prev, end: e.target.value }))}
          />
        </label>

        <div className="flex items-center gap-2 pb-1">
          <Segmented
            value=""
            onChange={() => setRange(defaultRange(timeZone))}
            options={[{ value: "", label: "今天" }]}
          />
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setRange(defaultRange(timeZone))}
          >
            重置为今天
          </Button>
        </div>

        <div className="ml-auto flex items-center gap-2 pb-1">
          {validation.ok ? (
            <span className="text-xs text-muted-foreground">
              跨度 {formatSpan(validation.durationMs)}
            </span>
          ) : (
            <span className="text-xs text-status-degraded">{validation.error}</span>
          )}
        </div>
      </div>

      <div className="flex min-h-0 flex-1 flex-col">
        {tab === "browse" ? (
          <>
            <div className="shrink-0 space-y-3 border-b border-border px-4 py-3">
              <DayDensityStrip
                days={densityDays}
                selectedDay={focusDay}
                onSelect={setFocusDay}
                isPending={daily.isPending}
                error={daily.error}
              />
              {focusDay && <DayHeatmap buckets={focusBuckets} timeZone={timeZone} />}
            </div>
            <div className="flex shrink-0 items-center gap-2 border-b border-border bg-muted/40 px-4 py-1.5">
              <Search className="size-3.5 text-muted-foreground" />
              <span className="text-xs text-muted-foreground">
                {rows.length} 个片段
                {segments.hasNextPage && "（还有更多）"}
              </span>
              {protections.data && protections.data.length > 0 && (
                <span className="text-xs text-muted-foreground">
                  · {protections.data.length} 条保护时间窗
                </span>
              )}
            </div>
            <SegmentTable
              segments={rows}
              protections={protections.data ?? []}
              loading={segments.isPending}
              error={segments.error ? String(segments.error.message) : null}
              onExport={exportSegment}
              onPlay={(segment) =>
                navigate({
                  to: "/playback",
                  search: { camera: activeCamera ?? undefined, at: segment.start_at },
                })
              }
              hasNextPage={Boolean(segments.hasNextPage)}
              fetchingNextPage={segments.isFetchingNextPage}
              onLoadMore={() => void segments.fetchNextPage()}
            />
          </>
        ) : (
          <div className="flex min-h-0 flex-1 flex-col overflow-auto">
            <div className="grid gap-4 p-4 lg:grid-cols-[1fr_20rem]">
              <div className="min-w-0 space-y-3">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="flex items-center gap-1.5 text-sm font-semibold">
                    <Film className="size-4 text-muted-foreground" />
                    导出任务
                  </h2>
                  <Segmented
                    value={stateFilter}
                    onChange={setStateFilter}
                    options={[
                      { value: "", label: "全部" },
                      { value: "RUNNING", label: "进行中" },
                      { value: "COMPLETED", label: "已完成" },
                      { value: "FAILED", label: "失败" },
                    ]}
                  />
                </div>

                {lastStranded && (
                  <Callout tone="degraded" title="上一条导出已记录但未开始处理">
                    任务队列当时不可用，那条导出不会被自动执行。再次点击「创建导出」会
                    新建一条任务；要清理卡住的记录，请在列表中取消它。
                  </Callout>
                )}

                {exportsQuery.isPending ? (
                  <ExportJobListSkeleton />
                ) : exportsQuery.error ? (
                  <EmptyState
                    icon={<Download />}
                    title="无法读取导出任务"
                    description={String(exportsQuery.error.message)}
                  />
                ) : (
                  <ExportJobList
                    jobs={exportRows}
                    cameraNames={cameraNames}
                    cancelling={cancelExport.isPending ? "pending" : null}
                    onCancel={(id) => cancelExport.mutate(id)}
                  />
                )}
              </div>

              <aside className="space-y-3">
                <div className="rounded-lg border border-border p-3">
                  <h2 className="flex items-center gap-1.5 text-sm font-semibold">
                    <Download className="size-4 text-muted-foreground" />
                    创建导出
                  </h2>
                  <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
                    将
                    {activeCamera
                      ? `「${cameraNames.get(activeCamera) ?? activeCamera}」`
                      : "所选机位"}
                    在上方所选时间段内的录像合并为**一个** mp4，最长 7 天。
                  </p>

                  <div className="mt-3 space-y-2">
                    <label className="block space-y-1">
                      <span className="text-[11px] text-muted-foreground">
                        编码方式
                      </span>
                      <Select
                        value={codecMode}
                        aria-label="编码方式"
                        onChange={(e) =>
                          setCodecMode(e.target.value as "auto" | "copy" | "h264")
                        }
                      >
                        <option value="auto">auto — 由后端按素材决定</option>
                        <option value="copy">copy — 直接封装，不转码</option>
                        <option value="h264">h264 — 强制转 H.264</option>
                      </Select>
                    </label>

                    <label className="block space-y-1">
                      <span className="text-[11px] text-muted-foreground">
                        录像缺口
                      </span>
                      <Select
                        value={gapPolicy}
                        aria-label="缺口策略"
                        onChange={(e) => setGapPolicy(e.target.value as "skip" | "fail")}
                      >
                        <option value="skip">skip — 跳过缺口，输出更短</option>
                        <option value="fail">fail — 有缺口即失败</option>
                      </Select>
                    </label>
                  </div>

                  <Button
                    className="mt-3 w-full"
                    onClick={submit}
                    disabled={
                      !validation.ok ||
                      !activeCamera ||
                      createExport.isPending
                    }
                  >
                    {createExport.isPending ? "提交中…" : "创建导出"}
                  </Button>

                  {!validation.ok && (
                    <p className="mt-2 text-[11px] text-status-degraded">
                      {validation.error}
                    </p>
                  )}
                  {validation.ok &&
                    validation.durationMs > EXPORT_MAX_RANGE_MS - 60 * 60 * 1000 && (
                      <p className="mt-2 text-[11px] text-status-degraded">
                        接近 7 天上限，导出耗时可能较长。
                      </p>
                    )}
                </div>

                <PrototypeNote>
                  同一时间范围重复提交不会产生第二条任务：请求带
                  Idempotency-Key，后端按用户+键去重。修改时间或编码参数后键会重新生成。
                </PrototypeNote>

                <Callout tone="degraded" title="没有跨机位导出">
                  一次导出只覆盖一个机位的时间范围，跨机位需要分别创建。
                  旧页面的「全部录像」根节点没有对应端点，因此没有保留。
                </Callout>

                <Callout tone="unknown" title="时间基准的诚实说明">
                  <span className="flex items-start gap-1.5">
                    <Info className="mt-0.5 size-3.5 shrink-0" />
                    <span>
                      上方时间范围按 {timeZone} 填写，后端按 UTC 存储。
                      若浏览器时区与此处不同，请以本处为准。
                    </span>
                  </span>
                </Callout>
              </aside>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
