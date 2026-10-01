<script setup lang="ts">
import {
  computed,
  onMounted,
  reactive,
  ref,
  watch
} from "vue"
import { useI18n } from "vue-i18n"

import { formatBytes } from "../utils/format"

import { useGlobalRefresh } from "../composables/useGlobalRefresh"

import {
  listCameras,
  type CameraSummary
} from "../api/cameras"
import {
  ApiClientError,
  errorMessage
} from "../api/client"
import {
  applyCameraNtpSettings,
  applyConfigurationImport,
  backfillFrigate,
  createBackupPolicy,
  createNotificationTarget,
  deleteNotificationTarget,
  getCameraClockHealth,
  getFrigateProvider,
  getSystemHealth,
  getSystemInfo,
  getSystemSettings,
  getUpdateInfo,
  listAuditEvents,
  listBackupPolicies,
  listBackups,
  listNotificationDeliveries,
  listNotificationTargets,
  patchSystemSettings,
  putFrigateProvider,
  runBackup,
  testFrigateProvider,
  testNotificationTarget,
  updateBackupPolicy,
  updateNotificationTarget,
  validateConfigurationImport,
  verifyBackup,
  type AuditEvent,
  type BackupPolicy,
  type CameraClockHealth,
  type CameraNtpApplyResult,
  type BackupSet,
  type ConfigurationImportApplyResult,
  type ConfigurationImportValidation,
  type FrigateCameraMapping,
  type HealthComponent,
  type NotificationDelivery,
  type NotificationTarget,
  type SystemHealth,
  type SystemInfo,
  type SystemSettings,
  type SystemUpdateInfo
} from "../api/system"
import SystemAccessControlPanel from "../components/system/SystemAccessControlPanel.vue"
import SystemApiTokensPanel from "../components/system/SystemApiTokensPanel.vue"
import SystemBackupTab from "../components/system/SystemBackupTab.vue"
import SystemNotificationsTab from "../components/system/SystemNotificationsTab.vue"
import SystemTimeTab from "../components/system/SystemTimeTab.vue"
import SystemAiTab from "../components/system/SystemAiTab.vue"
import SystemAuditTab from "../components/system/SystemAuditTab.vue"
import SystemGeneralTab from "../components/system/SystemGeneralTab.vue"
import SystemOverviewTab from "../components/system/SystemOverviewTab.vue"
import SystemRecoveryKitPanel from "../components/system/SystemRecoveryKitPanel.vue"
import SystemAlertRulesPanel from "../components/system/SystemAlertRulesPanel.vue"
import StatusPill from "../components/ui/StatusPill.vue"
import UiIcon from "../components/ui/UiIcon.vue"
import { useAuthStore } from "../stores/auth"
import NoticeBanner from "../components/ui/NoticeBanner.vue"

import { confirmAction } from "../composables/useConfirm"
import { useAsyncResource } from "../composables/useAsyncResource"

// These prompts all remove or irreversibly change stored data, so the
// dialog styles the accept action as destructive.
const confirmDestroy = (message: string) =>
  confirmAction({ message, danger: true })
// Routine but consequential: the operator is asked to confirm, without
// the destructive styling.
const confirmProceed = (message: string) => confirmAction({ message })

type SystemTab =
  | "overview"
  | "general"
  | "time"
  | "users"
  | "tokens"
  | "notifications"
  | "alerts"
  | "ai"
  | "backup"
  | "audit"

const auth = useAuthStore()
const { loading, error, run } = useAsyncResource()
const { locale, t } = useI18n({ useScope: "global" })
const tab = ref<SystemTab>("overview")
const info = ref<SystemInfo | null>(null)
const health = ref<SystemHealth | null>(null)
const settings = ref<SystemSettings | null>(null)
const updateInfo = ref<SystemUpdateInfo | null>(null)
const notice = ref<string | null>(null)

const cameras = ref<CameraSummary[]>([])

const targets = ref<NotificationTarget[]>([])
const deliveries = ref<NotificationDelivery[]>([])
const notificationPanelOpen = ref(false)
const editingNotification = ref<NotificationTarget | null>(null)
const notificationSaving = ref(false)
const testingNotificationId = ref<string | null>(null)
const notificationForm = reactive({
  name: "",
  url: "",
  passwordReset: false
})

const frigateConfigured = ref(false)
const frigateSaving = ref(false)
const frigateTesting = ref(false)
const frigateVersion = ref<string | null>(null)
const frigateMappings = ref<FrigateCameraMapping[]>([])
const frigateForm = reactive({
  enabled: false,
  mode: "external" as "managed" | "external",
  baseUrl: "http://frigate:5000",
  mqttEnabled: false,
  mqttHost: "",
  mqttPort: 1883,
  mqttTopicPrefix: "frigate",
  mqttTls: false,
  bearerToken: "",
  httpUsername: "",
  httpPassword: "",
  mqttUsername: "",
  mqttPassword: ""
})

