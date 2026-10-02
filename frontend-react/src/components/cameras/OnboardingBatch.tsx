import { useEffect, useRef, useState, type ChangeEvent } from "react"
import { Download, FileUp, Loader2, Play, Square, TriangleAlert } from "lucide-react"

import { ApiError } from "../../api/client"
import {
  IDENTITY_STATE_LABEL,
  ONVIF_TIMEOUT_BUDGET_MS,
  buildManualCameraInput,
  buildOnvifImportInput,
  buildOnvifProbeInput,
  identityBlockedReason,
  importableProfiles,
  validateManualCameraForm,
  type OnvifIdentityView,
  type OnvifImportResult,
} from "../../api/onboarding"
import {
  useCreateManualCamera,
  useImportOnvifDevice,
  useInspectOnvif,
  useTestManualCamera,
} from "../../lib/onboardingMutations"
import {
  BATCH_CSV_HEADERS,
  CsvParseError,
  batchRowLabel,
  buildBatchCsvTemplate,
  csvParseErrorMessage,
  manualFormForRow,
  onvifFormForRow,
  parseBatchCsv,
  type BatchCsvRow,
} from "../../lib/batchCsv"
import { Button } from "../ui/primitives"
import { Callout, EmptyState, PrototypeNote } from "../ui/display"

/**
 * CSV 批量录入。
 *
 * ## This is a loop over the operator's file, not a bulk endpoint
 *
 * There is no server-side batch call, no server-side CSV parsing and **no
 * dry-run** — `POST /cameras/onvif/import` is the only "validation" and it
 * writes. Three consequences drive the whole shape of this component:
 *
 * 1. **Not atomic, and never presented as if it were.** Row 37 failing leaves
 *    rows 1–36 in the database with no rollback and no way to undo them from
 *    here. There is therefore deliberately no "先校验" button: no such thing
 *    exists to call, and a control that only looks like one is worse than
 *    nothing. Contract gap **G-39**.
 * 2. **Serial, and slow.** Each ONVIF row is a 10 s inspection plus a 12 s ZLM
 *    probe per selected profile (`ONVIF_TIMEOUT_BUDGET_MS`), so a 20-row file
 *    is measured in minutes. Rows run one at a time — the loop awaits each one
 *    — and the operator can stop between rows.
 * 3. **Per-row outcomes, not one spinner.** A batch is minutes long; a screen
 *    that says "导入中" for four minutes is indistinguishable from a hang.
 *
 * ## `review` is not `failed`
 *
 * Identity is a four-state machine, and three of the four states mean *do not
 * import this row* rather than *this row is broken*
 * (`onvif_onboarding.py:462-481`). Collapsing them into `failed` would invite a
 * blind retry of a row that 409s every time, so they get their own state and
 * their own message.
 *
 * ## The password is read, used, and never shown
 *
 * The file needs credentials or it cannot onboard anything. They go straight
 * from the parser into the request body: never into an input, a row label, a
 * per-row error, a toast or a query key. That also rules out showing the
 * assembled `rtsp://user:pass@…` URL, so the row list shows `main_path`.
 */
