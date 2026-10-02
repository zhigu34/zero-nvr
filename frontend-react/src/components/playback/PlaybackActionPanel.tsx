import * as React from "react"

import {
  PRE_ROLL_STATUS_LABEL,
  TRIGGER_REASON_MAX,
  TRIGGER_STATE_LABEL,
  canStopTrigger,
  isTriggerActive,
  preRollShortfall,
  stopBlockedReason,
  triggerBlockedReason,
  triggerPersistedAnyway,
  triggerStateTone,
  type RecordingTriggerView,
} from "../../api/recordingTriggers"
import {
  buildProtectionBody,
  emptyProtectionForm,
  isProtectionActive,
  isProtectionExpired,
  validateProtectionForm,
  type ProtectionForm,
  type ProtectionFormError,
  type RecordingProtectionView,
} from "../../api/protections"
import {
  exportStateLabel,
  exportStateTone,
  type ExportView,
} from "../../api/exports"
import {
  useCameraProtections,
  useExports,
  useRecordingPolicies,
  useRecordingTriggers,
} from "../../lib/queries"
import {
  newTriggerIntent,
  useCreateRecordingTrigger,
  useStopRecordingTrigger,
  type TriggerIntent,
} from "../../lib/recordingTriggerMutations"
import {
  useCreateCameraProtection,
  useDeleteRecordingProtection,
} from "../../lib/protectionMutations"
import { formatClock } from "../../lib/format"
import { formatSeconds } from "../../lib/recordingRuntime"
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Input,
} from "../ui/primitives"
import { Callout, EmptyState, Section, StatusDot } from "../ui/display"
import { useConfirm } from "../ui/Confirm"

/**
 * The three writes an operator makes from a playback screen, and the two
 * read lists they need to be able to undo them.
 *
 * ## A manual trigger is a lease, not a segment
 *
 * The row the trigger writes makes the arbiter hold the camera recording for
 * the trigger's whole lifetime, **overriding `baseline_mode: "disabled"`**
 * (`arbiter.py:71-86`). Nothing expires it. That is why the list and the stop
 * action sit next to the create button, and why the create button says what an
 * open trigger costs.
 *
 * Two write-time facts shape the trigger form:
 *
 * 1. **It does not bypass the policy check.** `policy.enabled` *and*
 *    `policy.event_recording_enabled` must both be true or the POST is a 409
 *    `event_recording_not_enabled` (`triggers.py:79-88`). `triggerBlockedReason`
 *    turns that into the button's own disabled reason, so the operator is not
 *    sent to discover a 409 by clicking.
 * 2. **Without an `Idempotency-Key` every call creates a new ACTIVE row**
 *    (`triggers.py:289-290`), and two duplicate manual triggers are
 *    indistinguishable in the list while both keep the camera recording. The
 *    intent key is therefore kept in a ref, not in state: it has to survive the
 *    re-render that a failed attempt causes, and it has to be retired the
 *    moment it is spent.
 *
 * The 503 is the third instance of the persisted-anyway pattern — the row is
 * committed before the enqueue (`api.py:984-993`). A retry there does not
 * "try again", it creates a second trigger, so the panel locks the button
 * instead of offering a retry.
 *
 * ## A protection is a window, and it has two invisible costs
 *
 * The form is half-open `[started_at, ended_at)` with `ended_at > started_at`
 * enforced (`protection.py:133-134`), it must send an offset-bearing ISO
 * (`localWindowToIso`, or a hard 422 `timezone_required`), and the body always
 * carries all four fields because `PUT` replaces the object and an omitted
 * `expires_at` clears it (`protection.py:234-237`).
 *
 * Neither create nor update is idempotent — overlapping windows are legal — so
 * the button is disabled while in flight. And a window **blocks retention**
 * (`storage/retention.py:364-380`), which is a standing claim on disk that the
 * form says out loud. Conversely, alerts create protections on their own
 * (`alerts/service.py:921-927`), so a list can contain rows nobody made by
 * hand; `created_by === null` is the only hint and it is rendered as one.
 *
 * ## The history is composed, not audited
 *
 * The old Vue panel filtered the protections list client-side and called the
 * result "history". This one merges the protections and exports lists, and
 * says plainly that it is a composition of two lists — there is no audit query
 * behind it, and adding one would be inventing a history the contract does not
 * have.
 */

