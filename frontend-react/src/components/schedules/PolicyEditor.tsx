import { useMemo, useState } from "react"
import { X } from "lucide-react"

import type {
  BaselineMode,
  RecordingPolicyView,
  ScheduleWindow,
} from "../../api/recordingPolicies"
import { Button, Input, Select } from "../ui/primitives"
import { Callout } from "../ui/display"
import {
  BASELINE_MODE_LABEL,
  DESIRED_MODE_LABEL,
  formatSeconds,
  judgeRuntime,
  runtimeTone,
} from "../../lib/recordingRuntime"
import {
  fromEventFilter,
  fromSchedulePayload,
  parseFilterList,
  toEventFilter,
  toSchedulePayload,
  validateEventFilter,
  validatePolicyForm,
  WEEKDAY_LABEL,
  type EventFilterDraft,
  type PolicyFieldError,
} from "../../lib/recordingPolicyValidation"
import { useSaveRecordingPolicy } from "../../lib/recordingPolicyMutations"

/**
 * The recording policy form.
 *
 * The status block at the top is the point of the screen. A policy save
 * returns 200 whether or not anything is actually being recorded, because
 * `recording_stream_offline` and the media-service start timeout are swallowed
 * server-side. Everything below the form explains what the runtime says.
 */

export interface PolicyEditorProps {
  cameraId: string
  cameraName: string
  /** `null` when the camera has no policy yet; the PUT is an upsert. */
  policy: RecordingPolicyView | null
  onClose: () => void
}

