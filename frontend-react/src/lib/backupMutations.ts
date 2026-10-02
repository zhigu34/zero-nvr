import {
  buildCredentialEdit,
  buildRetention,
  buildSchedule,
  runPersistedAnyway,
  type BackupPolicyCreate,
  type BackupPolicyForm,
  type BackupPolicyUpdate,
  type BackupRunRequest,
  type RecoveryKitRequest,
} from "../api/backups"
import {
  createBackupPolicy,
  generateRecoveryKit,
  runBackupNow,
  updateBackupPolicy,
  verifyBackupSet,
  type BackupListFilters,
} from "../api/backups"
import { BACKUPS, RECOVERY_KITS } from "./queries"
import { useSave } from "./save"

/**
 * The bodies are built here rather than in the panels for the same reason the
 * notification credentials are: the parts that are easy to get wrong are
 * "present but empty" versus "absent", and that distinction is a
 * `JSON.stringify` behaviour rather than something a form can express.
 */

export function useCreateBackupPolicy() {
  return useSave<BackupPolicyCreate, unknown>({
    mutationFn: (body) => createBackupPolicy(body),
    invalidates: [BACKUPS.policies, BACKUPS.setList],
    success: () => ({ title: "备份策略已创建" }),
    failure: (error) => ({ title: "创建备份策略失败", detail: describeFailure(error) }),
  })
}

/**
 * `buildBackupPolicyPatch` sends the schedule objects **every time**, because
 * `{}` is the only way to express "never scheduled" and omitting the key means
 * "leave the existing schedule". An editor that sent them only when changed
 * would be unable to unschedule anything.
 */
export function useUpdateBackupPolicy(policyId: string) {
  return useSave<BackupPolicyUpdate, unknown>({
    mutationFn: (body) => updateBackupPolicy(policyId, body),
    invalidates: [BACKUPS.policies, BACKUPS.setList],
    success: () => ({ title: "备份策略已更新" }),
    failure: (error) => ({ title: "更新备份策略失败", detail: describeFailure(error) }),
  })
}

export function useRunBackupNow() {
  return useSave<BackupRunRequest, unknown>({
    mutationFn: (body) => runBackupNow(body),
    invalidates: [BACKUPS.setList],
    success: () => ({
      title: "备份已入队",
      detail: "这是后台任务，返回的是排队状态而不是结果。",
    }),
    failure: (error) => {
      // The row is committed before the enqueue, so a 503 can mean the backup
      // exists and will run. Saying "failed" there invites a retry that runs it
      // twice.
      const persisted = runPersistedAnyway(error)
      if (persisted) {
        return {
          title: "备份已创建，但任务队列不可用",
          detail: `任务队列没能接收这次请求，备份记录已经存在（${persisted.backupId ?? "未知 id"}）并会在队列恢复后由调度器处理。请不要重复触发。`,
        }
      }
      return { title: "触发备份失败", detail: describeFailure(error) }
    },
  })
}

export function useVerifyBackupSet() {
  return useSave<string, unknown>({
    mutationFn: (backupId) => verifyBackupSet(backupId),
    invalidates: [BACKUPS.setList],
    success: () => ({ title: "校验已入队" }),
    failure: (error) => ({ title: "校验失败", detail: describeFailure(error) }),
  })
}

/**
 * The recovery kit.
 *
 * This one does not go through `useSave` for its success path: the response is
 * an archive, not a model, and the caller needs the bytes to hand to a blob
 * download. The mutation is still a `useSave` so failures are announced the
 * same way as everything else — the panel supplies the download step.
 */
export function useGenerateRecoveryKit() {
  return useSave<
    RecoveryKitRequest,
    { blob: Blob; filename: string | null }
  >({
    mutationFn: (body) => generateRecoveryKit(body),
    invalidates: [RECOVERY_KITS.prefix],
    success: () => ({
      title: "恢复包已生成",
      detail: "请立刻保存——它无法重新下载，也无法作废。",
    }),
    failure: (error) => ({ title: "生成恢复包失败", detail: describeFailure(error) }),
  })
}