const backupPolicies = ref<BackupPolicy[]>([])
const backups = ref<BackupSet[]>([])
const backupPanelOpen = ref(false)
const editingBackupPolicy = ref<BackupPolicy | null>(null)
const backupSaving = ref(false)
const backupRefreshing = ref(false)
const runningBackupId = ref<string | null>(null)
const verifyingBackupId = ref<string | null>(null)
const configImportValidation = ref<ConfigurationImportValidation | null>(null)
const configImportBundle = ref<Record<string, unknown> | null>(null)
const configImportApplyResult = ref<ConfigurationImportApplyResult | null>(null)
const configImportValidating = ref(false)
const configImportApplying = ref(false)
const configImportFileName = ref<string | null>(null)
const backupForm = reactive({
  name: t("system.main.systemBackup"),
  repository: "",
  password: "",
  environmentCredentials: "",
  initializeIfMissing: true,
  scheduled: true,
  cron: "0 3 * * *",
  keepLast: 7,
  keepDaily: 7,
  keepWeekly: 4,
  keepMonthly: 6,
  verifyAfter: true,
  includeDeploymentConfig: true,
  enabled: true
})

const auditEvents = ref<AuditEvent[]>([])
const auditNextCursor = ref<string | null>(null)
const auditLoading = ref(false)
const auditLoadingMore = ref(false)
const auditFilters = reactive({
  period: "7d" as "24h" | "7d" | "30d" | "all",
  action: "",
  resourceType: "",
  result: ""
})
const generalForm = reactive({
  systemName: ""
})
const timeForm = reactive({
  recordingTimezone: "UTC",
  ntpMode: "dhcp" as "manual" | "dhcp",
  ntpServers: [""] as string[]
})
const runtimeForm = reactive({
  prebufferFragmentSeconds: 5,
  prebufferBufferSeconds: 35,
  turnCredentialTtlSeconds: 600,
  playbackCacheMiB: 4096,
  playbackCacheTtlSeconds: 21600,
  playbackRestoreLockTtlSeconds: 900,
  liveTranscodeMaxDerivatives: 2,
  liveTranscodeIdleTtlSeconds: 20,
  liveTranscodeLeaseTtlSeconds: 30,
  liveTranscodeStartupTimeoutSeconds: 10,
  liveTranscodeCpuThreads: 2,
  liveTranscodeVideoBitrateKbps: 4000
})
const generalSaving = ref(false)
const timeSaving = ref(false)
const ntpApplying = ref(false)
const runtimeSaving = ref(false)
const ntpApplyResult = ref<CameraNtpApplyResult | null>(null)
const cameraClockHealth = ref<CameraClockHealth | null>(null)
const cameraClockLoading = ref(false)

const navigation = computed(() => {
  const isZh = locale.value?.startsWith("zh")
  const items: Array<{
    id: SystemTab
    label: string
    icon: string
    visible: boolean
  }> = [
    {
      id: "overview",
      label: isZh ? "系统概览与资源" : t("system.main.navOverview"),
      icon: "dashboard",
      visible: true
    },
    {
      id: "general",
      label: isZh ? "基础参数与网络" : t("system.main.general"),
      icon: "system",
      visible: true
    },
    {
      id: "time",
      label: isZh ? "时钟与 NTP 策略" : t("system.main.time"),
      icon: "calendar",
      visible: auth.hasPermission("system.view")
    },
    {
      id: "users",
      label: isZh ? "用户权限 (RBAC)" : t("system.main.navUsers"),
      icon: "users",
      visible: auth.hasPermission("user.manage")
    },
    {
      id: "tokens",
      label: isZh ? "API 服务令牌" : t("system.main.navApiTokens"),
      icon: "shield",
      visible: true
    },
    {
      id: "notifications",
      label: isZh ? "通知渠道 (Apprise)" : t("system.main.notifications"),
      icon: "bell",
      visible: auth.hasPermission("notification.view")
    },
    {
      id: "alerts",
      label: isZh ? "告警规则与防风暴" : t("system.main.navAlertRules"),
      icon: "bell",
      visible: auth.hasPermission("alert.manage")
    },
    {
      id: "ai",
      label: isZh ? "Frigate AI 引擎配置" : t("system.main.aiFrigate"),
      icon: "brain",
      visible: auth.hasPermission("integration.manage")
    },
    {
      id: "backup",
      label: isZh ? "备份与 RecoveryKit" : t("system.main.backup"),
      icon: "backup",
      visible: auth.hasPermission("system.view")
    },
    {
      id: "audit",
      label: isZh ? "安全审计日志" : t("system.main.audit"),
      icon: "audit",
      visible: auth.hasPermission("audit.view")
    }
  ]
  return items.filter((item) => item.visible)
})

const hostClockHealth = computed(
  () => health.value?.components.host_clock ?? null
)


function parseBackupEnvironment(
  raw: string
): Record<string, string> {
  const environment: Record<string, string> = {}
  const reserved = new Set([
    "RESTIC_REPOSITORY",
    "RESTIC_PASSWORD",
    "RESTIC_PASSWORD_FILE"
  ])

  for (const [index, source] of raw.split(/\r?\n/).entries()) {
    const line = source.trim()
    if (!line || line.startsWith("#")) continue

    const separator = line.indexOf("=")
    if (separator <= 0) {
      throw new Error(
        t("system.main.repoLineFormat", { line: index + 1 })
      )
    }

    const key = line.slice(0, separator).trim()
    const value = line.slice(separator + 1)
    if (!/^[A-Z][A-Z0-9_]{0,127}$/.test(key)) {
      throw new Error(
        t("system.main.repoInvalidKey", { line: index + 1 })
      )
    }
    if (reserved.has(key)) {
      throw new Error(
        t("system.main.repoReservedKey", { key })
      )
    }
    environment[key] = value
  }

  return environment
}