export function PolicyEditor({
  cameraId,
  cameraName,
  policy,
  onClose,
}: PolicyEditorProps) {
  const [baselineMode, setBaselineMode] = useState<BaselineMode>(
    policy?.baseline_mode ?? "continuous",
  )
  const [enabled, setEnabled] = useState(policy?.enabled ?? true)
  const [scheduleWindows, setScheduleWindows] = useState<ScheduleWindow[]>(() =>
    fromSchedulePayload(policy?.schedule),
  )
  const [scheduleTimezone, setScheduleTimezone] = useState(
    policy?.schedule_timezone ?? "",
  )
  const [segmentTarget, setSegmentTarget] = useState(
    policy?.segment_target_seconds ?? 300,
  )
  const [preRoll, setPreRoll] = useState(policy?.pre_roll_seconds ?? 10)
  const [postRoll, setPostRoll] = useState(policy?.post_roll_seconds ?? 10)
  const [eventFilter, setEventFilter] = useState<EventFilterDraft>(() =>
    fromEventFilter({
      ...(policy?.event_filter ?? {}),
      event_recording_enabled: policy?.event_recording_enabled,
    }),
  )

  const save = useSaveRecordingPolicy(cameraId, policy)

  const errors: PolicyFieldError[] = useMemo(
    () => [
      ...validatePolicyForm({
        baselineMode,
        enabled,
        scheduleWindows,
        scheduleTimezone,
        segmentTargetSeconds: segmentTarget,
        preRollSeconds: preRoll,
        postRollSeconds: postRoll,
      }),
      ...validateEventFilter(eventFilter),
    ],
    [
      baselineMode,
      enabled,
      scheduleWindows,
      scheduleTimezone,
      segmentTarget,
      preRoll,
      postRoll,
      eventFilter,
    ],
  )
  /**
   * An empty filter is legitimate — it means "record every event" — so the
   * message is shown but does not block the save. Only structural problems do.
   */
  const blocking = errors.filter((error) => error.field !== "event_filter.empty")
  const errorFor = (field: string) =>
    errors.find((error) => error.field === field)?.message ?? null

  const verdict = judgeRuntime(
    policy?.runtime,
    policy?.baseline_mode ?? baselineMode,
    policy?.enabled ?? enabled,
  )

  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    if (blocking.length) return

    const schedule =
      baselineMode === "schedule" ? toSchedulePayload(scheduleWindows) : undefined

    save.mutate({
      baseline_mode: baselineMode,
      enabled,
      // Now owned by this form. The switch gates `triggers.py:166`, and the
      // filter itself gates `_event_matches`; both are only consulted for
      // events that do not already have a trigger.
      event_recording_enabled: eventFilter.eventRecordingEnabled,
      event_filter: toEventFilter(eventFilter),
      // Still carried through unchanged — this form has no UI for either.
      storage_target_id: policy?.storage_target_id ?? null,
      retention_policy_id: policy?.retention_policy_id ?? null,
      // Both keys are sent as null rather than omitted in the wrong mode:
      // the backend rejects a non-empty schedule alongside a non-schedule
      // mode, and an explicit null is what clears a previously saved one.
      ...(schedule
        ? { schedule, schedule_timezone: scheduleTimezone.trim() }
        : { schedule: {}, schedule_timezone: null }),
      segment_target_seconds: segmentTarget,
      pre_roll_seconds: preRoll,
      post_roll_seconds: postRoll,
    })
  }

  return (
    <aside className="flex h-full w-full flex-col border-l border-border bg-card">
      <header className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
        <div className="min-w-0">
          <h2 className="truncate text-sm font-medium">录制计划</h2>
          <p className="truncate text-xs text-muted-foreground">{cameraName}</p>
        </div>
        <Button variant="ghost" size="sm" onClick={onClose} aria-label="关闭">
          <X className="h-4 w-4" />
        </Button>
      </header>

      <form className="flex-1 space-y-4 overflow-auto p-4" onSubmit={submit}>
        {/* G-18: HTTP 200 does not mean this camera is recording. */}
        <div
          className="rounded-lg border border-border p-3"
          data-runtime-health={verdict.health}
        >
          <p className="text-xs font-medium">
            当前状态
            <span className="ml-2 text-muted-foreground">
              期望：{DESIRED_MODE_LABEL[policy?.runtime?.desired_mode ?? "off"] ??
                "—"}
            </span>
          </p>
          <p className="mt-1 text-xs text-muted-foreground">{verdict.message}</p>
          {policy?.runtime?.observed_at ? (
            <p className="mt-1 text-[11px] text-muted-foreground">
              观测于 {policy.runtime.observed_at}
            </p>
          ) : null}
        </div>

        <div className="space-y-1.5">
          <label htmlFor="policy-mode" className="text-xs font-medium">
            录制模式
          </label>
          <Select
            id="policy-mode"
            value={baselineMode}
            onChange={(event) =>
              setBaselineMode(event.target.value as BaselineMode)
            }
          >
            {(Object.keys(BASELINE_MODE_LABEL) as BaselineMode[]).map((mode) => (
              <option key={mode} value={mode}>
                {BASELINE_MODE_LABEL[mode]}
              </option>
            ))}
          </Select>
        </div>

        <label className="flex items-center gap-2 text-xs">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(event) => setEnabled(event.target.checked)}
          />
          启用该计划
        </label>

        {baselineMode === "schedule" ? (
          <div className="space-y-2">
            <p className="text-xs font-medium">录制时段</p>
            {scheduleWindows.map((window, index) => (
              <div
                key={index}
                className="space-y-2 rounded border border-border p-2"
              >
                <div className="flex flex-wrap gap-1">
                  {Object.entries(WEEKDAY_LABEL).map(([day, label]) => {
                    const value = Number(day)
                    const active = window.days.includes(value)
                    return (
                      <button
                        key={day}
                        type="button"
                        onClick={() =>
                          setScheduleWindows((current) =>
                            current.map((entry, i) =>
                              i !== index
                                ? entry
                                : {
                                    ...entry,
                                    days: active
                                      ? entry.days.filter(
                                          (day: number) => day !== value,
                                        )
                                      : [...entry.days, value],
                                  },
                            ),
                          )
                        }
                        className={
                          active
                            ? "rounded bg-primary px-1.5 py-0.5 text-[11px] text-primary-foreground"
                            : "rounded border border-border px-1.5 py-0.5 text-[11px]"
                        }
                      >
                        {label}
                      </button>
                    )
                  })}
                </div>
                <div className="flex items-center gap-2">
                  <Input
                    type="time"
                    value={window.start}
                    onChange={(event) =>
                      setScheduleWindows((current) =>
                        current.map((entry, i) =>
                          i !== index ? entry : { ...entry, start: event.target.value },
                        ),
                      )
                    }
                    aria-label={`第 ${index + 1} 个时段开始时间`}
                    className="w-28"
                  />
                  <span className="text-xs text-muted-foreground">至</span>
                  <Input
                    type="time"
                    value={window.end}
                    onChange={(event) =>
                      setScheduleWindows((current) =>
                        current.map((entry, i) =>
                          i !== index ? entry : { ...entry, end: event.target.value },
                        ),
                      )
                    }
                    aria-label={`第 ${index + 1} 个时段结束时间`}
                    className="w-28"
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() =>
                      setScheduleWindows((current) =>
                        current.filter((_, i) => i !== index),
                      )
                    }
                  >
                    删除
                  </Button>
                </div>
                {errorFor(`schedule.${index}.start`) ? (
                  <p className="text-xs text-status-offline">
                    {errorFor(`schedule.${index}.start`)}
                  </p>
                ) : null}
              </div>
            ))}
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() =>
                setScheduleWindows((current) => [
                  ...current,
                  { days: [0, 1, 2, 3, 4], start: "22:00", end: "06:00" },
                ])
              }
            >
              添加时段
            </Button>
            {errorFor("schedule") ? (
              <p className="text-xs text-status-offline">{errorFor("schedule")}</p>
            ) : null}

            <div className="space-y-1.5">
              <label htmlFor="policy-tz" className="text-xs font-medium">
                时区
              </label>
              <Input
                id="policy-tz"
                value={scheduleTimezone}
                onChange={(event) => setScheduleTimezone(event.target.value)}
                placeholder="Asia/Shanghai"
              />
              {errorFor("schedule_timezone") ? (
                <p className="text-xs text-status-offline">
                  {errorFor("schedule_timezone")}
                </p>
              ) : null}
            </div>
          </div>
        ) : null}

        {errorFor("schedule") && baselineMode !== "schedule" ? (
          <p className="text-xs text-status-offline">{errorFor("schedule")}</p>
        ) : null}

        <div className="grid gap-3 sm:grid-cols-3">
          <NumberField
            id="policy-segment"
            label="目标分段（秒）"
            value={segmentTarget}
            onChange={setSegmentTarget}
            error={errorFor("segment_target_seconds")}
            hint={formatSeconds(segmentTarget)}
          />
          <NumberField
            id="policy-preroll"
            label="预录（秒）"
            value={preRoll}
            onChange={setPreRoll}
            error={errorFor("pre_roll_seconds")}
            hint={formatSeconds(preRoll)}
          />
          <NumberField
            id="policy-postroll"
            label="后录（秒）"
            value={postRoll}
            onChange={setPostRoll}
            error={errorFor("post_roll_seconds")}
            hint={formatSeconds(postRoll)}
          />
        </div>

        <EventFilterFields
          value={eventFilter}
          onChange={setEventFilter}
          errorFor={errorFor}
        />

        {/*
          G-20: the policy carries only a `retention_policy_id` foreign key.
          The day counts live in the storage module, so this page must not
          invent them.
        */}
        <Callout tone="degraded" title="保留天数不在此处配置">
          录制计划只保存一个保留策略引用（外键），实际保留天数在「存储与保留策略」
          中定义，范围 0–36500 天。本页不显示天数，也不允许在此修改——那需要一次
          跨模块的写入。
        </Callout>

        <Callout tone="degraded" title="系统级时区设置当前不生效">
          「系统设置 → 时区」写入的 <code>recording_timezone</code> 没有任何消费者：
          计划求值用的是本表单里的每机位时区（<code>schedule_timezone</code>）。
          因此录制时区必须在这里逐机位设置。
        </Callout>
      </form>

      <footer className="flex items-center justify-end gap-2 border-t border-border px-4 py-3">
        <Button variant="outline" size="sm" onClick={onClose}>
          取消
        </Button>
        <Button
          size="sm"
          onClick={submit}
          disabled={save.isPending || blocking.length > 0}
        >
          {save.isPending ? "保存中…" : "保存"}
        </Button>
      </footer>
    </aside>
  )
}