export interface PlaybackActionPanelProps {
  cameraId: string
}

/** Free-string types, labelled where we know them and shown raw where we do not. */
const TRIGGER_TYPE_LABEL: Record<string, string> = {
  MANUAL: "手动",
  EVENT: "事件",
  SCHEDULE: "计划",
}

/**
 * A synchronous submit lock.
 *
 * `isPending` is not one: the flag only lands on the next render, so two clicks
 * inside the same tick both see `false` and both mutate. That is exactly how a
 * duplicate manual trigger (`triggers.py:289-290`) or a duplicate protection
 * window (`models.py:194-197`, overlaps are legal) gets made, and neither
 * create is idempotent. A ref flips before the first await and cannot be raced.
 */
function useSubmitLock() {
  const locked = React.useRef(false)
  return {
    acquire: () => {
      if (locked.current) return false
      locked.current = true
      return true
    },
    release: () => {
      locked.current = false
    },
  }
}

export function PlaybackActionPanel({ cameraId }: PlaybackActionPanelProps) {
  return (
    <Card className="flex flex-col" data-testid="playback-action-panel">
      <CardHeader>
        <CardTitle>回放操作</CardTitle>
        <span className="text-xs text-muted-foreground">{cameraId}</span>
      </CardHeader>
      <CardContent className="flex flex-col gap-6">
        <ManualTriggerSection cameraId={cameraId} />
        <TriggerListSection cameraId={cameraId} />
        <ProtectionSection cameraId={cameraId} />
        <ActionHistorySection cameraId={cameraId} />
      </CardContent>
    </Card>
  )
}

/* -------------------------------------------------------------------------- */
/* Manual trigger                                                              */
/* -------------------------------------------------------------------------- */

