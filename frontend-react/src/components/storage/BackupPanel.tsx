import { useEffect, useMemo, useState } from "react"
import { DatabaseBackup, HardDriveDownload, Pencil, Play, Plus, ShieldCheck, X } from "lucide-react"

import {
  BACKUP_STATE_LABEL,
  DATABASE_BACKENDS,
  RECOVERY_KIT_STATUS_LABEL,
  RECOVERY_PASSPHRASE_MIN,
  RETENTION_BUCKET_LABEL,
  RETENTION_BUCKETS,
  backupStateTone,
  buildSchedule,
  describeBackupReason,
  emptyPolicyForm,
  isVerifiable,
  policyFormFromView,
  scheduleIsCleared,
  validateBackupPolicyForm,
  type BackupPolicyForm,
  type BackupPolicyView,
  type BackupSetView,
  type SecretAction,
} from "../../api/backups"
import {
  RECOVERY_KITS,
  useBackupPolicies,
  useBackupSets,
  useRecoveryKitStatus,
  useSystemSettings,
} from "../../lib/queries"
import {
  buildBackupPolicyCreate,
  buildBackupPolicyPatch,
  useCreateBackupPolicy,
  useGenerateRecoveryKit,
  useRunBackupNow,
  useUpdateBackupPolicy,
  useVerifyBackupSet,
} from "../../lib/backupMutations"
import { Badge, Button, Input, Select, Switch } from "../ui/primitives"
import {
  Callout,
  EmptyState,
  Field,
  Segmented,
  StatusDot,
} from "../ui/display"
import { formatClock, formatRelative } from "../../lib/format"

/**
 * 备份策略与恢复包。
 *
 * 四个契约事实决定了这个面板的形状，而它们都属于「编辑器静默做错事」而不是
 * 「编辑器报错」这一类：
 *
 * 1. **`{}` 不是「没有配置」，而是「关闭」。** `schedule` / `retention` /
 *    `repository_check_schedule` 在 PATCH 里是整体替换（`service.py:389,398,411`），
 *    而 `{}` 是合法值、含义是「不再按计划运行」（`service.py:49-50`）。所以清空
 *    cron 框必须被当作一次**明确的取消调度**来说明，而不是让它看起来像没改东西；
 *    `buildSchedule` 返回 `{}` 正是这个选择的载体。
 * 2. **凭据是只写的。** 读模型只有 `repository_configured` /
 *    `credentials_configured`（`backups/schemas.py:64-75`），所以编辑器用
 *    保留 / 替换 / 清空三态。`credentials_action: "clear"` 是全页最锋利的一刀：
 *    第二次调用会成功且什么都不做（`service.py:574-597`），策略从此永远跑不了，
 *    而界面上看不出与健康策略的区别。
 * 3. **`POST /backups/run` 返回 202 和排队行，不是结果。** 行先落库再入队
 *    （`backups/api.py:403-412`），所以 503 配 `details.backup_persisted: true`
 *    意味着「备份已存在、稍后会跑」。页面照抄这个措辞，并且不提供自动重试。
 * 4. **恢复包是响应体，不是 URL。** 归档以 `application/octet-stream` 返回
 *    （`recovery_kit.py:619-623`），浏览器无法导航过去，只能取回字节再走 blob
 *    下载。而且它**无法作废**、口令也不会被保存——这两条后果必须在按下按钮之前
 *    说，而不是在成功提示里补一句。
 */

/** The system zone, for a schedule the operator has not overridden. */
const FALLBACK_TIMEZONE = "UTC"

function systemTimezone(data: { general?: { display_timezone?: string } } | undefined) {
  return data?.general?.display_timezone || FALLBACK_TIMEZONE
}