function NumberField({
  id,
  label,
  value,
  onChange,
  error,
  hint,
}: {
  id: string
  label: string
  value: number
  onChange: (value: number) => void
  error: string | null
  hint: string
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="text-xs font-medium">
        {label}
      </label>
      <Input
        id={id}
        type="number"
        value={Number.isFinite(value) ? value : ""}
        onChange={(event) => onChange(Number(event.target.value))}
        aria-invalid={Boolean(error)}
      />
      <p className="text-[11px] text-muted-foreground">{hint}</p>
      {error ? (
        <p className="text-xs text-status-offline">{error}</p>
      ) : null}
    </div>
  )
}

/**
 * The three-key event filter: `labels`, `zones`, `min_confidence`.
 *
 * ## Why `zones` carries a warning the other two do not
 *
 * This is D-2, and the warning is the point. The recording side tests
 * `set(required).intersection(metadata_json["zones"])`
 * (`recordings/triggers.py:106-109`) — **every** region the event touched. The
 * alert side tests membership of `Event.zone` (`alerts/service.py:643`) — the
 * **primary** region only. An event crossing `driveway` and `sidewalk`
 * therefore records under `sidewalk` here but does not alert there, and both
 * configurations look identical.
 *
 * The two filters are deliberately not merged; the alert screen refuses to
 * copy `zones` across for exactly this reason
 * (`alerts.ts` `MATCH_KEY_META.zones.importable = false`). This hint exists so
 * an operator reading one screen does not conclude the other is broken.
 */