function ManualTriggerSection({ cameraId }: { cameraId: string }) {
  const create = useCreateRecordingTrigger(cameraId)
  const { data: policies } = useRecordingPolicies()

  const [reason, setReason] = React.useState("")
  const lock = useSubmitLock()
  // A ref, not state: the key must survive the re-render a failed attempt
  // causes, otherwise every retry would mint a new one and defeat the header
  // it exists to send (`triggers.py:289-290`).
  const intentRef = React.useRef<TriggerIntent | null>(null)
  const [ackPersisted, setAckPersisted] = React.useState(false)

  // A 503 whose row was already committed is a success wearing a failure's
  // clothes, and the panel's only correct response is to stop offering the
  // button — not to offer a retry that would create a duplicate.
  const persisted = React.useMemo(
    () => triggerPersistedAnyway(create.error),
    [create.error],
  )
  const policyFound = policies !== undefined
  const policy = policies?.find((item) => item.camera_id === cameraId) ?? null

  const blocked = persisted
    ? "上一次触发已经落库（任务队列当时不可用）。请在下方列表确认它，不要重复触发。"
    : !policyFound
      ? "正在读取该机位的录制策略。"
      : policy === null
        ? "该机位没有配置录制策略，无法手动触发。"
        : triggerBlockedReason(policy)

  const submit = () => {
    if (persisted || !lock.acquire()) return
    const trimmed = reason.trim()
    const held = intentRef.current
    // Same intent → same key. Different reason → a different trigger, so a new
    // key; reusing one would make the second call a no-op against the first.
    const intent =
      held && held.reason === trimmed ? held : newTriggerIntent(cameraId, trimmed)
    intentRef.current = intent

    create.mutate(
      { body: { reason: trimmed || null }, intent },
      {
        onSuccess: () => {
          // Spent. The next click is a new intent and needs a new key.
          intentRef.current = null
          setReason("")
        },
        onError: (error) => {
          if (triggerPersistedAnyway(error)) intentRef.current = null
        },
        onSettled: () => lock.release(),
      },
    )
  }

  return (
    <Section
      title="手动录制触发"
      description="触发不会立刻产生一个录像文件，而是让录制器在触发存续期间一直写这个机位。"
      className="space-y-3"
    >
      <Callout tone="degraded" title="一个没人结束的触发会一直录下去">
        手动触发会覆盖该机位的计划录制设置，包括计划为「不录制」的机位
        （arbiter.py:71-86）。它不会自动过期，也没有时长上限——录制的停止时间等于你点「结束」的时间。
      </Callout>

      {persisted ? (
        <Callout tone="degraded" title="触发已创建，但任务队列不可用">
          记录已经落库（{persisted.triggerId ?? "未知 id"}），队列恢复后会被调度器接手。
          请不要重复触发，也不要在列表里手动结束它——重复提交会造出第二条无法区分的记录。
        </Callout>
      ) : null}

      <div className="flex flex-col gap-1.5">
        <label
          htmlFor="manual-trigger-reason"
          className="text-sm font-medium leading-tight"
        >
          触发原因
        </label>
        <Input
          id="manual-trigger-reason"
          value={reason}
          maxLength={TRIGGER_REASON_MAX}
          placeholder="例如：现场调试"
          onChange={(event) => setReason(event.target.value)}
          disabled={create.isPending}
        />
        <p className="text-xs text-muted-foreground">
          原因只写进这条触发记录，最多 {TRIGGER_REASON_MAX} 字；留空也能提交。
          重复提交同一个原因会复用同一个幂等键，改了原因则是另一次意图。
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button
          onClick={submit}
          disabled={Boolean(blocked) || create.isPending}
          title={blocked ?? undefined}
        >
          {create.isPending ? "触发中…" : "触发手动录制"}
        </Button>
        {blocked ? (
          <p className="text-xs text-status-degraded">{blocked}</p>
        ) : null}
        {persisted ? (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              // Clearing local state only. It sends nothing, and it exists so
              // the operator is not permanently locked out of the form.
              setAckPersisted(true)
              create.reset()
            }}
            disabled={ackPersisted}
          >
            我已在列表中核对
          </Button>
        ) : null}
      </div>
    </Section>
  )
}

/* -------------------------------------------------------------------------- */
/* Trigger list                                                                */
/* -------------------------------------------------------------------------- */

function TriggerListSection({ cameraId }: { cameraId: string }) {
  const { data: triggers, isPending, isError } = useRecordingTriggers(cameraId)

  return (
    <Section
      title="触发记录"
      description="服务端对这份列表硬性截断在最近 100 条，且不提供 limit 或游标（triggers.py:51-64）。"
    >
      <p className="text-xs text-muted-foreground">
        这里只显示最近 100 条触发记录，更早的记录在这里看不到，也无法翻页。
      </p>

      {isPending ? (
        <p className="text-xs text-muted-foreground">正在读取触发记录…</p>
      ) : isError ? (
        <Callout tone="offline" title="读取触发记录失败">
          触发属于其它机位时后端返回的也是 404（api.py:1054-1060），列表为空有可能不是真的为空。
        </Callout>
      ) : !triggers || triggers.length === 0 ? (
        <EmptyState title="没有触发记录" description="手动触发和事件触发都会出现在这里。" />
      ) : (
        <ul aria-label="触发记录列表" className="flex flex-col gap-2">
          {triggers.map((trigger) => (
            <TriggerRow key={trigger.id} trigger={trigger} cameraId={cameraId} />
          ))}
        </ul>
      )}
    </Section>
  )
}

