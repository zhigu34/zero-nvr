/**
 * Backup policy and recovery kit contract. Mirrors
 * `backend/app/modules/backups/{api,schemas,service,recovery_kit}.py`.
 *
 * ## A 503 from "run" means the backup already exists and will run
 *
 * `POST /backups/run` commits the row, *then* enqueues (`api.py:403-412`). If
 * the queue is unavailable the response is 503 with
 * `details.backup_persisted === true` and a `backup_id`. That is the G-17/G-23
 * pattern again: "nothing happened" and "it happened and we could not tell you"
 * are different states, and treating the 503 as a failure invites a retry that
 * creates a second backup set. `runPersistedAnyway` is the discriminator.
 *
 * ## The list route has no trailing slash and there is no detail route
 *
 * `@router.get("")` on `prefix="/backups"` (`api.py:324-327`) means the path is
 * exactly `/api/v1/backups`. There is no `GET /backups/{id}`, no policy delete,
 * no cancel, no restore, and no download. A page that wants a row's detail has
 * to keep it from the list response.
 *
 * ## Empty objects disable, they do not validate
 *
 * `schedule`, `retention` and `repository_check_schedule` are each replaced
 * wholesale when present (`service.py:389,398,411`), and `{}` is a **legal
 * value meaning "cleared"** (`service.py:49-50`). So a form that sends
 * `schedule: {}` because the operator emptied the cron field has silently
 * unscheduled the policy — with a 200. `scheduleIsCleared` exists so the form
 * can say that out loud instead.
 *
 * ## Credentials merge per field, and the environment half does not
 *
 * On PATCH, a missing `password` falls back to the stored one — but a missing
 * `environment` falls back to the **whole current dict**
 * (`service.py:507-514`). Sending `environment: {AWS_ACCESS_KEY_ID: "..."}`
 * therefore discards every other variable. `buildCredentialEdit` always sends
 * the complete environment, so this cannot happen from the form.
 *
 * `credentials_action: "clear"` is the sharp edge: it deletes the secret, is
 * **idempotent by silence** — a second call succeeds and does nothing
 * (`service.py:574-597`) — and leaves the policy permanently unrunnable with no
 * way to tell that from a healthy one. `repository: null` is not a way out: it
 * is a 400 (`api.py:238-244`).
 *
 * ## The recovery kit is a response body, not a URL
 *
 * `POST /backups/recovery-kit` streams the archive as
 * `application/octet-stream` with `Content-Disposition: attachment`
 * (`recovery_kit.py:619-623`). A browser cannot navigate to it — it needs a POST
 * with a JSON body, so the client must fetch the bytes and hand them to a blob
 * download. There is no one-time link and no token.
 *
 * It contains `ZERO_NVR_SECRET_KEY`, the ZLM/TURN shared secrets, the database
 * URL with its password inline, and every restic credential
 * (`recovery_kit.py:542-560`), encrypted with scrypt + AES-256-GCM. **A
 * generated kit cannot be revoked** — nothing in the system can invalidate a
 * copy that has already left. The page says so before the button, not after.
 */
import { api, ApiError } from "./client"

/* -------------------------------------------------------------------------- */
/* Wire shapes                                                                */
/* -------------------------------------------------------------------------- */

export type BackupSchedule = {
  /** Five fields, minute resolution. No seconds field. */
  cron: string
  /** IANA name, resolved with `ZoneInfo`. */
  timezone: string
}

/**
 * Snapshot **counts**, not durations.
 *
 * `keep_daily: 7` means "keep the last 7 daily snapshots", not "keep 7 days".
 * Values are ints 0–10000 and a `bool` is rejected outright
 * (`service.py:92-123`) — which matters because `true` is `1` in JavaScript and
 * a `<input type="number">` hands back a number, not a boolean.
 */
export type BackupRetention = {
  keep_last?: number
  keep_hourly?: number
  keep_daily?: number
  keep_weekly?: number
  keep_monthly?: number
  keep_yearly?: number
}

export const RETENTION_BUCKETS = [
  "keep_last",
  "keep_hourly",
  "keep_daily",
  "keep_weekly",
  "keep_monthly",
  "keep_yearly",
] as const

export type RetentionBucket = (typeof RETENTION_BUCKETS)[number]

export const RETENTION_BUCKET_LABEL: Record<RetentionBucket, string> = {
  keep_last: "最近 N 份",
  keep_hourly: "每小时 N 份",
  keep_daily: "每天 N 份",
  keep_weekly: "每周 N 份",
  keep_monthly: "每月 N 份",
  keep_yearly: "每年 N 份",
}