export function OnboardingBatch() {
  const [fileName, setFileName] = useState("")
  const [rows, setRows] = useState<BatchCsvRow[]>([])
  const [parseError, setParseError] = useState<string | null>(null)
  const [outcomes, setOutcomes] = useState<Record<number, RowOutcome>>({})
  // The loop needs to read every outcome at the end to build the summary, and
  // a `setState` is not readable from inside an async run.
  const outcomesRef = useRef<Record<number, RowOutcome>>({})
  const [running, setRunning] = useState(false)
  const [summary, setSummary] = useState<BatchSummary | null>(null)
  const [now, setNow] = useState(() => Date.now())

  const inspect = useInspectOnvif()
  const importDevice = useImportOnvifDevice()
  const testStream = useTestManualCamera()
  const createCamera = useCreateManualCamera()

  // A ref rather than state: the loop reads it between rows and must not be
  // re-created (or re-rendered) because a button was pressed. The in-flight
  // request cannot be recalled — `inspectOnvif` and `importOnvifDevice` take
  // no abort signal — so "stop" means "no further rows", not "undo this one".
  const stopRequested = useRef(false)
  // Guards a double click from starting a second loop over the same rows.
  const loopActive = useRef(false)

  // One tick a second, and only while a batch runs. A row's elapsed time is the
  // only thing that needs re-rendering on a timer.
  useEffect(() => {
    if (!running) return
    const timer = setInterval(() => setNow(Date.now()), 1_000)
    return () => clearInterval(timer)
  }, [running])

  const ready = rows.filter((row) => row.errors.length === 0 && row.kind !== null)
  const done = Object.keys(outcomes).length

  async function onFilePicked(event: ChangeEvent<HTMLInputElement>) {
    const input = event.target
    const file = input.files?.[0]
    // Cleared after reading, so the same file can be picked again after a
    // failed parse — otherwise the change event does not fire twice.
    input.value = ""
    if (!file) return

    setFileName(file.name)
    setParseError(null)
    outcomesRef.current = {}
    setOutcomes({})
    setSummary(null)
    try {
      const parsed = parseBatchCsv(await readFileText(file))
      setRows(parsed)
      if (parsed.length === 0) {
        setRows([])
        setParseError("文件里只有表头，没有数据行。")
      }
    } catch (caught) {
      setRows([])
      setParseError(
        caught instanceof CsvParseError
          ? csvParseErrorMessage(caught)
          : "文件读取失败，请重新选择。",
      )
    }
  }

  function downloadTemplate() {
    // Same object-URL dance as the recovery kit
    // (`components/storage/BackupPanel.tsx:901-911`): a Blob built in the page
    // has no URL of its own, and the anchor is removed immediately after.
    const blob = new Blob([buildBatchCsvTemplate()], {
      type: "text/csv;charset=utf-8",
    })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement("a")
    anchor.href = url
    anchor.download = "camera-onboarding-template.csv"
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    URL.revokeObjectURL(url)
  }

  function record(outcome: RowOutcome) {
    outcomesRef.current = { ...outcomesRef.current, [outcome.line]: outcome }
    setOutcomes(outcomesRef.current)
  }

  async function runBatch() {
    if (loopActive.current || rows.length === 0) return
    loopActive.current = true
    stopRequested.current = false
    setRunning(true)
    setSummary(null)
    outcomesRef.current = {}
    setOutcomes({})
    setNow(Date.now())

    try {
      for (const row of rows) {
        if (stopRequested.current) break

        record({
          line: row.line,
          state: "running",
          message: row.kind === "onvif" ? "正在检查设备…" : "正在测试码流…",
          startedAt: Date.now(),
          finishedAt: null,
          cameraCount: 0,
        })

        // A row that could not be parsed is a per-row failure, not a reason to
        // refuse the file: 39 good rows are still 39 good rows. The message
        // names the line so it can be found in the spreadsheet.
        if (row.errors.length > 0 || row.kind === null) {
          record(failed(row, row.errors.join("、") || "kind 无法识别"))
          continue
        }

        try {
          if (row.kind === "onvif") {
            await runOnvifRow(row)
          } else {
            await runRtspRow(row)
          }
        } catch (error) {
          // One row's failure never ends the run: the rows after it are
          // unrelated cameras, and a network blip is not a verdict on them.
          record(failed(row, describeRowFailure(error)))
        }
      }

      setSummary(summarise(outcomesRef.current, rows.length))
    } finally {
      loopActive.current = false
      setRunning(false)
    }
  }

  /**
   * The whole run for one ONVIF row: inspect, decide, then import.
   *
   * `buildOnvifImportInput` takes the identity the server just returned
   * (`api/onboarding.ts:530-545`) — that is the whole reason for the two-step,
   * and it is also the only way `confirm_existing_device_id` can ever be the
   * id the server actually matched.
   */
  async function runOnvifRow(row: BatchCsvRow) {
    const form = onvifFormForRow(row)
    const inspection = await inspect.mutateAsync(buildOnvifProbeInput(form))

    if (inspection.identity.state !== "new_device") {
      record({
        line: row.line,
        state: "review",
        message: identityReviewMessage(inspection.identity),
        startedAt: null,
        finishedAt: Date.now(),
        cameraCount: 0,
      })
      return
    }

    const profiles = importableProfiles(inspection)
    if (profiles.length === 0) {
      // Decided here rather than sent: `profile_tokens: []` is the request that
      // comes back 422 `onvif_no_usable_profiles` after another 10 s
      // (`onvif_onboarding.py:229-230`).
      record(failed(row, "没有可用的码流：所有 profile 都取不到可用的流地址。"))
      return
    }

    // The batch picked no profiles by hand, but it *did* verify exactly these
    // tokens a moment ago, so it sends exactly these tokens. `null` would mean
    // "every profile" and re-decide the set server-side.
    const verified = {
      ...form,
      selectedProfileTokens: profiles.map((profile) => profile.token),
      selectionTouched: true,
    }
    // The mutation hook widens the import result to `unknown` because all it
    // does is invalidate queries; the two fields the batch needs are read back
    // through the contract's own type.
    const result = (await importDevice.mutateAsync(
      buildOnvifImportInput(verified, inspection.identity),
    )) as OnvifImportResult
    const cameraCount = Array.isArray(result?.cameras) ? result.cameras.length : 0
    record(imported(row, cameraCount))
  }

  /**
   * The whole run for one `rtsp` row: probe, then create.
   *
   * The probe is a client convention, not a server invariant — `POST /cameras`
   * checks only `invalid_rtsp_url` syntax and never opens the stream
   * (`cameras/service.py:104,112`). Creating a camera that cannot play is
   * worse than a failed row, so the order stays.
   */
  async function runRtspRow(row: BatchCsvRow) {
    const form = manualFormForRow(row)
    const problems = validateManualCameraForm(form)
    if (problems.length > 0) {
      record(failed(row, problems.map((problem) => problem.message).join("、")))
      return
    }
    const body = buildManualCameraInput(form)
    await testStream.mutateAsync(body)
    await createCamera.mutateAsync(body)
    record(imported(row, 1))
  }

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-sm font-semibold">CSV 批量录入</h3>
        <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
          一行一台设备。文件只在你的浏览器里解析，服务器既不解析 CSV 也没有批量接口。
        </p>
      </div>

      <Callout tone="degraded" title="批量导入不是一次事务">
        {`没有「先校验后写入」：导入接口本身就是写入接口。中间任何一行失败，之前成功的行都会留在系统里，不会回滚，` +
          `请到机位列表里自行删除。每一行都要单独跑一遍检查，单行最长约 ` +
          `${Math.round((ONVIF_TIMEOUT_BUDGET_MS.inspection + ONVIF_TIMEOUT_BUDGET_MS.probePerStream) / 1000)} 秒起，` +
          `文件越大耗时越久。`}
      </Callout>

      <section className="space-y-2">
        <div className="flex flex-wrap items-end gap-3">
          <Button
            variant="secondary"
            size="sm"
            disabled={running}
            onClick={downloadTemplate}
          >
            <Download className="size-3.5" /> 下载 CSV 模板
          </Button>
          <label className="flex flex-col gap-1 text-xs">
            <span>批量导入 CSV 文件</span>
            <input
              type="file"
              accept=".csv,text/csv"
              disabled={running}
              onChange={onFilePicked}
              className="text-xs"
            />
          </label>
        </div>
        <p className="text-[11px] leading-relaxed text-muted-foreground">
          {`表头共 ${BATCH_CSV_HEADERS.length} 列，顺序随意、多余的列会被忽略：`}
          <span className="font-mono">{BATCH_CSV_HEADERS.join(", ")}</span>
        </p>
        <p className="text-[11px] leading-relaxed text-muted-foreground">
          模板里的 password 列是必需的：ONVIF 没有密码连不上，带账号的 rtsp 地址也要它。密码只会被送进请求体，
          不会显示在页面、错误提示或通知里。
        </p>
      </section>

      {parseError && (
        <Callout tone="offline" title="文件无法解析">
          {parseError}
        </Callout>
      )}

      {rows.length === 0 ? (
        <EmptyState
          icon={<FileUp />}
          title="还没有选择文件"
          description="选一个 CSV 文件后会先在这里列出解析结果，确认无误再开始导入。"
        />
      ) : (
        <>
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <p className="text-xs font-medium">{fileName}</p>
            <p className="text-[11px] text-muted-foreground">
              {`共 ${rows.length} 行 · 可导入 ${ready.length} 行 · 格式有误 ${rows.length - ready.length} 行`}
            </p>
          </div>
          <p className="text-[11px] leading-relaxed text-muted-foreground">
            下面只是本地的解析结果，不代表设备真的连得上：真正的写入发生在你点「开始导入」之后。
          </p>

          <ul aria-label="批量行列表" className="max-h-80 space-y-1.5 overflow-y-auto">
            {rows.map((row) => (
              <BatchRowView
                key={row.line}
                row={row}
                outcome={outcomes[row.line] ?? null}
                now={now}
              />
            ))}
          </ul>

          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" disabled={running || ready.length === 0} onClick={runBatch}>
              <Play className="size-3.5" />
              {`开始导入 ${ready.length} 行`}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              disabled={!running}
              onClick={() => {
                stopRequested.current = true
              }}
            >
              <Square className="size-3.5" /> 停止导入
            </Button>
            <span className="text-xs tabular-nums text-muted-foreground" aria-live="polite">
              {`${done} / ${rows.length}`}
            </span>
            <span className="text-[11px] text-muted-foreground">
              {running ? "逐行串行执行，停止会在当前行结束后生效。" : "一行一请求，不会并发。"}
            </span>
          </div>

          {summary && <BatchSummaryView summary={summary} />}
        </>
      )}

      <PrototypeNote>
        批量导入是逐行发送的：没有事先校验，也没有撤销操作。一行失败时，前面成功的行已经落库，需要你在机位列表里自己删除。
      </PrototypeNote>
    </div>
  )
}