function TriggerRow({
  trigger,
  cameraId,
}: {
  trigger: RecordingTriggerView
  cameraId: string
}) {
  const stop = useStopRecordingTrigger(cameraId)
  const confirm = useConfirm()
  const lock = useSubmitLock()
  const active = isTriggerActive(trigger)
  const shortfall = preRollShortfall(trigger)
  const stopReason = stopBlockedReason(trigger)
  const typeLabel = TRIGGER_TYPE_LABEL[trigger.type] ?? trigger.type

  const askStop = async () => {
    const ok = await confirm({
      title: "结束手动录制",
      // "Stopped" and "stopped now" are different promises: the endpoint sets
      // `planned_end_at = now + post_roll_seconds` (`triggers.py:368-372`) and a
      // second stop is a silent no-op that writes no audit event.
      message: `结束后本机位会继续录完 ${formatSeconds(trigger.post_roll_seconds)}的后录尾巴才真正停下；再点一次结束不会有任何变化，也不会留下操作记录。`,
      confirmLabel: "结束录制",
      danger: true,
    })
    if (!ok || !lock.acquire()) return
    stop.mutate(trigger.id, { onSettled: () => lock.release() })
  }

  return (
    <li className="rounded-lg border border-border p-3" data-trigger-id={trigger.id}>
      <div className="flex flex-wrap items-center gap-2">
        <StatusDot tone={triggerStateTone(trigger.state)} />
        {/* Free strings on both `state` and `type`: an unrecognised value is
            rendered, never swallowed, so a new backend state shows up as
            itself rather than as a blank row. */}
        <span className="text-sm font-medium">
          {TRIGGER_STATE_LABEL[trigger.state] ?? trigger.state}
        </span>
        <Badge variant="outline">类型：{typeLabel}</Badge>
        <span className="text-xs text-muted-foreground">{trigger.id}</span>
      </div>

      <dl className="mt-2 grid grid-cols-1 gap-1 text-xs sm:grid-cols-2">
        <div>
          <dt className="text-muted-foreground">开始时间</dt>
          <dd>{formatClock(trigger.requested_at)}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">结束时间</dt>
          <dd>
            {active ? (
              // `planned_end_at === null` is an open-ended trigger, not a
              // missing value and not a failure.
              <span>开放中（无结束时间）</span>
            ) : (
              <span>{formatClock(trigger.planned_end_at)}</span>
            )}
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground">原因</dt>
          <dd>{trigger.reason ?? "—"}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">前录</dt>
          <dd>{PRE_ROLL_STATUS_LABEL[trigger.pre_roll_status]}</dd>
        </div>
      </dl>

      {shortfall ? (
        <p className="mt-2 text-xs text-status-degraded">
          前录 {formatSeconds(shortfall.requested)}，实际可用{" "}
          {formatSeconds(shortfall.available)}，缺 {formatSeconds(shortfall.shortfall)}
        </p>
      ) : null}

      <div className="mt-2 flex items-center gap-2">
        {canStopTrigger(trigger) ? (
          <Button
            variant="outline"
            size="sm"
            onClick={() => void askStop()}
            disabled={stop.isPending}
          >
            {stop.isPending ? "结束中…" : "结束"}
          </Button>
        ) : (
          <p className="text-xs text-muted-foreground">{stopReason}</p>
        )}
      </div>
    </li>
  )
}

/* -------------------------------------------------------------------------- */
/* Protections                                                                 */
/* -------------------------------------------------------------------------- */