export const RETENTION_MAX = 10_000

export type BackupCredentialsInput = {
  password: string
  environment?: Record<string, string>
}

export type DatabaseBackend = "sqlite" | "postgresql"

export const DATABASE_BACKENDS: DatabaseBackend[] = ["sqlite", "postgresql"]

export type BackupPolicyView = {
  id: string
  name: string
  enabled: boolean
  database_backend: DatabaseBackend
  /** `{}` means "never scheduled" — not "no schedule configured". */
  schedule: Partial<BackupSchedule>
  retention: BackupRetention
  verify_after_backup: boolean
  repository_check_schedule: Partial<BackupSchedule>
  include_deployment_config: boolean
  repository_configured: boolean
  credentials_configured: boolean
  /**
   * `initialize_if_missing` is accepted on write and appears in **no**
   * response (`schemas.py:64-75`). The form keeps it as local state and never
   * pretends to read it back.
   */
}

export type BackupPolicyCreate = {
  name: string
  enabled?: boolean
  repository: string
  credentials: BackupCredentialsInput
  initialize_if_missing?: boolean
  database_backend: DatabaseBackend
  schedule?: Partial<BackupSchedule>
  retention?: BackupRetention
  repository_check_schedule?: Partial<BackupSchedule>
  verify_after_backup?: boolean
  include_deployment_config?: boolean
}

export type SecretAction = "keep" | "replace" | "clear"

export type BackupPolicyUpdate = {
  name?: string
  enabled?: boolean
  repository?: string
  credentials_action?: SecretAction
  credentials?: BackupCredentialsInput | null
  initialize_if_missing?: boolean
  /** Whole-object replace when present; `{}` clears. */
  schedule?: Partial<BackupSchedule>
  retention?: BackupRetention
  repository_check_schedule?: Partial<BackupSchedule>
  verify_after_backup?: boolean
  include_deployment_config?: boolean
}

export type BackupState = "PENDING" | "RUNNING" | "COMPLETED" | "FAILED"
export const BACKUP_STATES: BackupState[] = [
  "PENDING",
  "RUNNING",
  "COMPLETED",
  "FAILED",
]

/**
 * `reason` is an open `str` in the response even though the request enum has
 * four values — the scheduler writes `"scheduled"`
 * (`worker/tasks.py:1489`), a value no client can send.
 */
export type BackupRunReason =
  | "manual"
  | "pre_upgrade"
  | "pre_restore"
  | "pre_database_migration"

export type BackupRunRequest = {
  policy_id: string
  reason?: BackupRunReason
}

export type BackupSetView = {
  id: string
  backup_policy_id: string
  state: BackupState
  reason: string | null
  started_at: string | null
  completed_at: string | null
  app_version: string
  schema_revision: string
  database_engine: string
  restic_snapshot_id: string | null
  size_bytes: number | null
  verification_state: string
  last_verified_at: string | null
  error_code: string | null
  sanitized_error: string | null
  created_at: string
}

export type BackupSetPage = {
  items: BackupSetView[]
  next_cursor: string | null
}

export type BackupListFilters = {
  policyId?: string
  state?: BackupState
  cursor?: string
  limit?: number
}

export type RecoveryKitStatus = "never_generated" | "current" | "stale"

export type RecoveryKitStatusView = {
  status: RecoveryKitStatus
  policy_id: string
  generated_at: string | null
  app_version: string
}

export type RecoveryKitRequest = {
  policy_id: string
  /** Min 16 characters at the schema, min 16 UTF-8 **bytes** at the service. */
  passphrase: string
}

export const RECOVERY_PASSPHRASE_MIN = 16

/* -------------------------------------------------------------------------- */
/* Endpoints                                                                  */
/* -------------------------------------------------------------------------- */

export function listBackupPolicies(signal?: AbortSignal) {
  return api.get<BackupPolicyView[]>("/backups/policies", signal)
}

export function getBackupPolicy(policyId: string, signal?: AbortSignal) {
  return api.get<BackupPolicyView>(`/backups/policies/${policyId}`, signal)
}

export function createBackupPolicy(body: BackupPolicyCreate) {
  return api.post<BackupPolicyView>("/backups/policies", body)
}

export function updateBackupPolicy(
  policyId: string,
  body: BackupPolicyUpdate,
) {
  return api.patch<BackupPolicyView>(`/backups/policies/${policyId}`, body)
}