/* -------------------------------------------------------------------------- */
/* Build bodies                                                               */
/* -------------------------------------------------------------------------- */

export function buildBackupPolicyCreate(
  form: BackupPolicyForm,
): BackupPolicyCreate {
  return {
    name: form.name.trim(),
    enabled: form.enabled,
    database_backend: form.databaseBackend,
    repository: form.repository.trim(),
    credentials: {
      password: form.credentials.password,
      environment: form.credentials.environment,
    },
    initialize_if_missing: form.initializeIfMissing,
    schedule: buildSchedule(form.schedule),
    repository_check_schedule: buildSchedule(form.repositoryCheckSchedule),
    retention: buildRetention(form),
    verify_after_backup: form.verifyAfterBackup,
    include_deployment_config: form.includeDeploymentConfig,
  }
}

/**
 * Build the PATCH from the whole form.
 *
 * The three schedule-shaped objects are always sent. Two of them — `schedule`
 * and `retention` — are replaced wholesale when present and `{}` means
 * "cleared", so a form that only sent them on change could never switch a
 * schedule off. The scalars are sent only when they moved, because those *are*
 * merged (`api.py:234-237`).
 */
export function buildBackupPolicyPatch(
  form: BackupPolicyForm,
  original: {
    name: string
    enabled: boolean
    verify_after_backup: boolean
    include_deployment_config: boolean
  },
): BackupPolicyUpdate {
  const body: BackupPolicyUpdate = {
    schedule: buildSchedule(form.schedule),
    repository_check_schedule: buildSchedule(form.repositoryCheckSchedule),
    retention: buildRetention(form),
  }

  if (form.name.trim() !== original.name) body.name = form.name.trim()
  if (form.enabled !== original.enabled) body.enabled = form.enabled
  if (form.verifyAfterBackup !== original.verify_after_backup) {
    body.verify_after_backup = form.verifyAfterBackup
  }
  if (form.includeDeploymentConfig !== original.include_deployment_config) {
    body.include_deployment_config = form.includeDeploymentConfig
  }

  // The repository is write-only and has no "clear": `repository: null` is a
  // 400 (`api.py:238-244`). An empty box therefore means "leave it alone".
  if (form.repository.trim() !== "") body.repository = form.repository.trim()

  Object.assign(body, buildCredentialEdit(form))
  return body
}

function describeFailure(error: unknown): string {
  const code = (error as { code?: string } | null)?.code
  switch (code) {
    case "backup_policy_disabled":
      return "该策略已停用，定时备份不会运行。"
    case "backup_policy_name_conflict":
      return "同名备份策略已存在。"
    case "backup_database_backend_mismatch":
      return "数据库类型与当前部署不一致，改不了。"
    case "backup_repository_credentials_embedded":
      return "仓库地址里不能内嵌用户名或密码。"
    case "backup_credentials_update_invalid":
      return "凭据只在选择「替换」时提交，且不能为空。"
    case "backup_secret_unavailable":
      return "密钥环里取不到这条策略的凭据，密钥可能已被轮换掉。"
    case "backup_schedule_timezone_invalid":
      return "时区不是有效的 IANA 名称，例如 Asia/Shanghai。"
    case "backup_schedule_invalid":
      return "cron 无效：必须是五段（分钟精度），且只能包含 cron 与 timezone 两个字段。"
    case "backup_retention_invalid":
      return "保留策略无效：每项是快照份数，取 0–10000 的整数。"
    case "backup_not_verifiable":
      return "只有已完成且产生了快照的备份才能校验。"
    case "recovery_kit_passphrase_too_short":
      return "口令至少 16 个字符（按 UTF-8 字节计）。"
    case "recovery_kit_bootstrap_incomplete":
      return "部署配置不完整，无法生成恢复包——缺少必需的启动环境变量。"
    case "backup_task_queue_unavailable":
      return "任务队列不可用。"
    default:
      return error instanceof Error ? error.message : String(error)
  }
}