/* -------------------------------------------------------------------------- */

type RowState = "pending" | "running" | "success" | "partial" | "review" | "failed"

const ROW_STATE_LABEL: Record<RowState, string> = {
  pending: "等待导入",
  running: "进行中",
  success: "成功",
  // Not a failure: one CSV row legitimately produced several cameras, because
  // cameras are grouped by `video_source_token` (`onvif_onboarding.py:1149-1176`).
  partial: "已创建多台",
  review: "需人工确认",
  failed: "失败",
}

interface RowOutcome {
  line: number
  state: RowState
  message: string
  startedAt: number | null
  finishedAt: number | null
  cameraCount: number
}

interface BatchSummary {
  succeeded: number
  partial: number
  review: number
  failed: number
  untouched: number
}

function failed(row: BatchCsvRow, reason: string): RowOutcome {
  return {
    line: row.line,
    state: "failed",
    // The line number is in the message, not only in the row heading: this
    // string is what an operator copies into the spreadsheet to fix the row.
    message: `第 ${row.line} 行：${reason}`,
    startedAt: null,
    finishedAt: null,
    cameraCount: 0,
  }
}

function imported(row: BatchCsvRow, cameraCount: number): RowOutcome {
  return {
    line: row.line,
    state: cameraCount > 1 ? "partial" : "success",
    message:
      cameraCount > 1
        ? `这一行创建了 ${cameraCount} 台机位：多通道设备按码流来源分组，一份输入会变成多台机位。`
        : `已创建 ${Math.max(cameraCount, 1)} 台机位。`,
    startedAt: null,
    finishedAt: Date.now(),
    cameraCount,
  }
}