/** Cursor-paged. An unknown `policy_id` yields an empty page, not a 404. */
export function listBackupSets(
  filters: BackupListFilters = {},
  signal?: AbortSignal,
) {
  const qs = new URLSearchParams()
  if (filters.policyId) qs.set("policy_id", filters.policyId)
  if (filters.state) qs.set("state", filters.state)
  if (filters.cursor) qs.set("cursor", filters.cursor)
  qs.set("limit", String(filters.limit ?? 50))
  return api.get<BackupSetPage>(`/backups?${qs}`, signal)
}

/** 202 with the PENDING row — not the outcome. */
export function runBackupNow(body: BackupRunRequest) {
  return api.post<BackupSetView>("/backups/run", body)
}

/** 202. Re-entrant; a non-COMPLETED set answers 409, not 404. */
export function verifyBackupSet(backupId: string) {
  return api.post<{ id: string; verification_state: string }>(
    `/backups/${backupId}/verify`,
  )
}

/** `policy_id` is a required **query** parameter here, not a path segment. */
export function getRecoveryKitStatus(
  policyId: string,
  signal?: AbortSignal,
) {
  return api.get<RecoveryKitStatusView>(
    `/backups/recovery-kit/status?policy_id=${encodeURIComponent(policyId)}`,
    signal,
  )
}

/**
 * Returns the archive bytes. Not a navigable URL — see the module note.
 *
 * The passphrase is sent as JSON and never stored; the kit is encrypted with it
 * and there is no recovery path if it is lost.
 */
export function generateRecoveryKit(
  body: RecoveryKitRequest,
  signal?: AbortSignal,
) {
  return api.postBlob("/backups/recovery-kit", body, signal)
}

/* -------------------------------------------------------------------------- */
/* The 503 that means "it worked"                                            */
/* -------------------------------------------------------------------------- */

/**
 * Whether a failed `POST /backups/run` still created a backup that will run.
 *
 * The row is committed before the enqueue, so a 503 carries
 * `details.backup_persisted: true` and a `backup_id`. Reporting that as a
 * failure is how a retry ends up running the same backup twice.
 */
export function runPersistedAnyway(error: unknown): {
  persisted: true
  backupId: string | null
} | null {
  if (!(error instanceof ApiError)) return null
  if (error.details?.backup_persisted !== true) return null
  const id = error.details.backup_id
  return { persisted: true, backupId: typeof id === "string" ? id : null }
}

/* -------------------------------------------------------------------------- */
/* Deriving state from the three schedule objects                             */
/* -------------------------------------------------------------------------- */

export type ScheduleDraft = { cron: string; timezone: string }

/**
 * A schedule object is "off" when it is empty, and that is a legal state.
 *
 * `{}` on the wire means the policy never runs on a schedule
 * (`service.py:49-50`). When present, an object must have exactly the keys
 * `{cron, timezone}` (`service.py:51-56`) — a stray key is a 400.
 */
export function scheduleIsCleared(
  schedule: Partial<BackupSchedule> | undefined,
): boolean {
  return !schedule || Object.keys(schedule).length === 0
}

export function scheduleDraft(
  schedule: Partial<BackupSchedule> | undefined,
  fallbackTimezone: string,
): ScheduleDraft {
  if (scheduleIsCleared(schedule)) {
    return { cron: "", timezone: fallbackTimezone }
  }
  return {
    cron: schedule?.cron ?? "",
    timezone: schedule?.timezone ?? fallbackTimezone,
  }
}

/**
 * Build the wire object for a schedule, or `{}` to clear it.
 *
 * Returning `{}` — rather than omitting the key — is what actually unschedules
 * the policy, so the caller has to be able to express that choice explicitly.
 */
export function buildSchedule(draft: ScheduleDraft): Partial<BackupSchedule> {
  const cron = draft.cron.trim()
  if (cron === "") return {}
  return { cron, timezone: draft.timezone.trim() }
}

export function retentionIsCleared(retention: BackupRetention | undefined) {
  return !retention || Object.keys(retention).length === 0
}

/* -------------------------------------------------------------------------- */
/* Build body                                                                 */
/* -------------------------------------------------------------------------- */