function exportConfiguration(): void {
  window.location.assign(
    "/api/v1/system/configuration/export"
  )
}

async function copyHostCommand(
  command: string
): Promise<void> {
  try {
    await navigator.clipboard.writeText(command)
    notice.value = t("system.main.hostCommandCopied")
  } catch {
    notice.value = t("system.main.clipboardBlocked")
  }
}

/**
 * Validate a configuration bundle the operator picked.
 *
 * The backup tab owns the file input (and clears it after every pick, so the
 * same file can be re-selected), so this receives the `File` itself.
 */
async function handleConfigurationFile(file: File): Promise<void> {
  error.value = null
  notice.value = null
  configImportValidation.value = null
  configImportBundle.value = null
  configImportApplyResult.value = null
  configImportFileName.value = file.name

  if (file.size > 5 * 1024 * 1024) {
    error.value = t("system.main.configTooLarge")
    return
  }

  configImportValidating.value = true
  try {
    const parsed: unknown = JSON.parse(
      await file.text()
    )
    if (
      !parsed ||
      typeof parsed !== "object" ||
      Array.isArray(parsed)
    ) {
      throw new Error(
        t("system.main.configJsonObject")
      )
    }
    const bundle =
      parsed as Record<string, unknown>
    configImportValidation.value =
      await validateConfigurationImport(bundle)
    configImportBundle.value = bundle
    notice.value = t("system.main.configValid")
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    configImportValidating.value = false
  }
}

async function applyValidatedConfigurationImport(): Promise<void> {
  if (
    !configImportBundle.value ||
    !configImportValidation.value ||
    configImportApplying.value
  ) {
    return
  }

  const credentialCount =
    configImportValidation.value.credentials_required.length
  const detail = credentialCount
    ? t("system.main.configCredentialSkip", { count: credentialCount })
    : ""
  if (
    !await confirmProceed(
      t("system.main.configApplyConfirm") + detail
    )
  ) {
    return
  }

  configImportApplying.value = true
  error.value = null
  notice.value = null
  try {
    configImportApplyResult.value =
      await applyConfigurationImport(
        configImportBundle.value
      )
    notice.value =
      t("system.main.configApplied", { applied: configImportApplyResult.value.applied_count, skipped: configImportApplyResult.value.skipped_count })
    await Promise.all([
      loadBase(),
      loadBackups()
    ])
    window.dispatchEvent(
      new CustomEvent("zero-nvr:refresh")
    )
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    configImportApplying.value = false
  }
}

function discardConfigurationImport(): void {
  configImportValidation.value = null
  configImportBundle.value = null
  configImportApplyResult.value = null
  configImportFileName.value = null
}

async function loadBase(): Promise<void> {
  if (!auth.hasPermission("system.view")) return

  await run(async () => {
    const [infoValue, healthValue, settingsValue, updateValue] =
      await Promise.all([
        getSystemInfo(),
        getSystemHealth(),
        getSystemSettings(),
        getUpdateInfo()
      ])
    info.value = infoValue
    health.value = healthValue
    settings.value = settingsValue
    updateInfo.value = updateValue

    generalForm.systemName = settingsValue.general.system_name
    timeForm.recordingTimezone =
      settingsValue.time.recording_timezone
    timeForm.ntpMode =
      settingsValue.time.managed_camera_ntp_mode
    timeForm.ntpServers =
      settingsValue.time.managed_camera_ntp_servers.length
        ? [...settingsValue.time.managed_camera_ntp_servers]
        : [""]
    runtimeForm.prebufferFragmentSeconds =
      settingsValue.runtime.prebuffer_fragment_seconds
    runtimeForm.prebufferBufferSeconds =
      settingsValue.runtime.prebuffer_buffer_seconds
    runtimeForm.turnCredentialTtlSeconds =
      settingsValue.runtime.turn_credential_ttl_seconds
    runtimeForm.playbackCacheMiB =
      settingsValue.runtime.playback_cache_max_bytes /
      (1024 * 1024)
    runtimeForm.playbackCacheTtlSeconds =
      settingsValue.runtime.playback_cache_ttl_seconds
    runtimeForm.playbackRestoreLockTtlSeconds =
      settingsValue.runtime.playback_restore_lock_ttl_seconds
    runtimeForm.liveTranscodeMaxDerivatives =
      settingsValue.runtime.live_transcode_max_derivatives
    runtimeForm.liveTranscodeIdleTtlSeconds =
      settingsValue.runtime.live_transcode_idle_ttl_seconds
    runtimeForm.liveTranscodeLeaseTtlSeconds =
      settingsValue.runtime.live_transcode_lease_ttl_seconds
    runtimeForm.liveTranscodeStartupTimeoutSeconds =
      settingsValue.runtime.live_transcode_startup_timeout_seconds
    runtimeForm.liveTranscodeCpuThreads =
      settingsValue.runtime.live_transcode_cpu_threads
    runtimeForm.liveTranscodeVideoBitrateKbps =
      settingsValue.runtime.live_transcode_video_bitrate_kbps
  })
}