function BatchRowView({
  row,
  outcome,
  now,
}: {
  row: BatchCsvRow
  outcome: RowOutcome | null
  now: number
}) {
  const state: RowState = outcome?.state ?? "pending"
  const message = outcome?.message ?? (row.errors.length > 0 ? row.errors.join("、") : "")

  return (
    <li className="rounded-lg border border-border p-2">
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-xs font-medium">{`第 ${row.line} 行 · ${batchRowLabel(row)}`}</p>
        <span className="text-[10px] uppercase text-muted-foreground">
          {row.kind ?? "?"}
        </span>
        <span aria-live="polite" className="text-[11px] text-muted-foreground">
          {ROW_STATE_LABEL[state]}
        </span>
        {state === "running" && (
          <span className="inline-flex items-center gap-1 text-[11px] text-muted-foreground">
            <Loader2 className="size-3 animate-spin" />
            {`已用 ${elapsedSeconds(outcome, now)} 秒`}
          </span>
        )}
      </div>
      <p className="mt-0.5 text-[11px] text-muted-foreground">
        {/* `main_path` rather than the assembled URL: the URL carries the
            row's credentials in its userinfo. */}
        {row.kind === "rtsp" && (row.mainPath || row.mainUrl ? `主码流：${row.mainPath || "已填完整地址"}` : null)}
        {row.kind === "onvif" && row.host ? `地址：${row.host}:${row.onvifPort}` : null}
      </p>
      {message && (
        <p
          className={
            state === "failed"
              ? "mt-1 text-[11px] text-status-offline"
              : "mt-1 text-[11px] text-muted-foreground"
          }
        >
          {message}
        </p>
      )}
      {row.errors.length > 0 && (
        <p className="mt-1 flex items-start gap-1 text-[11px] text-status-degraded">
          <TriangleAlert className="mt-0.5 size-3 shrink-0" />
          这一行不会被发送。
        </p>
      )}
    </li>
  )
}

function elapsedSeconds(outcome: RowOutcome | null, now: number): number {
  if (!outcome?.startedAt) return 0
  const end = outcome.finishedAt ?? now
  return Math.max(0, Math.round((end - outcome.startedAt) / 1_000))
}