export type BackupPolicyForm = {
  name: string
  enabled: boolean
  databaseBackend: DatabaseBackend
  repository: string
  /** Local only — never read back from the server. */
  initializeIfMissing: boolean
  schedule: ScheduleDraft
  repositoryCheckSchedule: ScheduleDraft
  /**
   * `number | ""` on purpose: this is draft state read straight off
   * `<input type="number">`, which yields `""` for an empty box. The wire
   * type is `BackupRetention` (numbers only) — `buildRetention` is what
   * drops the empties.
   */
  retention: Partial<Record<RetentionBucket, number | "">>
  verifyAfterBackup: boolean
  includeDeploymentConfig: boolean
  credentialsAction: SecretAction
  /** Write-only; the server keeps only `credentials_configured`. */
  credentials: { password: string; environment: Record<string, string> }
}

export type BackupFormField =
  | "name"
  | "repository"
  | "credentials"
  | "schedule"
  | "repositoryCheckSchedule"
  | "retention"
  | "retentionValue"

export type BackupFormError = { field: BackupFormField; message: string }

/** Reserved because the server derives them from the other fields. */
export const RESERVED_ENV_KEYS = [
  "RESTIC_REPOSITORY",
  "RESTIC_PASSWORD",
  "RESTIC_PASSWORD_FILE",
] as const

const ENV_KEY_PATTERN = /^[A-Z][A-Z0-9_]{0,127}$/

export function validateBackupPolicyForm(
  form: BackupPolicyForm,
  opts: { creating: boolean },
): BackupFormError[] {
  const errors: BackupFormError[] = []

  if (form.name.trim() === "") {
    errors.push({ field: "name", message: "请填写策略名称" })
  } else if (form.name.trim().length > 128) {
    errors.push({ field: "name", message: "名称最长 128 个字符" })
  }

  if (opts.creating || form.repository.trim() !== "") {
    const repository = form.repository.trim()
    if (repository === "") {
      errors.push({ field: "repository", message: "请填写备份仓库地址" })
    } else {
      if (repository.length > 4096) {
        errors.push({ field: "repository", message: "仓库地址过长" })
      }
      if (/[\r\n\0]/.test(repository)) {
        errors.push({
          field: "repository",
          message: "仓库地址不能包含换行或空字符",
        })
      }
      // Userinfo in the URL would be a second, unrevokable copy of the
      // credential (`service.py:151-156`).
      try {
        const url = new URL(repository)
        if (url.username || url.password) {
          errors.push({
            field: "repository",
            message: "地址里不能内嵌用户名或密码，请用下方凭据填写",
          })
        }
      } catch {
        if (!repository.startsWith("s3:")) {
          errors.push({ field: "repository", message: "仓库地址无法解析" })
        }
      }
    }
  }

  if (form.credentialsAction === "replace") {
    if (form.credentials.password === "") {
      errors.push({ field: "credentials", message: "请填写仓库密码" })
    }
    for (const [key, value] of Object.entries(form.credentials.environment)) {
      if (key === "" && value === "") continue
      if (!ENV_KEY_PATTERN.test(key)) {
        errors.push({
          field: "credentials",
          message: `环境变量名「${key}」只能是大写字母、数字和下划线，且以字母开头`,
        })
      } else if ((RESERVED_ENV_KEYS as readonly string[]).includes(key)) {
        errors.push({
          field: "credentials",
          message: `${key} 由其它字段生成，不能手工填写`,
        })
      } else if (value.length > 8192) {
        errors.push({
          field: "credentials",
          message: `${key} 的值过长（上限 8192 字符）`,
        })
      }
    }
  }

  for (const field of ["schedule", "repositoryCheckSchedule"] as const) {
    const draft = form[field]
    if (draft.cron.trim() === "") continue
    if (draft.timezone.trim() === "") {
      errors.push({ field, message: "填写 cron 时必须同时指定时区" })
    }
  }

  for (const bucket of RETENTION_BUCKETS) {
    const value = form.retention[bucket]
    if (value === undefined || value === "") continue
    if (
      typeof value !== "number" ||
      !Number.isInteger(value) ||
      value < 0 ||
      value > RETENTION_MAX
    ) {
      errors.push({
        field: "retentionValue",
        message: `${RETENTION_BUCKET_LABEL[bucket]} 需为 0–${RETENTION_MAX} 的整数`,
      })
    }
  }

  return errors
}

/**
 * Build the credential half of a PATCH.
 *
 * The environment is always sent whole. The server falls back to the stored
 * dict when the key is absent, so sending one variable would delete the rest —
 * and the stored environment is unreadable, so the form cannot have re-read
 * them to begin with. This is the read-merge-write rule from `mergeMatch`,
 * with a twist: the "read" is impossible, so the "merge" is whatever the
 * operator typed in full.
 */