async function loadNotifications(): Promise<void> {
  if (!auth.hasPermission("notification.view")) return
  try {
    ;[targets.value, deliveries.value] = await Promise.all([
      listNotificationTargets(),
      listNotificationDeliveries()
    ])
  } catch (caught) {
    error.value = errorMessage(caught)
  }
}

async function loadFrigate(): Promise<void> {
  if (!auth.hasPermission("integration.manage")) return
  if (!cameras.value.length && auth.hasPermission("camera.view")) {
    cameras.value = await listCameras().catch(() => [])
  }

  try {
    const value = await getFrigateProvider()
    frigateConfigured.value = true
    frigateForm.enabled = value.enabled
    frigateForm.mode = value.mode
    frigateForm.baseUrl = value.base_url
    frigateForm.mqttEnabled = value.mqtt_enabled
    frigateForm.mqttHost = value.mqtt_host ?? ""
    frigateForm.mqttPort = value.mqtt_port
    frigateForm.mqttTopicPrefix = value.mqtt_topic_prefix
    frigateForm.mqttTls = value.mqtt_tls
    frigateMappings.value = value.camera_map.map((item) => ({ ...item }))
  } catch (caught) {
    if (
      caught instanceof ApiClientError &&
      caught.code === "frigate_not_configured"
    ) {
      frigateConfigured.value = false
      frigateMappings.value = []
      return
    }
    error.value = errorMessage(caught)
  }
}

async function loadBackups(): Promise<void> {
  if (!auth.hasPermission("system.view")) return
  backupRefreshing.value = true
  try {
    const [policyPage, backupPage] = await Promise.all([
      listBackupPolicies(),
      listBackups()
    ])
    backupPolicies.value = policyPage
    backups.value = backupPage.items
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    backupRefreshing.value = false
  }
}

function auditRange(): [Date | null, Date | null] {
  if (auditFilters.period === "all") {
    return [null, null]
  }
  const now = new Date()
  const hours =
    auditFilters.period === "24h"
      ? 24
      : auditFilters.period === "7d"
        ? 24 * 7
        : 24 * 30
  return [
    new Date(now.getTime() - hours * 60 * 60 * 1000),
    now
  ]
}

async function loadAudit(): Promise<void> {
  if (!auth.hasPermission("audit.view")) return
  const [from, to] = auditRange()
  auditLoading.value = true
  error.value = null
  try {
    const page = await listAuditEvents({
      action: auditFilters.action.trim() || null,
      resourceType:
        auditFilters.resourceType.trim() || null,
      result: auditFilters.result || null,
      from,
      to,
      limit: 100
    })
    auditEvents.value = page.items
    auditNextCursor.value = page.next_cursor
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    auditLoading.value = false
  }
}

async function loadMoreAudit(): Promise<void> {
  if (
    !auditNextCursor.value ||
    auditLoadingMore.value
  ) {
    return
  }
  const [from, to] = auditRange()
  auditLoadingMore.value = true
  error.value = null
  try {
    const page = await listAuditEvents({
      action: auditFilters.action.trim() || null,
      resourceType:
        auditFilters.resourceType.trim() || null,
      result: auditFilters.result || null,
      from,
      to,
      cursor: auditNextCursor.value,
      limit: 100
    })
    const known = new Set(
      auditEvents.value.map((item) => item.id)
    )
    auditEvents.value.push(
      ...page.items.filter(
        (item) => !known.has(item.id)
      )
    )
    auditNextCursor.value = page.next_cursor
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    auditLoadingMore.value = false
  }
}

function resetAuditFilters(): void {
  auditFilters.period = "7d"
  auditFilters.action = ""
  auditFilters.resourceType = ""
  auditFilters.result = ""
  void loadAudit()
}

async function loadTab(value: SystemTab): Promise<void> {
  notice.value = null
  if (value === "time") await checkCameraClocks()
  if (value === "notifications") await loadNotifications()
  if (value === "ai") await loadFrigate()
  if (value === "backup") await loadBackups()
  if (value === "audit") await loadAudit()
}

async function checkCameraClocks(): Promise<void> {
  if (!auth.hasPermission("system.view")) return
  cameraClockLoading.value = true
  error.value = null
  try {
    cameraClockHealth.value =
      await getCameraClockHealth()
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    cameraClockLoading.value = false
  }
}

async function saveGeneral(): Promise<void> {
  if (!auth.hasPermission("system.manage")) return
  generalSaving.value = true
  error.value = null
  try {
    settings.value = await patchSystemSettings({
      general: {
        system_name: generalForm.systemName.trim()
      }
    })
    notice.value = t("system.main.generalSaved")
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    generalSaving.value = false
  }
}

function normalizedTimeNtpServers(): string[] {
  const seen = new Set<string>()
  const result: string[] = []
  for (const raw of timeForm.ntpServers) {
    const value = raw.trim()
    if (!value || seen.has(value)) continue
    seen.add(value)
    result.push(value)
  }
  return result
}