function ProtectionSection({ cameraId }: { cameraId: string }) {
  const { data: protections, isPending } = useCameraProtections(cameraId)
  const create = useCreateCameraProtection(cameraId)
  const remove = useDeleteRecordingProtection()
  const confirm = useConfirm()

  const [form, setForm] = React.useState<ProtectionForm>(emptyProtectionForm)
  const [errors, setErrors] = React.useState<ProtectionFormError[]>([])
  const createLock = useSubmitLock()
  const deleteLock = useSubmitLock()

  const errorFor = (field: ProtectionFormError["field"]) =>
    errors.find((item) => item.field === field)?.message

  const submit = () => {
    const found = validateProtectionForm(form)
    setErrors(found)
    if (found.length > 0) return
    if (!createLock.acquire()) return
    create.mutate(buildProtectionBody(form), {
      onSuccess: () => {
        setForm(emptyProtectionForm())
        setErrors([])
      },
      onSettled: () => createLock.release(),
    })
  }

  const askDelete = async (protection: RecordingProtectionView) => {
    const ok = await confirm({
      title: "撤销保护",
      // Irreversible, and it changes what retention is allowed to do — the
      // reason it needs a prompt even though it is a single click.
      message: `撤销后，${formatClock(protection.started_at)} 到 ${formatClock(protection.ended_at)} 之间不再受保护，与之重叠的录像会重新变成可被保留策略清理。此操作不可撤销。`,
      confirmLabel: "撤销保护",
      danger: true,
    })
    if (!ok || !deleteLock.acquire()) return
    remove.mutate(protection.id, { onSettled: () => deleteLock.release() })
  }

  return (
    <Section
      title="保护区间"
      description="保护是一段时间窗，不是某个文件的标记：与它重叠的录像会被保留下来。"
    >
      <form
        className="flex flex-col gap-3"
        onSubmit={(event) => {
          event.preventDefault()
          submit()
        }}
      >
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <FormField
            id="protection-started-at"
            label="开始时间"
            type="datetime-local"
            value={form.startedAt}
            error={errorFor("startedAt")}
            disabled={create.isPending}
            onChange={(value) => setForm((prev) => ({ ...prev, startedAt: value }))}
          />
          <FormField
            id="protection-ended-at"
            label="结束时间"
            type="datetime-local"
            value={form.endedAt}
            error={errorFor("endedAt")}
            disabled={create.isPending}
            onChange={(value) => setForm((prev) => ({ ...prev, endedAt: value }))}
          />
        </div>

        <FormField
          id="protection-reason"
          label="保护原因"
          value={form.reason}
          error={errorFor("reason")}
          disabled={create.isPending}
          onChange={(value) => setForm((prev) => ({ ...prev, reason: value }))}
        />

        <FormField
          id="protection-expires-at"
          label="失效时间"
          type="datetime-local"
          value={form.expiresAt}
          error={errorFor("expiresAt")}
          disabled={create.isPending}
          onChange={(value) => setForm((prev) => ({ ...prev, expiresAt: value }))}
        />
        <p className="text-xs text-muted-foreground">
          留空表示永不过期（expires_at 传 null，不是省略）。区间是左闭右开的
          [开始, 结束)，结束时间必须晚于开始时间；填写的是本地时间，提交时会带上时区。
        </p>

        <Callout tone="degraded" title="保护会挡住保留策略的清理">
          与该区间重叠的录像不会被保留策略删除（storage/retention.py:364-380），
          磁盘占用会一直增加，直到保护被撤销或过期。重复提交会造出两条重叠的保护，
          而且没有接口能告诉你哪一条是你想要的。
        </Callout>

        <div className="flex items-center gap-2">
          <Button type="submit" disabled={create.isPending}>
            {create.isPending ? "建立中…" : "建立保护"}
          </Button>
        </div>
      </form>

      <div className="mt-4 flex flex-col gap-2">
        <h4 className="text-sm font-medium">已有保护</h4>
        {isPending ? (
          <p className="text-xs text-muted-foreground">正在读取保护区间…</p>
        ) : !protections || protections.length === 0 ? (
          <EmptyState
            title="没有保护区间"
            description="告警命中时会自动建立保护，所以这里也可能出现不是你手动创建的行。"
          />
        ) : (
          <ul aria-label="保护区间列表" className="flex flex-col gap-2">
            {protections.map((protection) => (
              <li
                key={protection.id}
                className="flex flex-wrap items-center gap-2 rounded-lg border border-border p-3"
                data-protection-id={protection.id}
              >
                <div className="min-w-0 flex-1">
                  <p className="text-sm">
                    {formatClock(protection.started_at)} — {formatClock(protection.ended_at)}
                  </p>
                  <p className="text-xs text-muted-foreground">{protection.reason}</p>
                  <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    {protection.created_by === null ? (
                      // Alerts create protections on their own
                      // (`alerts/service.py:921-927`); `created_by` null is the
                      // only evidence, so it is rendered as a badge rather than
                      // as an empty byline.
                      <Badge variant="warning">由告警自动创建</Badge>
                    ) : (
                      <span>由 {protection.created_by} 创建</span>
                    )}
                    <span>
                      {protection.expires_at
                        ? `失效于 ${formatClock(protection.expires_at)}`
                        : "永不过期"}
                    </span>
                    {!isProtectionActive(protection) ? (
                      <Badge variant="muted">已失效</Badge>
                    ) : null}
                    {isProtectionExpired(protection) ? (
                      <Badge variant="muted">已过期</Badge>
                    ) : null}
                  </p>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  title="撤销保护"
                  disabled={remove.isPending}
                  onClick={() => void askDelete(protection)}
                >
                  {remove.isPending ? "撤销中…" : "撤销"}
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Section>
  )
}

function FormField({
  id,
  label,
  value,
  onChange,
  type = "text",
  error,
  disabled,
}: {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
  type?: string
  error?: string
  disabled?: boolean
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium leading-tight">
        {label}
      </label>
      <Input
        id={id}
        type={type}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      />
      {error ? <p className="text-xs text-status-offline">{error}</p> : null}
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Composed history                                                            */
/* -------------------------------------------------------------------------- */

type HistoryEntry = {
  id: string
  kind: "protection" | "export"
  at: number
  title: string
  detail: string
  tone: "online" | "degraded" | "offline" | "unknown"
}

function ActionHistorySection({ cameraId }: { cameraId: string }) {
  const { data: protections } = useCameraProtections(cameraId)
  const { data: exports } = useExports()

  const entries = React.useMemo<HistoryEntry[]>(() => {
    const fromProtections: HistoryEntry[] = (protections ?? []).map((item) => ({
      id: item.id,
      kind: "protection",
      at: Date.parse(item.created_at),
      title: "建立保护",
      detail: `${formatClock(item.started_at)} — ${formatClock(item.ended_at)} · ${item.reason}`,
      tone: isProtectionActive(item) ? "degraded" : "unknown",
    }))

    // `GET /exports` has no camera filter (`api/exports.ts:131-140`), so this
    // is a local intersection over the pages that have been fetched. Only the
    // first page is loaded here, which is why the caveat below is load-bearing.
    const fromExports: HistoryEntry[] = (exports?.pages ?? [])
      .flatMap((page) => page.items)
      .filter((item) => item.camera_id === cameraId)
      .map((item: ExportView) => ({
        id: item.id,
        kind: "export",
        at: Date.parse(item.created_at),
        title: "创建导出任务",
        detail: `${formatClock(item.start_at)} — ${formatClock(item.end_at)} · ${exportStateLabel(item.state)}`,
        tone: exportStateTone(item.state),
      }))

    return [...fromProtections, ...fromExports].sort((a, b) => b.at - a.at)
  }, [cameraId, exports, protections])

  return (
    <Section
      title="操作历史"
      description="由保护区间和导出任务两个列表在本地合成，不是审计日志。"
    >
      <p className="text-xs text-muted-foreground">
        这个列表把「保护区间」和「导出任务」两个接口的结果按时间排在一起，
        它不是审计日志：删除、结束触发等操作在这里都不会留下记录，
        导出任务也只包含已经加载到的页。
      </p>
      {entries.length === 0 ? (
        <EmptyState title="没有可显示的历史" description="还没有保护区间或导出任务。" />
      ) : (
        <ul aria-label="操作历史列表" className="flex flex-col gap-2">
          {entries.map((entry) => (
            <li
              key={`${entry.kind}-${entry.id}`}
              className="flex items-center gap-2 rounded-lg border border-border p-2.5"
            >
              <StatusDot tone={entry.tone} />
              <div className="min-w-0 flex-1">
                <p className="text-sm">
                  {entry.title}
                  <span className="ml-2 text-xs text-muted-foreground">{entry.id}</span>
                </p>
                <p className="text-xs text-muted-foreground">{entry.detail}</p>
              </div>
              <span className="text-xs text-muted-foreground">
                {formatClock(entry.at)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Section>
  )
}