function formatBytes(bytes: number | null): string {
  if (bytes === null) return "—"
  if (bytes < 1024) return `${bytes} B`
  const units = ["KB", "MB", "GB", "TB"]
  let value = bytes / 1024
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value.toFixed(1)} ${units[unit]}`
}

export function BackupPanel() {
  const settings = useSystemSettings()
  const policies = useBackupPolicies()
  const timezone = systemTimezone(settings.data)

  const [editing, setEditing] = useState<BackupPolicyView | "create" | null>(null)

  const list = policies.data ?? []
  /** The recovery kit is per policy, so it needs one to ask about. */
  const kitPolicyId = list[0]?.id ?? null

  return (
    <div className="space-y-5">
      {/* ------------------------------------------------------ policies */}
      <section>
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold">备份策略</h3>
          <Button size="sm" onClick={() => setEditing("create")}>
            <Plus /> 新建策略
          </Button>
        </div>

        {policies.isPending ? (
          <p className="mt-2 text-xs text-muted-foreground">读取中…</p>
        ) : policies.error ? (
          <div className="mt-2">
            <Callout tone="offline" title="无法读取备份策略">
              {policies.error.message}
            </Callout>
          </div>
        ) : list.length === 0 ? (
          <div className="mt-2">
            <EmptyState
              icon={<DatabaseBackup />}
              title="还没有备份策略"
              description="没有策略就不会有备份。建一条策略，指定仓库与定时计划后才会开始产出快照。"
            />
          </div>
        ) : (
          <ul className="mt-2 space-y-2" aria-label="备份策略列表">
            {list.map((policy) => (
              <PolicyRow
                key={policy.id}
                policy={policy}
                onEdit={() => setEditing(policy)}
              />
            ))}
          </ul>
        )}
      </section>

      {editing && (
        <PolicyEditor
          policy={editing === "create" ? undefined : editing}
          timezone={timezone}
          onClose={() => setEditing(null)}
        />
      )}

      {/* ----------------------------------------------------- backup sets */}
      <BackupSetList policies={list} />

      {/* -------------------------------------------------- recovery kit */}
      <RecoveryKitSection policyId={kitPolicyId} policies={list} />
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Policy row                                                                 */
/* -------------------------------------------------------------------------- */

function PolicyRow({
  policy,
  onEdit,
}: {
  policy: BackupPolicyView
  onEdit: () => void
}) {
  const run = useRunBackupNow()
  const scheduled = !scheduleIsCleared(policy.schedule)

  return (
    <li className="rounded-lg border border-border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <StatusDot tone={policy.enabled ? "online" : "unknown"} />
        <span className="text-sm font-medium">{policy.name}</span>
        <Badge variant="outline">{policy.database_backend}</Badge>
        {scheduled ? (
          <Badge variant="secondary">
            {policy.schedule.cron} · {policy.schedule.timezone}
          </Badge>
        ) : (
          <Badge variant="muted">未按计划运行</Badge>
        )}
        {!policy.enabled && <Badge variant="warning">已停用</Badge>}

        <div className="ml-auto flex items-center gap-1">
          <Button
            variant="outline"
            size="sm"
            disabled={run.isPending}
            onClick={() => run.mutate({ policy_id: policy.id, reason: "manual" })}
          >
            <Play /> {run.isPending ? "提交中…" : "立即备份"}
          </Button>
          <Button variant="ghost" size="icon-sm" title="编辑" onClick={onEdit}>
            <Pencil className="size-3.5" />
          </Button>
        </div>
      </div>

      <p className="mt-1 text-[11px] text-muted-foreground">
        {policy.repository_configured ? "仓库地址已配置" : "仓库地址未配置"}
        {" · "}
        {policy.credentials_configured ? "凭据已配置" : "凭据未配置"}
        {policy.verify_after_backup && " · 备份后自动校验"}
        {policy.include_deployment_config && " · 包含部署配置"}
      </p>

      {!policy.credentials_configured && (
        <p className="mt-1 text-[11px] text-status-degraded">
          没有凭据的策略无法运行备份。
        </p>
      )}
    </li>
  )
}

/* -------------------------------------------------------------------------- */
/* Policy editor                                                              */
/* -------------------------------------------------------------------------- */

function PolicyEditor({
  policy,
  timezone,
  onClose,
}: {
  policy?: BackupPolicyView
  timezone: string
  onClose: () => void
}) {
  const creating = !policy
  const [form, setForm] = useState<BackupPolicyForm>(() => {
    if (policy) return policyFormFromView(policy, timezone)
    // On create there is no stored secret to keep, and the create body has no
    // "credentials: null" — `BackupPolicyCreate.credentials` is required. A
    // form left on "keep" here would send an empty password and be rejected
    // with a message about a field the operator cannot see.
    return { ...emptyPolicyForm(timezone), credentialsAction: "replace" }
  })
  const [envDraft, setEnvDraft] = useState<{ key: string; value: string }[]>([])

  const create = useCreateBackupPolicy()
  const update = useUpdateBackupPolicy(policy?.id ?? "")

  // Validation runs on the form as it will be **sent**, with the environment
  // rows already folded into the map. Validating the raw form would let a
  // reserved variable name through to the server as a 400 about a field the
  // operator filled in and then watched disappear from the body.
  const submitted: BackupPolicyForm = {
    ...form,
    credentials: {
      ...form.credentials,
      environment: collectEnvironment(form, envDraft),
    },
  }
  const errors = validateBackupPolicyForm(submitted, { creating })

  /**
   * Whether saving will *switch the schedule off* rather than leave it alone.
   *
   * This is the sentence the panel exists to say: the PATCH replaces the whole
   * object and `{}` means "never scheduled", so an emptied cron box is a
   * destructive action dressed as a no-op.
   */
  const unschedules =
    !creating && !scheduleIsCleared(policy!.schedule) && form.schedule.cron.trim() === ""

  const mutate = creating ? create : update

  /**
   * The system zone comes from a separate query, so on a cold page the first
   * render has no zone and both drafts start on the fallback. Fill the real one
   * in when it lands — but only into a zone box the operator has not touched,
   * because a typed zone is theirs and the cron next to it says nothing about
   * whether the zone was deliberate.
   */
  useEffect(() => {
    if (timezone === FALLBACK_TIMEZONE) return
    setForm((f) => {
      const untouched = (d: BackupPolicyForm["schedule"]) =>
        d.timezone === FALLBACK_TIMEZONE
      if (!untouched(f.schedule) && !untouched(f.repositoryCheckSchedule)) return f
      return {
        ...f,
        schedule: untouched(f.schedule) ? { ...f.schedule, timezone } : f.schedule,
        repositoryCheckSchedule: untouched(f.repositoryCheckSchedule)
          ? { ...f.repositoryCheckSchedule, timezone }
          : f.repositoryCheckSchedule,
      }
    })
  }, [timezone])

  function patch<K extends keyof BackupPolicyForm>(key: K, value: BackupPolicyForm[K]) {
    setForm((f) => ({ ...f, [key]: value }))
  }

  function submit() {
    if (errors.length > 0) return
    if (creating) {
      create.mutate(buildBackupPolicyCreate(submitted), { onSuccess: onClose })
      return
    }
    const body = buildBackupPolicyPatch(submitted, {
      name: policy!.name,
      enabled: policy!.enabled,
      verify_after_backup: policy!.verify_after_backup,
      include_deployment_config: policy!.include_deployment_config,
    })
    update.mutate(body, { onSuccess: onClose })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-foreground/40 p-4 pt-16">
      <div className="w-full max-w-lg rounded-lg border border-border bg-background p-4 shadow-lg">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold">
            {creating ? "新建备份策略" : `编辑：${policy!.name}`}
          </h3>
          <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="关闭">
            <X className="size-3.5" />
          </Button>
        </div>

        <div className="mt-2">
          <Field label="名称">
            <Input
              className="w-56"
              value={form.name}
              aria-label="策略名称"
              onChange={(e) => patch("name", e.target.value)}
            />
          </Field>
          <ErrorText error={errors.find((e) => e.field === "name")?.message} />

          <Field label="启用" hint="停用后定时备份不会运行，手动触发仍会被后端拒绝。">
            <Switch
              role="switch"
              aria-checked={form.enabled}
              aria-label="启用该策略"
              onClick={() => patch("enabled", !form.enabled)}
            />
          </Field>

          <Field
            label="数据库类型"
            hint="与当前部署的类型不一致时后端会拒绝修改这条策略。"
          >
            <Select
              className="w-32"
              value={form.databaseBackend}
              aria-label="数据库类型"
              disabled={!creating}
              onChange={(e) =>
                patch("databaseBackend", e.target.value as BackupPolicyForm["databaseBackend"])
              }
            >
              {DATABASE_BACKENDS.map((b) => (
                <option key={b} value={b}>
                  {b}
                </option>
              ))}
            </Select>
          </Field>

          <Field
            label="仓库地址"
            hint={
              creating
                ? "只写字段，保存后无法读回。地址里不能内嵌用户名或密码。"
                : "只写字段。留空表示不改动已存的地址——它无法被清空，只能被替换。"
            }
          >
            <Input
              className="w-72"
              value={form.repository}
              aria-label="仓库地址"
              placeholder="s3:s3.example.com/bucket"
              onChange={(e) => patch("repository", e.target.value)}
            />
          </Field>
          <ErrorText error={errors.find((e) => e.field === "repository")?.message} />

          <CredentialsField
            form={form}
            creating={creating}
            configured={policy?.credentials_configured}
            envDraft={envDraft}
            setEnvDraft={setEnvDraft}
            onPatch={patch}
            error={errors.find((e) => e.field === "credentials")?.message}
          />

          <ScheduleField
            label="备份计划"
            hint="五段 cron（分钟精度），例如 0 3 * * *。留空表示不再按计划运行。"
            draft={form.schedule}
            error={errors.find((e) => e.field === "schedule")?.message}
            unschedules={unschedules}
            onChange={(schedule) => patch("schedule", schedule)}
          />

          <ScheduleField
            label="仓库检查计划"
            hint="用于定期验证仓库可读性的 cron。留空表示不做定期检查。"
            draft={form.repositoryCheckSchedule}
            error={errors.find((e) => e.field === "repositoryCheckSchedule")?.message}
            onChange={(schedule) => patch("repositoryCheckSchedule", schedule)}
          />

          <div className="border-b border-border py-3">
            <p className="text-sm font-medium">保留策略</p>
            <p className="mt-1 text-xs text-muted-foreground">
              每一项都是<strong className="text-foreground">快照份数</strong>
              ，不是时长：填 7 表示保留最近 7 份每日快照。留空表示该项不参与保留。
            </p>
            <div className="mt-2 grid grid-cols-2 gap-2">
              {RETENTION_BUCKETS.map((bucket) => (
                <label key={bucket} className="flex items-center justify-between gap-2">
                  <span className="text-[11px] text-muted-foreground">
                    {RETENTION_BUCKET_LABEL[bucket]}
                  </span>
                  <Input
                    type="number"
                    className="w-20"
                    aria-label={RETENTION_BUCKET_LABEL[bucket]}
                    value={form.retention[bucket] ?? ""}
                    onChange={(e) => {
                      const raw = e.target.value
                      patch("retention", {
                        ...form.retention,
                        [bucket]:
                          raw === "" ? "" : (Number(raw) as number | ""),
                      } as BackupPolicyForm["retention"])
                    }}
                  />
                </label>
              ))}
            </div>
          </div>
          <ErrorText error={errors.find((e) => e.field === "retentionValue")?.message} />

          <Field label="备份后自动校验" hint="校验是异步任务，不影响备份本身的成败。">
            <Switch
              role="switch"
              aria-checked={form.verifyAfterBackup}
              aria-label="备份后自动校验"
              onClick={() => patch("verifyAfterBackup", !form.verifyAfterBackup)}
            />
          </Field>

          <Field label="包含部署配置" hint="把部署相关的环境变量一起打进备份。">
            <Switch
              role="switch"
              aria-checked={form.includeDeploymentConfig}
              aria-label="包含部署配置"
              onClick={() => patch("includeDeploymentConfig", !form.includeDeploymentConfig)}
            />
          </Field>
        </div>

        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose}>
            取消
          </Button>
          <Button size="sm" disabled={errors.length > 0 || mutate.isPending} onClick={submit}>
            {mutate.isPending ? "保存中…" : "保存"}
          </Button>
        </div>
      </div>
    </div>
  )
}

/**
 * Merge the draft environment rows into the form's environment map.
 *
 * Rows are UI-only state; the contract's `buildCredentialEdit` reads the map.
 * A row with a blank key and a blank value is dropped, matching the rule the
 * validator applies.
 */
function collectEnvironment(
  form: BackupPolicyForm,
  rows: { key: string; value: string }[],
): Record<string, string> {
  if (rows.length === 0) return form.credentials.environment
  const merged = { ...form.credentials.environment }
  for (const row of rows) {
    const key = row.key.trim()
    if (key === "" && row.value === "") continue
    if (key === "") continue
    merged[key] = row.value
  }
  return merged
}

/* -------------------------------------------------------------------------- */
/* Credentials — the keep / replace / clear tri-state                         */
/* -------------------------------------------------------------------------- */

/**
 * One write-only secret, with the three states the update schema can express.
 *
 * "Keep" is the only honest initial state on edit: the stored password and
 * environment are unreadable, so there is nothing to pre-fill. "Clear" is the
 * one that cannot be taken back — it is idempotent by silence, so a second
 * attempt succeeds and does nothing while the policy is left permanently
 * unrunnable, and `repository: null` is a 400 rather than a way out
 * (`api.py:238-244`). The consequence is stated next to the choice, not after.
 */
function CredentialsField({
  form,
  creating,
  configured,
  envDraft,
  setEnvDraft,
  onPatch,
  error,
}: {
  form: BackupPolicyForm
  creating: boolean
  configured?: boolean
  envDraft: { key: string; value: string }[]
  setEnvDraft: React.Dispatch<React.SetStateAction<{ key: string; value: string }[]>>
  onPatch: <K extends keyof BackupPolicyForm>(
    key: K,
    value: BackupPolicyForm[K],
  ) => void
  error?: string
}) {
  const action = form.credentialsAction

  return (
    <div
      role="group"
      aria-label="仓库凭据"
      className="border-b border-border py-3"
    >
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">仓库凭据</span>
        <span className="text-[11px] text-muted-foreground">
          {action === "clear" ? "将清空" : action === "replace" ? "将替换" : configured ? "已配置" : "未配置"}
        </span>
      </div>

      {creating ? (
        <p className="mt-1 text-[10px] text-muted-foreground">
          新建策略必须填写仓库密码，保存后无法读回。
        </p>
      ) : (
        <Segmented
          className="mt-1.5"
          ariaLabel="仓库凭据处理方式"
          value={action}
          onChange={(v) => onPatch("credentialsAction", v as SecretAction)}
          options={[
            { value: "keep", label: "保持不变" },
            { value: "replace", label: "替换" },
            { value: "clear", label: "清空" },
          ]}
        />
      )}

      {action === "replace" && (
        <div className="mt-2 space-y-1.5">
          <Input
            type="password"
            value={form.credentials.password}
            aria-label="仓库密码"
            placeholder="仓库密码"
            onChange={(e) =>
              onPatch("credentials", {
                ...form.credentials,
                password: e.target.value,
              })
            }
          />
          {envDraft.map((row, i) => (
            <div key={i} className="flex items-center gap-1.5">
              <Input
                className="w-40"
                value={row.key}
                aria-label={`环境变量名 ${i + 1}`}
                placeholder="AWS_ACCESS_KEY_ID"
                onChange={(e) => {
                  const next = [...envDraft]
                  next[i] = { ...row, key: e.target.value }
                  setEnvDraft(next)
                }}
              />
              <Input
                className="flex-1"
                type="password"
                value={row.value}
                aria-label={`环境变量值 ${i + 1}`}
                onChange={(e) => {
                  const next = [...envDraft]
                  next[i] = { ...row, value: e.target.value }
                  setEnvDraft(next)
                }}
              />
              <Button
                variant="ghost"
                size="icon-sm"
                title={`删除环境变量 ${i + 1}`}
                onClick={() => setEnvDraft(envDraft.filter((_, j) => j !== i))}
              >
                <X className="size-3.5" />
              </Button>
            </div>
          ))}
          <Button
            variant="outline"
            size="sm"
            onClick={() => setEnvDraft([...envDraft, { key: "", value: "" }])}
          >
            <Plus /> 添加环境变量
          </Button>
          <p className="text-[10px] text-muted-foreground">
            RESTIC_REPOSITORY、RESTIC_PASSWORD、RESTIC_PASSWORD_FILE 由其它字段生成，不能手工填写。环境变量会整份替换已存的字典，所以要把现有的一并填回。
          </p>
        </div>
      )}

      {action === "clear" && (
        <p className="mt-2 text-[11px] text-status-offline">
          清空后该策略将永远无法运行备份，也没有恢复已存密码的办法。再次执行同一步会成功但不改变任何东西。
        </p>
      )}

      {error && <p className="mt-1.5 text-[11px] text-status-offline">{error}</p>}
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Schedule                                                                   */
/* -------------------------------------------------------------------------- */

function ScheduleField({
  label,
  hint,
  draft,
  error,
  unschedules,
  onChange,
}: {
  label: string
  hint: string
  draft: BackupPolicyForm["schedule"]
  error?: string
  unschedules?: boolean
  onChange: (draft: BackupPolicyForm["schedule"]) => void
}) {
  return (
    <div role="group" aria-label={label} className="border-b border-border py-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">{label}</span>
        <span className="text-[11px] text-muted-foreground">
          {scheduleIsCleared(buildSchedule(draft)) ? "不按计划运行" : "已设置"}
        </span>
      </div>

      <div className="mt-1.5 flex items-center gap-2">
        <Input
          className="w-36"
          value={draft.cron}
          aria-label={`${label} cron`}
          placeholder="0 3 * * *"
          onChange={(e) => onChange({ ...draft, cron: e.target.value })}
        />
        <Input
          className="w-44"
          value={draft.timezone}
          aria-label={`${label} 时区`}
          placeholder="Asia/Shanghai"
          onChange={(e) => onChange({ ...draft, timezone: e.target.value })}
        />
      </div>

      <p className="mt-1 text-[10px] text-muted-foreground">{hint}</p>

      {unschedules && (
        <p className="mt-1.5 text-[11px] text-status-degraded">
          保存后该策略将不再按计划运行：清空 cron 会发送空的 schedule 对象，这是关闭调度的唯一方式。
        </p>
      )}

      {error && <p className="mt-1.5 text-[11px] text-status-offline">{error}</p>}
    </div>
  )
}

function ErrorText({ error }: { error?: string }) {
  if (!error) return null
  return <p className="pb-1 text-[11px] text-status-offline">{error}</p>
}

/* -------------------------------------------------------------------------- */
/* Backup sets — cursor paged, never a page number                             */
/* -------------------------------------------------------------------------- */

const PAGE_SIZE = 20

/**
 * The backup set list.
 *
 * `GET /backups` is a cursor-paged list with no total count anywhere in the
 * contract (`api.py:324-327`), so "page 2" is not a thing this panel can say —
 * it walks `next_cursor` forwards and says nothing about how many there are in
 * total. A row's detail comes from the list response because there is no detail
 * route at all.
 */
function BackupSetList({ policies }: { policies: BackupPolicyView[] }) {
  const [policyFilter, setPolicyFilter] = useState("")
  const [cursors, setCursors] = useState<string[]>([])

  const cursor = cursors[cursors.length - 1]
  const filters = useMemo(
    () => ({ policyId: policyFilter || undefined, cursor, limit: PAGE_SIZE }),
    [policyFilter, cursor],
  )
  const sets = useBackupSets(filters)

  const items = sets.data?.items ?? []
  const nextCursor = sets.data?.next_cursor ?? null

  function resetCursors() {
    setCursors([])
  }

  return (
    <section>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">备份记录</h3>
        <div className="flex items-center gap-2">
          <Select
            className="w-44"
            value={policyFilter}
            aria-label="按策略筛选备份记录"
            onChange={(e) => {
              setPolicyFilter(e.target.value)
              resetCursors()
            }}
          >
            <option value="">全部策略</option>
            {policies.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </Select>
        </div>
      </div>

      <p className="mt-0.5 text-[11px] text-muted-foreground">
        备份由后台任务执行，入队即返回排队行，实际结果要等任务跑完才会变。
      </p>

      {sets.isPending ? (
        <p className="mt-2 text-xs text-muted-foreground">读取中…</p>
      ) : sets.error ? (
        <div className="mt-2">
          <Callout tone="offline" title="无法读取备份记录">
            {sets.error.message}
          </Callout>
        </div>
      ) : items.length === 0 ? (
        <p className="mt-2 rounded-lg border border-dashed border-border px-3 py-4 text-center text-xs text-muted-foreground">
          这一页没有备份记录
        </p>
      ) : (
        <>
          <ul
            className="mt-2 divide-y divide-border rounded-lg border border-border"
            aria-label="备份记录列表"
          >
            {items.map((b) => (
              <BackupSetRow key={b.id} backup={b} policyName={policyName(policies, b)} />
            ))}
          </ul>
          <div className="mt-2 flex items-center gap-2">
            {cursors.length > 0 && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => setCursors(cursors.slice(0, -1))}
              >
                上一页
              </Button>
            )}
            {nextCursor && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => setCursors([...cursors, nextCursor])}
              >
                下一页
              </Button>
            )}
          </div>
        </>
      )}
    </section>
  )
}

function policyName(policies: BackupPolicyView[], backup: BackupSetView): string {
  return policies.find((p) => p.id === backup.backup_policy_id)?.name ?? "未知策略"
}

function BackupSetRow({
  backup,
  policyName,
}: {
  backup: BackupSetView
  policyName: string
}) {
  const verify = useVerifyBackupSet()
  const verifiable = isVerifiable(backup)

  return (
    <li className="flex flex-wrap items-center gap-3 px-3 py-2">
      <StatusDot tone={backupStateTone(backup.state)} />
      <div className="min-w-0 flex-1">
        <p className="truncate text-xs font-medium">
          {policyName} · {describeBackupReason(backup.reason)}
        </p>
        <p className="mt-0.5 text-[10px] text-muted-foreground">
          {backup.app_version} · {formatBytes(backup.size_bytes)}
          {backup.verification_state && backup.verification_state !== "unknown"
            ? ` · 校验：${backup.verification_state}`
            : ""}
          {backup.restic_snapshot_id ? "" : " · 无快照"}
        </p>
        {backup.error_code && (
          <p className="mt-0.5 font-mono text-[10px] text-status-offline">
            {backup.error_code}
            {backup.sanitized_error ? ` ${backup.sanitized_error}` : ""}
          </p>
        )}
      </div>
      <span
        className="shrink-0 text-[10px] text-muted-foreground"
        title={formatClock(backup.created_at)}
      >
        {formatRelative(backup.created_at)}
      </span>
      <span className="w-16 shrink-0 text-right text-[10px] text-muted-foreground">
        {BACKUP_STATE_LABEL[backup.state]}
      </span>
      <Button
        variant="outline"
        size="sm"
        disabled={!verifiable || verify.isPending}
        title={verifiable ? "校验" : "只有已完成且有快照的备份才能校验"}
        onClick={() => verify.mutate(backup.id)}
      >
        {verifiable ? "校验" : "不可校验"}
      </Button>
    </li>
  )
}

/* -------------------------------------------------------------------------- */
/* Recovery kit — the sharpest edge on the page                                */
/* -------------------------------------------------------------------------- */

/**
 * 恢复包。
 *
 * The consequences are stated **before** the button, because both of them are
 * irreversible and neither has a UI moment afterwards: a generated kit cannot
 * be revoked — nothing in the system can invalidate a copy that has already
 * left — and the passphrase is never stored, so a lost passphrase means a lost
 * kit. The download is also a one-shot response body, so losing it before
 * saving is unrecoverable; there is no link to re-fetch.
 */
function RecoveryKitSection({
  policyId,
  policies,
}: {
  policyId: string | null
  policies: BackupPolicyView[]
}) {
  const status = useRecoveryKitStatus(policyId)
  const generate = useGenerateRecoveryKit()
  const [passphrase, setPassphrase] = useState("")
  const [target, setTarget] = useState(policyId ?? "")

  const effectiveTarget = target || policyId || ""
  const passphraseBytes = new TextEncoder().encode(passphrase).length
  const tooShort =
    passphrase !== "" && passphraseBytes < RECOVERY_PASSPHRASE_MIN

  function download(blob: Blob, filename: string | null) {
    // The archive arrives as the response body of a POST, so the browser cannot
    // navigate to it and there is no URL to hand the operator. Create an object
    // URL, click a synthetic anchor, then revoke it (`recovery_kit.py:619-623`).
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement("a")
    anchor.href = url
    anchor.download = filename ?? "recovery-kit.znrk"
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    URL.revokeObjectURL(url)
  }

  return (
    <section>
      <div className="flex items-center justify-between">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold">
          <ShieldCheck className="size-4 text-muted-foreground" />
          恢复包
        </h3>
        {status.data && (
          <span className="text-[11px] text-muted-foreground">
            {RECOVERY_KIT_STATUS_LABEL[status.data.status]}
            {status.data.generated_at
              ? ` · ${formatRelative(status.data.generated_at)}`
              : ""}
          </span>
        )}
      </div>

      {/* Consequences first, always. */}
      <div className="mt-2 space-y-2">
        <Callout tone="degraded" title="恢复包无法作废">
          恢复包里包含 ZERO_NVR_SECRET_KEY、ZLM 与 TURN 共享密钥、含密码的数据库连接串，
          以及全部 restic 凭据，用 scrypt + AES-256-GCM 加密。生成之后没有任何办法让它失效——
          已经离开系统的副本无法被收回。口令不会被保存，忘了口令就等于永久失去这个恢复包。
        </Callout>

        <div className="flex flex-wrap items-center gap-2">
          <Select
            className="w-44"
            value={effectiveTarget}
            aria-label="恢复包对应策略"
            onChange={(e) => setTarget(e.target.value)}
          >
            {policies.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </Select>
          <Input
            className="w-64"
            type="password"
            value={passphrase}
            aria-label="恢复包口令"
            placeholder={`至少 ${RECOVERY_PASSPHRASE_MIN} 个字符`}
            onChange={(e) => setPassphrase(e.target.value)}
          />
          <Button
            size="sm"
            disabled={
              !effectiveTarget ||
              tooShort ||
              passphrase.trim() === "" ||
              generate.isPending
            }
            onClick={() =>
              generate.mutate(
                { policy_id: effectiveTarget, passphrase },
                {
                  onSuccess: (data) => {
                    download(data.blob, data.filename)
                    setPassphrase("")
                  },
                },
              )
            }
          >
            <HardDriveDownload /> {generate.isPending ? "生成中…" : "生成并下载"}
          </Button>
        </div>

        {tooShort && (
          <p className="text-[11px] text-status-offline">
            口令至少 {RECOVERY_PASSPHRASE_MIN} 个字符（按 UTF-8 字节计）。
          </p>
        )}
        {policies.length === 0 && (
          <p className="text-[11px] text-muted-foreground">
            需要至少一条备份策略才能生成恢复包。
          </p>
        )}
        <p className="text-[10px] text-muted-foreground">
          下载是一次性响应：没有二次下载入口，保存前丢失无法重新获取。
        </p>
      </div>
    </section>
  )
}