async function saveTime(
  applyToCameras = false
): Promise<void> {
  if (!auth.hasPermission("system.manage")) return

  const servers = normalizedTimeNtpServers()
  if (
    timeForm.ntpMode === "manual" &&
    !servers.length
  ) {
    error.value = t("system.main.manualNtpRequired")
    return
  }

  timeSaving.value = true
  ntpApplying.value = applyToCameras
  error.value = null
  ntpApplyResult.value = null
  try {
    const updated = await patchSystemSettings({
      time: {
        recording_timezone:
          timeForm.recordingTimezone.trim(),
        managed_camera_ntp_mode:
          timeForm.ntpMode,
        managed_camera_ntp_servers: servers
      }
    })
    settings.value = updated
    timeForm.ntpServers =
      updated.time.managed_camera_ntp_servers.length
        ? [...updated.time.managed_camera_ntp_servers]
        : [""]

    if (!applyToCameras) {
      notice.value = t("system.main.timeSavedNoApply")
      return
    }

    const applied = await applyCameraNtpSettings()
    ntpApplyResult.value = applied
    if (applied.total_devices === 0) {
      notice.value = t("system.main.timeSavedNoDevices")
    } else if (applied.failed === 0) {
      notice.value =
        t("system.main.timeSavedApplied", { updated: applied.updated })
    } else {
      notice.value =
        t("system.main.timeSavedPartial", { updated: applied.updated, total: applied.total_devices })
    }
    if (applied.updated) {
      await checkCameraClocks()
    }
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    timeSaving.value = false
    ntpApplying.value = false
  }
}

async function saveRuntime(): Promise<void> {
  if (!auth.hasPermission("system.manage")) return
  runtimeSaving.value = true
  error.value = null
  try {
    const updated = await patchSystemSettings({
      runtime: {
        prebuffer_fragment_seconds:
          Number(runtimeForm.prebufferFragmentSeconds),
        prebuffer_buffer_seconds:
          Number(runtimeForm.prebufferBufferSeconds),
        turn_credential_ttl_seconds:
          Number(runtimeForm.turnCredentialTtlSeconds),
        playback_cache_max_bytes: Math.round(
          runtimeForm.playbackCacheMiB * 1024 * 1024
        ),
        playback_cache_ttl_seconds:
          Number(runtimeForm.playbackCacheTtlSeconds),
        playback_restore_lock_ttl_seconds:
          Number(runtimeForm.playbackRestoreLockTtlSeconds),
        live_transcode_max_derivatives:
          Number(runtimeForm.liveTranscodeMaxDerivatives),
        live_transcode_idle_ttl_seconds:
          Number(runtimeForm.liveTranscodeIdleTtlSeconds),
        live_transcode_lease_ttl_seconds:
          Number(runtimeForm.liveTranscodeLeaseTtlSeconds),
        live_transcode_startup_timeout_seconds:
          Number(runtimeForm.liveTranscodeStartupTimeoutSeconds),
        live_transcode_cpu_threads:
          Number(runtimeForm.liveTranscodeCpuThreads),
        live_transcode_video_bitrate_kbps:
          Number(runtimeForm.liveTranscodeVideoBitrateKbps)
      }
    })
    settings.value = updated
    notice.value = t("system.main.runtimeSaved")
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    runtimeSaving.value = false
  }
}

function openNotificationPanel(): void {
  editingNotification.value = null
  notificationForm.name = ""
  notificationForm.url = ""
  notificationForm.passwordReset = false
  notificationPanelOpen.value = true
}

function openEditNotification(item: NotificationTarget): void {
  editingNotification.value = item
  notificationForm.name = item.name
  notificationForm.url = ""
  notificationForm.passwordReset =
    item.config.password_reset === true
  notificationPanelOpen.value = true
  notice.value = null
}

async function saveNotification(): Promise<void> {
  notificationSaving.value = true
  error.value = null
  try {
    const name = notificationForm.name.trim()
    const url = notificationForm.url.trim()

    if (editingNotification.value) {
      const changes: Record<string, unknown> = {
        name,
        url_action: url ? "replace" : "keep"
      }
      if (url) {
        changes.url = url
      }
      changes.config = {
        notify_type:
          typeof editingNotification.value.config.notify_type === "string"
            ? editingNotification.value.config.notify_type
            : "info",
        password_reset: notificationForm.passwordReset
      }
      await updateNotificationTarget(
        editingNotification.value.id,
        changes
      )
      notice.value = t("system.main.notificationUpdated")
    } else {
      await createNotificationTarget(
        name,
        url,
        {
          password_reset: notificationForm.passwordReset
        }
      )
      notice.value = t("system.main.notificationCreated")
    }

    editingNotification.value = null
    notificationPanelOpen.value = false
    await loadNotifications()
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    notificationSaving.value = false
  }
}

async function testNotification(item: NotificationTarget): Promise<void> {
  testingNotificationId.value = item.id
  error.value = null
  try {
    await testNotificationTarget(item.id)
    notice.value = t("system.main.notificationTestSent", { name: item.name })
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    testingNotificationId.value = null
  }
}