function BatchSummaryView({ summary }: { summary: BatchSummary }) {
  // A named live region, because the non-atomic consequence is stated in two
  // other places on this screen and a test (or a screen reader) needs to be
  // able to point at this one specifically.
  return (
    <section role="status" aria-label="批量导入结果">
      <Callout tone={summary.failed > 0 ? "degraded" : "online"} title="批量导入已结束">
        <p>
          {`完成：成功 ${summary.succeeded} · 已创建多台 ${summary.partial} · 需人工确认 ${summary.review} · 失败 ${summary.failed}。`}
        </p>
        <p className="mt-1">
          失败和需人工确认的行都不会回滚：已经写入的行留在系统里，需要你在机位列表中自行删除或重新导入。
        </p>
        {summary.untouched > 0 && (
          <p className="mt-1">
            {`还有 ${summary.untouched} 行没有开始（已停止），它们没有产生任何写入。`}
          </p>
        )}
      </Callout>
    </section>
  )
}

/* -------------------------------------------------------------------------- */

function summarise(
  outcomes: Record<number, RowOutcome>,
  total: number,
): BatchSummary {
  const list = Object.values(outcomes)
  const count = (state: RowState) => list.filter((o) => o.state === state).length
  return {
    succeeded: count("success"),
    partial: count("partial"),
    review: count("review"),
    failed: count("failed"),
    // Rows the loop never reached, i.e. a stopped run.
    untouched: total - list.length,
  }
}

/**
 * Why a row needs a person, in the identity machine's own terms.
 *
 * `identity_conflict` has no path through import at all
 * (`onvif_onboarding.py:462-481`) and gets the contract's own blocked
 * sentence; the other two are legitimately retryable *by hand* in the wizard,
 * which is exactly what a batch cannot do.
 */
function identityReviewMessage(identity: OnvifIdentityView): string {
  const blocked = identityBlockedReason(identity)
  if (blocked) return blocked
  const matched = identity.matched_device_name ? `（${identity.matched_device_name}）` : ""
  if (identity.state === "same_device") {
    return `该设备${IDENTITY_STATE_LABEL.same_device}${matched}，批量导入不会刷新已存在的设备，这一行没有写入任何内容。如需刷新，请在机位列表中处理。`
  }
  return `该设备${IDENTITY_STATE_LABEL.probable_match_requires_confirmation}${matched}，需要人工确认后才能导入。批量导入不会替你确认，这一行保持未导入，请到机位列表中确认。`
}

/**
 * A per-row failure reason.
 *
 * `onboardingMutations.ts` translates the same codes, but that function is
 * private to that module, so this mirrors the codes a batch row can actually
 * produce. Anything unrecognised is reported as the bare code rather than as the
 * server's English prose: the code is what support can act on, and the
 * backend's `message` is not a translation. `error.message` is never rendered
 * at all, which is also what keeps a password out of a row.
 */
function describeRowFailure(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return "请求没有到达服务端或被中断，请检查网络后单独重试这一行。"
  }
  switch (error.code) {
    case "onvif_connection_failed":
      // Deliberately generic: wrong password, wrong IP and a firewall all land
      // here (`onvif_adapter.py:471-479`).
      return "无法连接该设备。地址、端口、凭据或网络策略任一不对，结果都一样，请逐项排查。"
    case "onvif_timeout":
      return `设备响应超时（服务端等待 ${ONVIF_TIMEOUT_BUDGET_MS.inspection / 1000} 秒）。`
    case "onvif_device_already_exists":
      return "该 host:port 已属于另一台设备。"
    case "onvif_device_topology_changed":
      return "设备的码流结构在检查之后发生了变化，请重新导入这一行。"
    case "onvif_no_usable_profiles":
      return "没有可用的码流：所有 profile 都取不到可用的流地址。"
    case "onvif_stream_uri_unavailable":
      return "该 profile 取不到可用的流地址。"
    case "invalid_onvif_profile_tokens":
      return "选中的 profile 不存在或已不可用。"
    case "invalid_rtsp_url":
      return "RTSP 地址无法解析，或协议不是 rtsp://。"
    case "device_credential_unavailable":
      return "密钥环里取不到该设备的凭据，密钥可能已被轮换掉。"
    case "validation_error":
      return "这一行的内容不符合接口要求，请对照模板检查列名与取值。"
    default:
      return `服务端返回错误：${error.code}`
  }
}

/**
 * Read a picked file as text.
 *
 * `file.text()` is the obvious call, but the DOM the tests run in implements
 * neither `Blob.text()` nor `Blob.arrayBuffer()`. `FileReader` is the one read
 * path both a browser and jsdom have.
 */
function readFileText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result ?? ""))
    reader.onerror = () => reject(new Error("文件读取失败"))
    reader.readAsText(file)
  })
}