export function buildCredentialEdit(form: BackupPolicyForm): {
  credentials_action: SecretAction
  credentials?: BackupCredentialsInput | null
} {
  if (form.credentialsAction === "keep") return { credentials_action: "keep" }
  if (form.credentialsAction === "clear") {
    return { credentials_action: "clear", credentials: null }
  }
  const environment: Record<string, string> = {}
  for (const [key, value] of Object.entries(form.credentials.environment)) {
    if (key.trim() === "" && value === "") continue
    environment[key.trim()] = value
  }
  return {
    credentials_action: "replace",
    credentials: { password: form.credentials.password, environment },
  }
}

export function buildRetention(
  form: BackupPolicyForm,
): BackupRetention {
  const retention: BackupRetention = {}
  for (const bucket of RETENTION_BUCKETS) {
    const value = form.retention[bucket]
    if (value === undefined || value === "") continue
    retention[bucket] = value
  }
  return retention
}

/* -------------------------------------------------------------------------- */
/* Form factories                                                             */
/* -------------------------------------------------------------------------- */

/**
 * A blank policy form.
 *
 * The schedule drafts start with a usable timezone rather than an empty string
 * so the common case — "type a cron, keep the system zone" — needs no extra
 * click, and so `buildSchedule` has somewhere to read it from.
 */
export function emptyPolicyForm(timezone: string): BackupPolicyForm {
  return {
    name: "",
    enabled: false,
    databaseBackend: "sqlite",
    repository: "",
    // Local only: the server accepts it and never returns it.
    initializeIfMissing: false,
    schedule: { cron: "", timezone },
    repositoryCheckSchedule: { cron: "", timezone },
    retention: {},
    verifyAfterBackup: true,
    includeDeploymentConfig: false,
    // "Keep" is the only honest initial state: the stored repository URL and
    // password are unreadable, so there is nothing to pre-fill.
    credentialsAction: "keep",
    credentials: { password: "", environment: {} },
  }
}

/**
 * Seed the form from a saved policy.
 *
 * Note what is *not* here: the repository, the password and the environment.
 * The view carries only `repository_configured` / `credentials_configured`
 * booleans, so the form starts blank with "keep" selected rather than
 * pre-filling a value the server would reject.
 */
export function policyFormFromView(
  view: BackupPolicyView,
  timezone: string,
): BackupPolicyForm {
  return {
    name: view.name,
    enabled: view.enabled,
    databaseBackend: view.database_backend,
    repository: "",
    initializeIfMissing: false,
    schedule: scheduleDraft(view.schedule, timezone),
    repositoryCheckSchedule: scheduleDraft(view.repository_check_schedule, timezone),
    retention: { ...view.retention },
    verifyAfterBackup: view.verify_after_backup,
    includeDeploymentConfig: view.include_deployment_config,
    credentialsAction: "keep",
    credentials: { password: "", environment: {} },
  }
}

/* -------------------------------------------------------------------------- */
/* Presentation                                                               */
/* -------------------------------------------------------------------------- */

export const BACKUP_STATE_LABEL: Record<BackupState, string> = {
  PENDING: "排队中",
  RUNNING: "执行中",
  COMPLETED: "已完成",
  FAILED: "失败",
}

export type HealthTone = "online" | "degraded" | "offline" | "unknown"

export function backupStateTone(state: string): HealthTone {
  if (state === "COMPLETED") return "online"
  if (state === "FAILED") return "offline"
  if (state === "RUNNING" || state === "PENDING") return "degraded"
  return "unknown"
}

export const RECOVERY_KIT_STATUS_LABEL: Record<RecoveryKitStatus, string> = {
  never_generated: "尚未生成",
  current: "与当前版本一致",
  stale: "已过期",
}

/** A backup set is only verifiable once it completed and produced a snapshot. */
export function isVerifiable(backup: BackupSetView): boolean {
  return backup.state === "COMPLETED" && Boolean(backup.restic_snapshot_id)
}

/** Human note for the `"scheduled"` reason the request enum cannot express. */
export function describeBackupReason(reason: string | null): string {
  if (reason === "scheduled") return "定时触发"
  if (reason === "manual") return "手动触发"
  if (reason === "pre_upgrade") return "升级前"
  if (reason === "pre_restore") return "恢复前"
  if (reason === "pre_database_migration") return "数据库迁移前"
  return reason ?? "未知"
}