async function toggleNotification(item: NotificationTarget): Promise<void> {
  try {
    await updateNotificationTarget(item.id, {
      enabled: !item.enabled
    })
    await loadNotifications()
  } catch (caught) {
    error.value = errorMessage(caught)
  }
}

async function removeNotification(item: NotificationTarget): Promise<void> {
  if (!await confirmDestroy(t("system.main.deleteNotification", { name: item.name }))) {
    return
  }
  try {
    await deleteNotificationTarget(item.id)
    await loadNotifications()
  } catch (caught) {
    error.value = errorMessage(caught)
  }
}

async function saveFrigate(): Promise<void> {
  frigateSaving.value = true
  error.value = null
  const hasCredentials = Boolean(
    frigateForm.bearerToken ||
      frigateForm.httpUsername ||
      frigateForm.httpPassword ||
      frigateForm.mqttUsername ||
      frigateForm.mqttPassword
  )

  try {
    await putFrigateProvider({
      enabled: frigateForm.enabled,
      mode: frigateForm.mode,
      base_url: frigateForm.baseUrl.trim(),
      camera_map: frigateMappings.value
        .map((item) => ({
          frigate_camera: item.frigate_camera.trim(),
          camera_id: item.camera_id
        }))
        .filter((item) => item.frigate_camera && item.camera_id),
      mqtt_enabled: frigateForm.mqttEnabled,
      mqtt_host: frigateForm.mqttHost.trim() || null,
      mqtt_port: Number(frigateForm.mqttPort),
      mqtt_topic_prefix:
        frigateForm.mqttTopicPrefix.trim() || "frigate",
      mqtt_tls: frigateForm.mqttTls,
      credentials_action: hasCredentials
        ? "replace"
        : "keep",
      credentials: hasCredentials
        ? {
            http_bearer_token:
              frigateForm.bearerToken || null,
            http_username:
              frigateForm.httpUsername || null,
            http_password:
              frigateForm.httpPassword || null,
            mqtt_username:
              frigateForm.mqttUsername || null,
            mqtt_password:
              frigateForm.mqttPassword || null
          }
        : null
    })
    frigateForm.bearerToken = ""
    frigateForm.httpUsername = ""
    frigateForm.httpPassword = ""
    frigateForm.mqttUsername = ""
    frigateForm.mqttPassword = ""
    frigateConfigured.value = true
    notice.value =
      frigateForm.enabled &&
      frigateForm.mode === "managed"
        ? t("system.main.managedFrigateSaved")
        : t("system.main.frigateSaved")
    await loadFrigate()
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    frigateSaving.value = false
  }
}

async function testFrigate(): Promise<void> {
  frigateTesting.value = true
  error.value = null
  try {
    const result = await testFrigateProvider()
    frigateVersion.value = result.version
    notice.value = t("system.main.frigateConnected", { version: result.version ? ` · ${result.version}` : "" })
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    frigateTesting.value = false
  }
}

async function queueBackfill(): Promise<void> {
  try {
    await backfillFrigate(600)
    notice.value = t("system.main.frigateBackfill")
  } catch (caught) {
    error.value = errorMessage(caught)
  }
}

function openBackupPanel(): void {
  editingBackupPolicy.value = null
  backupForm.name = t("system.main.systemBackup")
  backupForm.repository = ""
  backupForm.password = ""
  backupForm.environmentCredentials = ""
  backupForm.initializeIfMissing = true
  backupForm.scheduled = true
  backupForm.cron = "0 3 * * *"
  backupForm.keepLast = 7
  backupForm.keepDaily = 7
  backupForm.keepWeekly = 4
  backupForm.keepMonthly = 6
  backupForm.verifyAfter = true
  backupForm.includeDeploymentConfig = true
  backupForm.enabled = true
  backupPanelOpen.value = true
}

function numberFromRecord(
  value: Record<string, unknown>,
  key: string,
  fallback: number
): number {
  const raw = value[key]
  return typeof raw === "number" && Number.isFinite(raw)
    ? raw
    : fallback
}

function openEditBackupPolicy(policy: BackupPolicy): void {
  editingBackupPolicy.value = policy
  backupForm.name = policy.name
  backupForm.repository = ""
  backupForm.password = ""
  backupForm.environmentCredentials = ""
  backupForm.initializeIfMissing = false
  backupForm.scheduled =
    typeof policy.schedule.cron === "string" &&
    Boolean(policy.schedule.cron)
  backupForm.cron =
    typeof policy.schedule.cron === "string"
      ? policy.schedule.cron
      : "0 3 * * *"
  backupForm.keepLast = numberFromRecord(
    policy.retention,
    "keep_last",
    7
  )
  backupForm.keepDaily = numberFromRecord(
    policy.retention,
    "keep_daily",
    7
  )
  backupForm.keepWeekly = numberFromRecord(
    policy.retention,
    "keep_weekly",
    4
  )
  backupForm.keepMonthly = numberFromRecord(
    policy.retention,
    "keep_monthly",
    6
  )
  backupForm.verifyAfter = policy.verify_after_backup
  backupForm.includeDeploymentConfig =
    policy.include_deployment_config
  backupForm.enabled = policy.enabled
  backupPanelOpen.value = true
  notice.value = null
}