function EventFilterFields({
  value,
  onChange,
  errorFor,
}: {
  value: EventFilterDraft
  onChange: (next: EventFilterDraft) => void
  errorFor: (field: string) => string | null
}) {
  const patch = (part: Partial<EventFilterDraft>) =>
    onChange({ ...value, ...part })

  const note = errorFor("event_filter.empty")

  return (
    <section className="space-y-3 rounded-lg border border-border p-3">
      <label className="flex items-start gap-2 text-xs font-medium">
        <input
          type="checkbox"
          className="mt-0.5"
          checked={value.eventRecordingEnabled}
          onChange={(event) =>
            patch({ eventRecordingEnabled: event.target.checked })
          }
        />
        <span>按事件触发录像</span>
      </label>

      {value.eventRecordingEnabled ? (
        <div className="space-y-3 pl-6">
          <Callout tone="degraded" title="条件留空 = 记录全部事件">
            三项都不填时，任何被识别出的事件都会触发录像。
          </Callout>

          <ListField
            id="policy-event-labels"
            label="事件标签"
            placeholder="person, car"
            items={value.labels}
            onChange={(labels) => patch({ labels })}
            error={errorFor("event_filter.labels")}
          />

          <ListField
            id="policy-event-zones"
            label="区域"
            placeholder="driveway, sidewalk"
            items={value.zones}
            onChange={(zones) => patch({ zones })}
            error={errorFor("event_filter.zones")}
          />

          <p className="text-[11px] text-muted-foreground">
            区域匹配事件的**全部**区域；告警规则只匹配**主区域**。同一事件
            触发了录像却没触发告警，是这两条规则本就不同，不是配置错了。
          </p>

          <div className="space-y-1.5">
            <label
              htmlFor="policy-event-confidence"
              className="text-xs font-medium"
            >
              最低置信度
            </label>
            <Input
              id="policy-event-confidence"
              type="number"
              min={0}
              max={1}
              step={0.05}
              placeholder="不限制"
              value={value.minConfidence ?? ""}
              onChange={(event) => {
                const raw = event.target.value
                patch({
                  minConfidence:
                    raw === "" ? undefined : Number(raw),
                })
              }}
              aria-invalid={Boolean(
                errorFor("event_filter.min_confidence"),
              )}
            />
            {errorFor("event_filter.min_confidence") ? (
              <p className="text-xs text-status-offline">
                {errorFor("event_filter.min_confidence")}
              </p>
            ) : null}
          </div>

          {note ? (
            <p className="text-[11px] text-muted-foreground">{note}</p>
          ) : null}
        </div>
      ) : null}
    </section>
  )
}

function ListField({
  id,
  label,
  placeholder,
  items,
  onChange,
  error,
}: {
  id: string
  label: string
  placeholder: string
  items: string[]
  onChange: (next: string[]) => void
  error: string | null
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="text-xs font-medium">
        {label}
      </label>
      <Input
        id={id}
        value={items.join(", ")}
        placeholder={placeholder}
        onChange={(event) => onChange(parseFilterList(event.target.value))}
        aria-invalid={Boolean(error)}
      />
      {error ? (
        <p className="text-xs text-status-offline">{error}</p>
      ) : null}
    </div>
  )
}

export { runtimeTone }