async function saveBackupPolicy(): Promise<void> {
  backupSaving.value = true
  error.value = null
  const timezone =
    settings.value?.time.recording_timezone || "UTC"
  try {
    const environment = parseBackupEnvironment(
      backupForm.environmentCredentials
    )
    const hasEnvironmentCredentials =
      Object.keys(environment).length > 0

    const schedule = backupForm.scheduled
      ? {
          cron: backupForm.cron.trim(),
          timezone
        }
      : {}
    const retention = {
      keep_last: Number(backupForm.keepLast),
      keep_daily: Number(backupForm.keepDaily),
      keep_weekly: Number(backupForm.keepWeekly),
      keep_monthly: Number(backupForm.keepMonthly)
    }

    if (editingBackupPolicy.value) {
      const changes: {
        name: string
        enabled: boolean
        schedule: Record<string, unknown>
        retention: Record<string, unknown>
        verify_after_backup: boolean
        include_deployment_config: boolean
        repository?: string
        credentials_action: "keep" | "replace"
        credentials?: {
          password?: string
          environment?: Record<string, string>
        }
      } = {
        name: backupForm.name.trim(),
        enabled: backupForm.enabled,
        schedule,
        retention,
        verify_after_backup: backupForm.verifyAfter,
        include_deployment_config:
          backupForm.includeDeploymentConfig,
        credentials_action:
          backupForm.password || hasEnvironmentCredentials
            ? "replace"
            : "keep"
      }

      if (backupForm.repository.trim()) {
        changes.repository = backupForm.repository.trim()
      }
      if (
        backupForm.password ||
        hasEnvironmentCredentials
      ) {
        changes.credentials = {}
        if (backupForm.password) {
          changes.credentials.password =
            backupForm.password
        }
        if (hasEnvironmentCredentials) {
          changes.credentials.environment =
            environment
        }
      }

      await updateBackupPolicy(
        editingBackupPolicy.value.id,
        changes
      )
      notice.value = t("system.main.backupUpdated")
    } else {
      await createBackupPolicy({
        name: backupForm.name.trim(),
        enabled: backupForm.enabled,
        repository: backupForm.repository.trim(),
        credentials: {
          password: backupForm.password,
          environment
        },
        initialize_if_missing: backupForm.initializeIfMissing,
        database_backend: info.value?.database_backend || "sqlite",
        schedule,
        retention,
        verify_after_backup: backupForm.verifyAfter,
        repository_check_schedule: {},
        include_deployment_config:
          backupForm.includeDeploymentConfig
      })
      notice.value = t("system.main.backupCreated")
    }

    editingBackupPolicy.value = null
    backupPanelOpen.value = false
    await loadBackups()
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    backupSaving.value = false
  }
}

async function runPolicy(policy: BackupPolicy): Promise<void> {
  runningBackupId.value = policy.id
  error.value = null
  try {
    await runBackup(policy.id)
    notice.value = t("system.main.backupStarted", { name: policy.name })
    await loadBackups()
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    runningBackupId.value = null
  }
}

async function verifySet(item: BackupSet): Promise<void> {
  verifyingBackupId.value = item.id
  error.value = null
  try {
    await verifyBackup(item.id)
    notice.value = t("system.main.backupVerifyQueued")
    await loadBackups()
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    verifyingBackupId.value = null
  }
}

function handleRefreshEvent(): void {
  void loadBase()
  void loadTab(tab.value)
}

watch(tab, (value) => {
  void loadTab(value)
})

useGlobalRefresh(handleRefreshEvent)

onMounted(() => {
  void loadBase()
})
</script>

<template>
  <div class="system-workspace">
    <aside class="system-nav">
      <div class="system-nav__title">
        <span class="blue-dot" />
        <strong>系统运维 (System)</strong>
      </div>
      <nav>
        <button
          v-for="item in navigation"
          :key="item.id"
          type="button"
          :class="{ 'system-nav__active': tab === item.id }"
          @click="tab = item.id"
        >
          <UiIcon :name="item.icon" :size="16" />
          <span>{{ item.label }}</span>
        </button>
      </nav>
      <div class="system-nav__footer">
        <div>zero-nvr Core {{ info?.version ? (info.version.startsWith('v') ? info.version : `v${info.version}`) : "v1.4.2" }}</div>
        <div class="text-emerald">● 生产就绪 (Production)</div>
      </div>
    </aside>

    <main class="system-content">
      <NoticeBanner
        v-if="error"
        surface-class="events-error"
        variant="error" :icon-size="16"
      >{{ error }}</NoticeBanner>

      <NoticeBanner
        v-if="notice"
        surface-class="storage-notice"
        variant="success" :icon-size="15"
      >{{ notice }}</NoticeBanner>

      <template v-if="tab === 'overview'">
        <SystemOverviewTab
          :health="health"
          :info="info"
          :update-info="updateInfo"
          :loading="loading"
          :can-view-secret-store="auth.hasPermission('system.view')"
          @refresh="loadBase"
        />
      </template>


      <template v-else-if="tab === 'general'">
        <SystemGeneralTab
          :general-form="generalForm"
          :runtime-form="runtimeForm"
          :general-saving="generalSaving"
          :runtime-saving="runtimeSaving"
          :can-manage="auth.hasPermission('system.manage')"
          @save-general="saveGeneral"
          @save-runtime="saveRuntime"
        />
      </template>

      <template v-else-if="tab === 'time'">
        <SystemTimeTab
          :time-form="timeForm"
          :time-saving="timeSaving"
          :ntp-applying="ntpApplying"
          :ntp-apply-result="ntpApplyResult"
          :host-clock-health="hostClockHealth"
          :camera-clock-health="cameraClockHealth"
          :camera-clock-loading="cameraClockLoading"
          :can-manage="auth.hasPermission('system.manage')"
          @save="saveTime"
          @check-clocks="checkCameraClocks"
        />
      </template>

      <template v-else-if="tab === 'users'">
        <SystemAccessControlPanel />
      </template>

      <template v-else-if="tab === 'tokens'">
        <SystemApiTokensPanel />
      </template>


      <template v-else-if="tab === 'notifications'">
        <SystemNotificationsTab
          :targets="targets"
          :deliveries="deliveries"
          :notification-form="notificationForm"
          :notification-panel-open="notificationPanelOpen"
          :editing-notification="editingNotification"
          :notification-saving="notificationSaving"
          :testing-notification-id="testingNotificationId"
          :can-manage="auth.hasPermission('notification.manage')"
          @open-panel="openNotificationPanel"
          @close-panel="notificationPanelOpen = false; editingNotification = null"
          @edit-target="openEditNotification"
          @remove-target="removeNotification"
          @test-target="testNotification"
          @toggle-target="toggleNotification"
          @save="saveNotification"
        />
      </template>

      <template v-else-if="tab === 'alerts'">
        <SystemAlertRulesPanel
          :display-timezone="
            settings?.general.display_timezone || 'UTC'
          "
        />
      </template>

      <template v-else-if="tab === 'ai'">
        <SystemAiTab
          :frigate-form="frigateForm"
          :frigate-configured="frigateConfigured"
          :frigate-version="frigateVersion"
          :frigate-mappings="frigateMappings"
          :frigate-saving="frigateSaving"
          :frigate-testing="frigateTesting"
          :cameras="cameras"
          @save="saveFrigate"
          @test="testFrigate"
          @backfill="queueBackfill"
        />
      </template>

      <template v-else-if="tab === 'backup'">
        <SystemBackupTab
          :backup-policies="backupPolicies"
          :backups="backups"
          :settings="settings"
          :backup-form="backupForm"
          :backup-panel-open="backupPanelOpen"
          :editing-backup-policy="editingBackupPolicy"
          :backup-saving="backupSaving"
          :backup-refreshing="backupRefreshing"
          :running-backup-id="runningBackupId"
          :verifying-backup-id="verifyingBackupId"
          :config-import-validation="configImportValidation"
          :config-import-file-name="configImportFileName"
          :config-import-validating="configImportValidating"
          :config-import-applying="configImportApplying"
          :config-import-apply-result="configImportApplyResult"
          :config-import-bundle="configImportBundle"
          :can-manage="auth.hasPermission('system.manage')"
          @refresh="loadBackups"
          @open-panel="openBackupPanel"
          @close-panel="backupPanelOpen = false; editingBackupPolicy = null"
          @edit-policy="openEditBackupPolicy"
          @save-policy="saveBackupPolicy"
          @run-policy="runPolicy"
          @verify-set="verifySet"
          @export-config="exportConfiguration"
          @config-file="handleConfigurationFile"
          @config-apply="applyValidatedConfigurationImport"
          @config-discard="discardConfigurationImport"
          @copy-command="copyHostCommand"
        />
      </template>

      <template v-else-if="tab === 'audit'">
        <SystemAuditTab
          :audit-events="auditEvents"
          :audit-filters="auditFilters"
          :audit-loading="auditLoading"
          :audit-loading-more="auditLoadingMore"
          :audit-next-cursor="auditNextCursor"
          @reload="loadAudit"
          @load-more="loadMoreAudit"
          @reset-filters="resetAuditFilters"
        />
      </template>
    </main>
  </div>
</template>


<style scoped>















.backup-recovery-commands {
  display: grid;
  gap: 8px;
}

.backup-recovery-commands > div {
  display: grid;
  grid-template-columns:
    minmax(180px, 0.9fr)
    minmax(260px, 1.4fr)
    auto;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--uf-border-subtle);
  border-radius: 8px;
  background: var(--uf-bg-card-sub);
}

.backup-recovery-commands span {
  color: var(--uf-text-primary);
  font-size: 11px;
}

.backup-recovery-commands code {
  overflow-x: auto;
  color: var(--uf-accent);
  font-size: 11px;
  font-family: var(--font-mono);
  white-space: nowrap;
}

@media (max-width: 820px) {
  .backup-recovery-commands > div {
    grid-template-columns: 1fr auto;
  }

  .backup-recovery-commands span {
    grid-column: 1 / -1;
  }
}
</style>