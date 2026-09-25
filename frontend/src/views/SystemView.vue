<script setup lang="ts">
import {
  computed,
  onBeforeUnmount,
  onMounted,
  reactive,
  ref,
  watch
} from "vue"
import { useI18n } from "vue-i18n"

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
import SystemOidcPanel from "../components/system/SystemOidcPanel.vue"
import SystemReleaseValidationPanel from "../components/system/SystemReleaseValidationPanel.vue"
import SystemSecretStorePanel from "../components/system/SystemSecretStorePanel.vue"
import SystemRecoveryKitPanel from "../components/system/SystemRecoveryKitPanel.vue"
import SystemAlertRulesPanel from "../components/system/SystemAlertRulesPanel.vue"
import UiIcon from "../components/ui/UiIcon.vue"
import { useAuthStore } from "../stores/auth"

type SystemTab =
  | "overview"
  | "validation"
  | "general"
  | "time"
  | "users"
  | "tokens"
  | "oidc"
  | "notifications"
  | "alerts"
  | "ai"
  | "backup"
  | "audit"

const auth = useAuthStore()
const { locale, t, te } = useI18n({ useScope: "global" })
const tab = ref<SystemTab>("overview")
const info = ref<SystemInfo | null>(null)
const health = ref<SystemHealth | null>(null)
const settings = ref<SystemSettings | null>(null)
const updateInfo = ref<SystemUpdateInfo | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
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
const configImportInput = ref<HTMLInputElement | null>(null)
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
  const items: Array<{
    id: SystemTab
    label: string
    icon: string
    visible: boolean
  }> = [
    { id: "overview", label: t("system.main.navOverview"), icon: "dashboard", visible: true },
    {
      id: "validation",
      label: t("system.main.navValidation"),
      icon: "activity",
      visible: auth.hasPermission("system.view")
    },
    { id: "general", label: t("system.main.general"), icon: "system", visible: true },
    {
      id: "time",
      label: t("system.main.time"),
      icon: "calendar",
      visible: auth.hasPermission("system.view")
    },
    {
      id: "users",
      label: t("system.main.navUsers"),
      icon: "users",
      visible: auth.hasPermission("user.manage")
    },
    {
      id: "tokens",
      label: t("system.main.navApiTokens"),
      icon: "shield",
      visible: true
    },
    {
      id: "oidc",
      label: t("system.main.navOidc"),
      icon: "users",
      visible: auth.hasPermission("user.manage")
    },
    {
      id: "notifications",
      label: t("system.main.notifications"),
      icon: "bell",
      visible: auth.hasPermission("notification.view")
    },
    {
      id: "alerts",
      label: t("system.main.navAlertRules"),
      icon: "bell",
      visible: auth.hasPermission("alert.manage")
    },
    {
      id: "ai",
      label: t("system.main.aiFrigate"),
      icon: "brain",
      visible: auth.hasPermission("integration.manage")
    },
    {
      id: "backup",
      label: t("system.main.backup"),
      icon: "backup",
      visible: auth.hasPermission("system.view")
    },
    {
      id: "audit",
      label: t("system.main.audit"),
      icon: "audit",
      visible: auth.hasPermission("audit.view")
    }
  ]
  return items.filter((item) => item.visible)
})

const healthComponents = computed(() =>
  Object.entries(health.value?.components ?? {})
)
const hostClockHealth = computed(
  () => health.value?.components.host_clock ?? null
)

const latestBackupByPolicy = computed(() => {
  const map = new Map<string, BackupSet>()
  for (const item of backups.value) {
    if (!map.has(item.backup_policy_id)) {
      map.set(item.backup_policy_id, item)
    }
  }
  return map
})

function backupPolicyName(policyId: string): string {
  return (
    backupPolicies.value.find(
      (policy) => policy.id === policyId
    )?.name ?? t("system.main.unknownPolicy")
  )
}

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

function openConfigurationValidation(): void {
  configImportInput.value?.click()
}

async function handleConfigurationFile(
  event: Event
): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ""
  if (!file) return

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
    !window.confirm(
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

function statusClass(value: string): string {
  const normalized = value.toUpperCase()
  if (
    normalized === "OK" ||
    normalized === "SENT" ||
    normalized === "COMPLETED" ||
    normalized === "VERIFIED"
  ) {
    return "status-pill--ok"
  }
  if (
    normalized === "ERROR" ||
    normalized === "FAILED"
  ) {
    return "status-pill--error"
  }
  return "status-pill--muted"
}

function stateLabel(value: string): string {
  const key = `system.main.state_${value.toLowerCase()}`
  return te(key) ? t(key) : value
}

function pretty(value: string): string {
  return value
    .replaceAll("_", " ")
    .replaceAll(".", " · ")
    .replace(/\b\w/g, (match) => match.toUpperCase())
}

function formatTime(value: string | null): string {
  if (!value) return "—"
  return new Intl.DateTimeFormat(locale.value, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false
  }).format(new Date(value))
}

function formatBytes(value: number | null): string {
  if (value === null) return "—"
  const units = ["B", "KB", "MB", "GB", "TB"]
  let amount = value
  let index = 0
  while (amount >= 1024 && index < units.length - 1) {
    amount /= 1024
    index += 1
  }
  return `${amount.toFixed(index === 0 ? 0 : 1)} ${units[index]}`
}

function healthMessage(item: HealthComponent): string {
  return item.message || t("system.main.healthy")
}

function healthDetail(
  item: HealthComponent | null,
  key: string
): string {
  const value = item?.details[key]
  if (
    typeof value === "string" ||
    typeof value === "number"
  ) {
    return String(value)
  }
  return "—"
}

interface StorageHealthTarget {
  id: string
  name: string
  path?: string
  level: "normal" | "warning" | "high" | "critical" | "unavailable"
  used_percent?: number
  free_bytes?: number
  total_bytes?: number
  warning_percent?: number
  high_percent?: number
  critical_percent?: number
  error?: string
}

function storageHealthTargets(
  component: HealthComponent
): StorageHealthTarget[] {
  const value = component.details.target_details
  if (!Array.isArray(value)) return []
  return value.filter(
    (item): item is StorageHealthTarget =>
      Boolean(
        item &&
          typeof item === "object" &&
          typeof (item as StorageHealthTarget).id === "string" &&
          typeof (item as StorageHealthTarget).name === "string" &&
          typeof (item as StorageHealthTarget).level === "string"
      )
  )
}

function storageHealthSummary(
  item: StorageHealthTarget
): string {
  if (item.level === "unavailable") {
    return pretty(item.error || "unavailable")
  }
  const used =
    typeof item.used_percent === "number"
      ? t("system.main.storageUsed", { used: item.used_percent.toFixed(1) })
      : t("system.main.usageUnavailable")
  const free =
    typeof item.free_bytes === "number"
      ? t("system.main.storageFree", { free: formatBytes(item.free_bytes) })
      : null
  return [used, free].filter(Boolean).join(" · ")
}

function storageHealthStatus(
  item: StorageHealthTarget
): HealthComponent["status"] {
  if (
    item.level === "critical" ||
    item.level === "unavailable"
  ) {
    return "ERROR"
  }
  if (
    item.level === "warning" ||
    item.level === "high"
  ) {
    return "DEGRADED"
  }
  return "OK"
}

function storageWatermarkSummary(
  item: StorageHealthTarget
): string | null {
  if (
    typeof item.warning_percent !== "number" ||
    typeof item.high_percent !== "number" ||
    typeof item.critical_percent !== "number"
  ) {
    return null
  }
  return t("system.main.watermarks", { warning: item.warning_percent, high: item.high_percent, critical: item.critical_percent })
}


async function loadBase(): Promise<void> {
  if (!auth.hasPermission("system.view")) return

  loading.value = true
  error.value = null
  try {
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
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    loading.value = false
  }
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

function addTimeNtpServer(): void {
  if (timeForm.ntpServers.length >= 4) return
  timeForm.ntpServers.push("")
}

function removeTimeNtpServer(index: number): void {
  timeForm.ntpServers.splice(index, 1)
  if (!timeForm.ntpServers.length) {
    timeForm.ntpServers.push("")
  }
}

function moveTimeNtpServer(
  index: number,
  direction: -1 | 1
): void {
  const target = index + direction
  if (
    target < 0 ||
    target >= timeForm.ntpServers.length
  ) {
    return
  }
  const [item] = timeForm.ntpServers.splice(
    index,
    1
  )
  timeForm.ntpServers.splice(target, 0, item)
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
  if (!window.confirm(t("system.main.deleteNotification", { name: item.name }))) {
    return
  }
  try {
    await deleteNotificationTarget(item.id)
    await loadNotifications()
  } catch (caught) {
    error.value = errorMessage(caught)
  }
}

function addFrigateMapping(): void {
  frigateMappings.value.push({
    frigate_camera: "",
    camera_id: cameras.value[0]?.id ?? ""
  })
}

function removeFrigateMapping(index: number): void {
  frigateMappings.value.splice(index, 1)
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

onMounted(() => {
  void loadBase()
  window.addEventListener("zero-nvr:refresh", handleRefreshEvent)
})

onBeforeUnmount(() => {
  window.removeEventListener("zero-nvr:refresh", handleRefreshEvent)
})
</script>

<template>
  <section class="system-workspace">
    <aside class="system-nav">
      <div class="system-nav__title">
        <strong>{{ t("system.main.title") }}</strong>
        <span>{{ info?.version || "zero-nvr" }}</span>
      </div>
      <nav>
        <button
          v-for="item in navigation"
          :key="item.id"
          type="button"
          :class="{ 'system-nav__active': tab === item.id }"
          @click="tab = item.id"
        >
          <UiIcon :name="item.icon" :size="15" />
          <span>{{ item.label }}</span>
        </button>
      </nav>
    </aside>

    <div class="system-content">
      <div v-if="error" class="events-error">
        <UiIcon name="warning" :size="16" />
        <span>{{ error }}</span>
      </div>

      <div v-if="notice" class="storage-notice">
        <UiIcon name="check" :size="15" />
        <span>{{ notice }}</span>
      </div>

      <template v-if="tab === 'overview'">
        <header class="system-page-header">
          <div>
            <strong>{{ t("system.main.overview") }}</strong>
            <span>{{ t("system.main.coreHealth") }}</span>
          </div>
          <button
            class="button button--ghost"
            type="button"
            :disabled="loading"
            @click="loadBase"
          >
            <UiIcon name="refresh" :size="14" />
            {{ t("system.main.refresh") }}
          </button>
        </header>

        <div class="system-overview-grid">
          <article class="system-overview-card system-overview-card--hero">
            <div>
              <span>{{ t("system.main.overallHealth") }}</span>
              <strong>{{ health?.status ? stateLabel(health.status) : "—" }}</strong>
            </div>
            <span
              class="system-health-orb"
              :class="`system-health-orb--${(health?.status || 'DISABLED').toLowerCase()}`"
            />
          </article>
          <article class="system-overview-card">
            <span>{{ t("system.main.version") }}</span>
            <strong>{{ info?.version || "—" }}</strong>
            <small>{{ info?.environment || "—" }}</small>
          </article>
          <article class="system-overview-card">
            <span>{{ t("system.main.database") }}</span>
            <strong>{{ pretty(info?.database_backend || "—") }}</strong>
            <small>{{ t("system.main.activeBackend") }}</small>
          </article>
          <article class="system-overview-card">
            <span>{{ t("system.main.updates") }}</span>
            <strong>{{ updateInfo?.status ? stateLabel(updateInfo.status) : t("system.main.unknown") }}</strong>
            <small>{{ updateInfo?.latest_version || t("system.main.noRemoteVersion") }}</small>
          </article>
        </div>

        <div class="system-section">
          <div class="system-section__heading">
            <strong>{{ t("system.main.components") }}</strong>
            <span>{{ t("system.main.liveHealth") }}</span>
          </div>
          <div class="health-component-grid">
            <article
              v-for="[name, component] in healthComponents"
              :key="name"
              class="health-component"
              :class="{
                'health-component--storage': name === 'storage'
              }"
            >
              <div class="health-component__title">
                <strong>{{ pretty(name) }}</strong>
                <span
                  class="status-pill"
                  :class="statusClass(component.status)"
                >
                  {{ stateLabel(component.status) }}
                </span>
              </div>
              <p>{{ healthMessage(component) }}</p>
              <div
                v-if="name === 'storage' && storageHealthTargets(component).length"
                class="storage-health-list"
              >
                <div
                  v-for="target in storageHealthTargets(component)"
                  :key="target.id"
                  class="storage-health-row"
                >
                  <div class="storage-health-row__main">
                    <strong>{{ target.name }}</strong>
                    <span>{{ storageHealthSummary(target) }}</span>
                  </div>
                  <span
                    class="status-pill"
                    :class="statusClass(storageHealthStatus(target))"
                  >
                    {{ stateLabel(target.level) }}
                  </span>
                  <small v-if="storageWatermarkSummary(target)">
                    {{ storageWatermarkSummary(target) }}
                  </small>
                </div>
              </div>
            </article>
          </div>
        </div>

        <SystemSecretStorePanel
          v-if="auth.hasPermission('system.view')"
        />
      </template>

      <template v-else-if="tab === 'validation'">
        <SystemReleaseValidationPanel />
      </template>

      <template v-else-if="tab === 'general'">
        <header class="system-page-header">
          <div>
            <strong>{{ t("system.main.general") }}</strong>
            <span>{{ t("system.main.generalDesc") }}</span>
          </div>
        </header>

        <form
          class="system-form-card"
          @submit.prevent="saveGeneral"
        >
          <label>
            <span>{{ t("system.main.systemName") }}</span>
            <input
              v-model="generalForm.systemName"
              required
              maxlength="128"
            />
            <small>
              {{ t("system.main.systemNameHint") }}
            </small>
          </label>

          <div class="system-form-actions">
            <button
              class="button button--primary"
              type="submit"
              :disabled="generalSaving || !auth.hasPermission('system.manage')"
            >
              {{ generalSaving ? t("system.main.saving") : t("system.main.saveGeneral") }}
            </button>
          </div>
        </form>

        <div class="system-section">
          <div class="system-section__heading">
            <strong>{{ t("system.main.runtimeTuning") }}</strong>
            <span>
              {{ t("system.main.runtimeHint") }}
            </span>
          </div>
          <form
            class="system-form-card system-form-card--wide"
            @submit.prevent="saveRuntime"
          >
            <div class="system-subsection">
              <div class="system-subsection__heading">
                <div>
                  <strong>{{ t("system.main.eventPrebuffer") }}</strong>
                  <span>
                    {{ t("system.main.eventPrebufferHint") }}
                  </span>
                </div>
              </div>
              <div class="system-form-row">
                <label>
                  <span>{{ t("system.main.fragmentSeconds") }}</span>
                  <input
                    v-model.number="runtimeForm.prebufferFragmentSeconds"
                    type="number"
                    min="2"
                    max="30"
                    required
                  />
                </label>
                <label>
                  <span>{{ t("system.main.bufferSeconds") }}</span>
                  <input
                    v-model.number="runtimeForm.prebufferBufferSeconds"
                    type="number"
                    min="10"
                    max="600"
                    required
                  />
                </label>
              </div>
              <small>
                {{ t("system.main.tmpfsHint") }}
              </small>
            </div>

            <div class="system-subsection">
              <div class="system-subsection__heading">
                <div>
                  <strong>{{ t("system.main.turnCredentials") }}</strong>
                  <span>
                    {{ t("system.main.turnHint") }}
                  </span>
                </div>
              </div>
              <div class="system-form-row">
                <label>
                  <span>{{ t("system.main.credentialTtl") }}</span>
                  <input
                    v-model.number="runtimeForm.turnCredentialTtlSeconds"
                    type="number"
                    min="60"
                    max="3600"
                    required
                  />
                </label>
              </div>
            </div>

            <div class="system-form-row">
              <label>
                <span>{{ t("system.main.playbackCacheLimit") }}</span>
                <input
                  v-model.number="runtimeForm.playbackCacheMiB"
                  type="number"
                  min="64"
                  max="1048576"
                  step="64"
                  required
                />
              </label>
              <label>
                <span>{{ t("system.main.playbackCacheTtl") }}</span>
                <input
                  v-model.number="runtimeForm.playbackCacheTtlSeconds"
                  type="number"
                  min="60"
                  max="604800"
                  required
                />
              </label>
              <label>
                <span>{{ t("system.main.restoreLockTtl") }}</span>
                <input
                  v-model.number="runtimeForm.playbackRestoreLockTtlSeconds"
                  type="number"
                  min="60"
                  max="604800"
                  required
                />
              </label>
            </div>

            <div class="system-subsection">
              <div class="system-subsection__heading">
                <div>
                  <strong>{{ t("system.main.compatTranscode") }}</strong>
                  <span>
                    {{ t("system.main.compatTranscodeHint") }}
                  </span>
                </div>
              </div>
              <div class="system-form-row">
                <label>
                  <span>{{ t("system.main.maxDerivatives") }}</span>
                  <input
                    v-model.number="runtimeForm.liveTranscodeMaxDerivatives"
                    type="number"
                    min="1"
                    max="8"
                    required
                  />
                </label>
                <label>
                  <span>{{ t("system.main.cpuThreads") }}</span>
                  <input
                    v-model.number="runtimeForm.liveTranscodeCpuThreads"
                    type="number"
                    min="1"
                    max="8"
                    required
                  />
                </label>
                <label>
                  <span>{{ t("system.main.videoBitrate") }}</span>
                  <input
                    v-model.number="runtimeForm.liveTranscodeVideoBitrateKbps"
                    type="number"
                    min="512"
                    max="20000"
                    step="128"
                    required
                  />
                </label>
              </div>
              <div class="system-form-row">
                <label>
                  <span>{{ t("system.main.idleTtl") }}</span>
                  <input
                    v-model.number="runtimeForm.liveTranscodeIdleTtlSeconds"
                    type="number"
                    min="5"
                    max="300"
                    required
                  />
                </label>
                <label>
                  <span>{{ t("system.main.leaseTtl") }}</span>
                  <input
                    v-model.number="runtimeForm.liveTranscodeLeaseTtlSeconds"
                    type="number"
                    min="15"
                    max="300"
                    required
                  />
                </label>
                <label>
                  <span>{{ t("system.main.startupTimeout") }}</span>
                  <input
                    v-model.number="runtimeForm.liveTranscodeStartupTimeoutSeconds"
                    type="number"
                    min="1"
                    max="30"
                    step="0.5"
                    required
                  />
                </label>
              </div>
            </div>

            <div class="system-form-actions">
              <button
                class="button button--primary"
                type="submit"
                :disabled="runtimeSaving || !auth.hasPermission('system.manage')"
              >
                {{ runtimeSaving ? t("system.main.saving") : t("system.main.saveRuntime") }}
              </button>
            </div>
          </form>
        </div>
      </template>

      <template v-else-if="tab === 'time'">
        <header class="system-page-header">
          <div>
            <strong>{{ t("system.main.time") }}</strong>
            <span>
              {{ t("system.main.timeDesc") }}
            </span>
          </div>
          <button
            class="button button--ghost"
            type="button"
            :disabled="cameraClockLoading"
            @click="checkCameraClocks"
          >
            <UiIcon name="refresh" :size="14" />
            {{
              cameraClockLoading
                ? t("system.main.checkingClocks")
                : t("system.main.checkClocks")
            }}
          </button>
        </header>

        <form
          class="system-form-card system-form-card--time"
          @submit.prevent="saveTime(false)"
        >
          <label>
            <span>{{ t("system.main.recordingTimezone") }}</span>
            <input
              v-model="timeForm.recordingTimezone"
              required
              placeholder="America/Los_Angeles"
              autocomplete="off"
            />
            <small>
              {{ t("system.main.recordingTimezoneHint") }}
            </small>
          </label>

          <label>
            <span>{{ t("system.main.managedNtp") }}</span>
            <select v-model="timeForm.ntpMode">
              <option value="dhcp">
                {{ t("system.main.dhcpNtp") }}
              </option>
              <option value="manual">
                {{ t("system.main.manualNtp") }}
              </option>
            </select>
            <small v-if="timeForm.ntpMode === 'dhcp'">
              {{ t("system.main.dhcpNtpHint") }}
            </small>
            <small v-else>
              {{ t("system.main.manualNtpHint") }}
            </small>
          </label>

          <div
            v-if="timeForm.ntpMode === 'manual'"
            class="time-ntp-list"
          >
            <div class="time-ntp-list__heading">
              <div>
                <strong>{{ t("system.main.manualNtp") }}</strong>
                <span>
                  {{ t("system.main.ntpPriorityHint") }}
                </span>
              </div>
              <button
                class="button button--ghost button--compact"
                type="button"
                :disabled="timeForm.ntpServers.length >= 4"
                @click="addTimeNtpServer"
              >
                <UiIcon name="plus" :size="13" />
                {{ t("system.main.addServer") }}
              </button>
            </div>

            <div class="time-ntp-list__rows">
              <div
                v-for="(server, index) in timeForm.ntpServers"
                :key="index"
                class="time-ntp-row"
              >
                <span class="time-ntp-row__priority">
                  {{ index + 1 }}
                </span>
                <input
                  v-model="timeForm.ntpServers[index]"
                  :aria-label="t('system.main.ntpServerPriority', { priority: index + 1 })"
                  placeholder="pool.ntp.org"
                  maxlength="253"
                  autocomplete="off"
                />
                <button
                  class="icon-button"
                  type="button"
                  :title="t('system.main.moveUp')"
                  :disabled="index === 0"
                  @click="moveTimeNtpServer(index, -1)"
                >
                  <UiIcon name="chevron-up" :size="13" />
                </button>
                <button
                  class="icon-button"
                  type="button"
                  :title="t('system.main.moveDown')"
                  :disabled="index === timeForm.ntpServers.length - 1"
                  @click="moveTimeNtpServer(index, 1)"
                >
                  <UiIcon name="chevron-down" :size="13" />
                </button>
                <button
                  class="icon-button icon-button--danger"
                  type="button"
                  :title="t('system.main.removeServer')"
                  @click="removeTimeNtpServer(index)"
                >
                  <UiIcon name="trash" :size="13" />
                </button>
              </div>
            </div>
          </div>

          <div class="time-policy-note">
            <UiIcon name="activity" :size="15" />
            <span>
              {{ t("system.main.timePolicyPrefix") }}
              <strong>{{ t("system.main.saveApply") }}</strong>
              {{ t("system.main.timePolicySuffix") }}
            </span>
          </div>

          <div class="system-form-actions">
            <button
              class="button button--ghost"
              type="submit"
              :disabled="timeSaving || !auth.hasPermission('system.manage')"
            >
              {{ timeSaving && !ntpApplying ? t("system.main.saving") : t("system.main.savePolicy") }}
            </button>
            <button
              class="button button--primary"
              type="button"
              :disabled="timeSaving || !auth.hasPermission('system.manage')"
              @click="saveTime(true)"
            >
              {{
                ntpApplying
                  ? t("system.main.savingApplying")
                  : t("system.main.saveApply")
              }}
            </button>
          </div>
        </form>

        <div
          v-if="hostClockHealth"
          class="host-clock-health"
        >
          <div class="host-clock-health__main">
            <div>
              <strong>{{ t("system.main.hostClock") }}</strong>
              <span>
                {{ t("system.main.canonicalTimeSource") }}
                {{ healthDetail(hostClockHealth, "canonical_timezone") }}
              </span>
            </div>
            <span
              class="status-pill"
              :class="statusClass(hostClockHealth.status)"
            >
              {{ stateLabel(hostClockHealth.status) }}
            </span>
          </div>
          <dl>
            <div>
              <dt>{{ t("system.main.syncState") }}</dt>
              <dd>
                {{
                  healthDetail(
                    hostClockHealth,
                    "sync_state"
                  )
                }}
              </dd>
            </div>
            <div>
              <dt>{{ t("system.main.estimatedOffset") }}</dt>
              <dd>
                {{
                  healthDetail(
                    hostClockHealth,
                    "estimated_offset_ms"
                  )
                }} ms
              </dd>
            </div>
            <div>
              <dt>{{ t("system.main.estimatedError") }}</dt>
              <dd>
                {{
                  healthDetail(
                    hostClockHealth,
                    "estimated_error_ms"
                  )
                }} ms
              </dd>
            </div>
            <div>
              <dt>{{ t("system.main.probe") }}</dt>
              <dd>
                {{
                  healthDetail(
                    hostClockHealth,
                    "source"
                  )
                }}
              </dd>
            </div>
          </dl>
          <p v-if="hostClockHealth.status === 'DISABLED'">
            {{ t("system.main.hostClockUnobservable") }}
          </p>
          <p v-else-if="hostClockHealth.status !== 'OK'">
            {{ t("system.main.hostClockUnsynced") }}
          </p>
        </div>

        <div
          v-if="ntpApplyResult"
          class="system-ntp-result"
        >
          <div>
            <strong>
              {{ t("system.main.cameraNtpApplied", { updated: ntpApplyResult.updated, total: ntpApplyResult.total_devices }) }}
            </strong>
            <span>
              {{
                ntpApplyResult.mode === "manual"
                  ? t("system.main.manualNtp")
                  : t("system.main.dhcpNtp")
              }}
            </span>
          </div>
          <span
            class="status-pill"
            :class="ntpApplyResult.failed ? 'status-pill--error' : 'status-pill--ok'"
          >
            {{ ntpApplyResult.failed ? t("system.main.partial") : t("system.main.appliedState") }}
          </span>
          <ul v-if="ntpApplyResult.failed">
            <li
              v-for="item in ntpApplyResult.results.filter(
                (entry) => entry.status === 'FAILED'
              )"
              :key="item.device_id"
            >
              {{ item.name }} · {{ item.error_code || "apply_failed" }}
            </li>
          </ul>
        </div>

        <div
          v-if="cameraClockHealth"
          class="camera-clock-health"
        >
          <header>
            <div>
              <strong>{{ t("system.main.cameraClockHealth") }}</strong>
              <span>
                {{ t("system.main.clockChecked", { count: cameraClockHealth.total_devices, time: formatTime(cameraClockHealth.checked_at) }) }}
              </span>
            </div>
            <span
              class="status-pill"
              :class="statusClass(cameraClockHealth.status)"
            >
              {{ cameraClockHealth.status }}
            </span>
          </header>

          <div
            v-if="!cameraClockHealth.results.length"
            class="camera-clock-health__empty"
          >
            {{ t("system.main.noOnvifClocks") }}
          </div>
          <div v-else class="camera-clock-health__rows">
            <article
              v-for="item in cameraClockHealth.results"
              :key="item.device_id"
            >
              <div>
                <strong>{{ item.name }}</strong>
                <span>
                  {{
                    item.error_code
                      ? pretty(item.error_code)
                      : `${item.date_time_type || t("system.main.unknownMode")} · ${item.timezone || t("system.main.timezoneUnknown")}`
                  }}
                </span>
              </div>
              <div class="camera-clock-health__metrics">
                <span>
                  {{ t("system.main.offset") }}
                  <strong>
                    {{
                      item.offset_ms === null
                        ? "—"
                        : `${item.offset_ms > 0 ? "+" : ""}${item.offset_ms} ms`
                    }}
                  </strong>
                </span>
                <span>
                  {{ t("system.main.rtt") }}
                  <strong>
                    {{
                      item.rtt_ms === null
                        ? "—"
                        : `${item.rtt_ms} ms`
                    }}
                  </strong>
                </span>
                <span>
                  {{ t("system.main.quality") }}
                  <strong>
                    {{ stateLabel(item.quality) }}
                  </strong>
                </span>
              </div>
              <span
                class="status-pill"
                :class="statusClass(item.status)"
              >
                {{ stateLabel(item.status) }}
              </span>
            </article>
          </div>
        </div>
      </template>

      <template v-else-if="tab === 'users'">
        <SystemAccessControlPanel />
      </template>

      <template v-else-if="tab === 'tokens'">
        <SystemApiTokensPanel />
      </template>

      <template v-else-if="tab === 'oidc'">
        <SystemOidcPanel />
      </template>

      <template v-else-if="tab === 'notifications'">
        <header class="system-page-header">
          <div>
            <strong>{{ t("system.main.notifications") }}</strong>
            <span>{{ t("system.main.notificationsDesc") }}</span>
          </div>
          <button
            v-if="auth.hasPermission('notification.manage')"
            class="button button--primary"
            type="button"
            @click="openNotificationPanel"
          >
            <UiIcon name="plus" :size="14" />
            {{ t("system.main.addTarget") }}
          </button>
        </header>

        <div class="notification-grid">
          <article
            v-for="item in targets"
            :key="item.id"
            class="notification-card"
          >
            <div class="notification-card__icon">
              <UiIcon name="bell" :size="19" />
            </div>
            <div class="notification-card__main">
              <strong>{{ item.name }}</strong>
              <span>
                {{ item.url_configured ? t("system.main.destinationConfigured") : t("system.main.destinationMissing") }}
                <template v-if="item.config.password_reset === true">
                  {{ t("system.main.passwordResetEmail") }}
                </template>
              </span>
            </div>
            <span
              class="status-pill"
              :class="item.enabled ? 'status-pill--ok' : 'status-pill--muted'"
            >
              {{ item.enabled ? t("system.main.enabled") : t("system.main.disabled") }}
            </span>
            <div
              v-if="auth.hasPermission('notification.manage')"
              class="notification-card__actions"
            >
              <button
                class="button button--ghost button--compact"
                type="button"
                :disabled="testingNotificationId === item.id"
                @click="testNotification(item)"
              >
                {{ testingNotificationId === item.id ? t("system.main.testing") : t("system.main.test") }}
              </button>
              <button
                class="icon-button"
                type="button"
                :title="t('system.main.editNotification')"
                @click="openEditNotification(item)"
              >
                <UiIcon name="system" :size="14" />
              </button>
              <button class="icon-button" type="button" @click="toggleNotification(item)">
                <UiIcon :name="item.enabled ? 'pause' : 'play'" :size="14" />
              </button>
              <button class="icon-button icon-button--danger" type="button" @click="removeNotification(item)">
                <UiIcon name="trash" :size="14" />
              </button>
            </div>
          </article>
        </div>

        <div class="system-section">
          <div class="system-section__heading">
            <strong>{{ t("system.main.recentDeliveries") }}</strong>
            <span>{{ t("system.main.recentDeliveriesHint") }}</span>
          </div>
          <div class="system-table-wrap">
            <table class="system-table">
              <thead>
                <tr>
                  <th>{{ t("system.main.message") }}</th>
                  <th>{{ t("system.main.purpose") }}</th>
                  <th>{{ t("system.main.status") }}</th>
                  <th>{{ t("system.main.attempts") }}</th>
                  <th>{{ t("system.main.sent") }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in deliveries" :key="item.id">
                  <td>
                    <strong>{{ item.title }}</strong>
                    <small>{{ item.last_error_code || item.body }}</small>
                  </td>
                  <td>{{ pretty(item.purpose) }}</td>
                  <td>
                    <span class="status-pill" :class="statusClass(item.state)">
                      {{ stateLabel(item.state) }}
                    </span>
                  </td>
                  <td>{{ item.attempt_count }}</td>
                  <td>{{ formatTime(item.sent_at || item.last_attempt_at) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <aside
          v-if="
            notificationPanelOpen &&
            auth.hasPermission('notification.manage')
          "
          class="system-drawer"
        >
          <header class="storage-editor__header">
            <div>
              <strong>
                {{
                  editingNotification
                    ? t("system.main.editNotification")
                    : t("system.main.addNotification")
                }}
              </strong>
              <span>{{ t("system.main.appriseCompatible") }}</span>
            </div>
            <button class="icon-button" type="button" @click="notificationPanelOpen = false; editingNotification = null">
              <UiIcon name="close" :size="16" />
            </button>
          </header>
          <form class="storage-editor__form" @submit.prevent="saveNotification">
            <label>
              <span>{{ t("system.main.name") }}</span>
              <input v-model="notificationForm.name" required />
            </label>
            <label>
              <span>{{ t("system.main.appriseUrl") }}</span>
              <textarea
                v-model="notificationForm.url"
                rows="7"
                :required="!editingNotification"
                spellcheck="false"
                :placeholder="
                  editingNotification
                    ? t("system.main.leaveDestination")
                    : 'mailto://user:pass@smtp.example.com?to=alerts@example.com'
                "
              />
              <small>
                {{
                  editingNotification
                    ? t("system.main.leaveEncryptedUrl")
                    : t("system.main.encryptedNeverReturned")
                }}
              </small>
            </label>
            <label class="storage-check">
              <input
                v-model="notificationForm.passwordReset"
                type="checkbox"
              />
              <span>
                {{ t("system.main.passwordResetTarget") }}
                <small>
                  {{ t("system.main.passwordResetHint") }}
                </small>
              </span>
            </label>
            <div class="storage-editor__actions">
              <button class="button button--ghost" type="button" @click="notificationPanelOpen = false; editingNotification = null">
                {{ t("system.main.cancel") }}
              </button>
              <button class="button button--primary" type="submit" :disabled="notificationSaving">
                {{
                  notificationSaving
                    ? t("system.main.saving")
                    : editingNotification
                      ? t("system.main.saveTarget")
                      : t("system.main.createTarget")
                }}
              </button>
            </div>
          </form>
        </aside>
      </template>

      <template v-else-if="tab === 'alerts'">
        <SystemAlertRulesPanel
          :display-timezone="
            settings?.general.display_timezone || 'UTC'
          "
        />
      </template>

      <template v-else-if="tab === 'ai'">
        <header class="system-page-header">
          <div>
            <strong>{{ t("system.main.aiFrigate") }}</strong>
            <span>{{ t("system.main.frigateDesc") }}</span>
          </div>
          <div class="system-page-actions">
            <button
              v-if="frigateConfigured"
              class="button button--ghost"
              type="button"
              :disabled="frigateTesting"
              @click="testFrigate"
            >
              <UiIcon name="activity" :size="14" />
              {{ frigateTesting ? t("system.main.testing") : t("system.main.test") }}
            </button>
            <button
              v-if="frigateConfigured && frigateForm.enabled"
              class="button button--ghost"
              type="button"
              @click="queueBackfill"
            >
              {{ t("system.main.backfill10m") }}
            </button>
          </div>
        </header>

        <form class="system-form-card system-form-card--wide" @submit.prevent="saveFrigate">
          <div class="system-form-row">
            <label>
              <span>{{ t("system.main.mode") }}</span>
              <select v-model="frigateForm.mode">
                <option value="external">{{ t("system.main.externalFrigate") }}</option>
                <option value="managed">{{ t("system.main.managedProfile") }}</option>
              </select>
            </label>
            <label>
              <span>{{ t("system.main.baseUrl") }}</span>
              <input
                v-model="frigateForm.baseUrl"
                required
                placeholder="http://frigate:5000"
              />
            </label>
          </div>

          <label class="storage-check">
            <input v-model="frigateForm.enabled" type="checkbox" />
            <span>{{ t("system.main.enableFrigate") }}</span>
          </label>

          <div class="system-subsection">
            <div class="system-subsection__heading">
              <div>
                <strong>{{ t("system.main.cameraMapping") }}</strong>
                <span>{{ t("system.main.cameraMappingHint") }}</span>
              </div>
              <button class="button button--ghost button--compact" type="button" @click="addFrigateMapping">
                <UiIcon name="plus" :size="13" />
                {{ t("system.main.addMapping") }}
              </button>
            </div>
            <div class="frigate-mapping-list">
              <div
                v-for="(mapping, index) in frigateMappings"
                :key="index"
                class="frigate-mapping-row"
              >
                <input
                  v-model="mapping.frigate_camera"
                  placeholder="front_door"
                />
                <UiIcon name="next" :size="13" />
                <select v-model="mapping.camera_id">
                  <option value="" disabled>{{ t("system.main.selectCamera") }}</option>
                  <option
                    v-for="camera in cameras"
                    :key="camera.id"
                    :value="camera.id"
                  >
                    {{ camera.name }}
                  </option>
                </select>
                <button class="icon-button icon-button--danger" type="button" @click="removeFrigateMapping(index)">
                  <UiIcon name="trash" :size="14" />
                </button>
              </div>
            </div>
          </div>

          <div class="system-subsection">
            <div class="system-subsection__heading">
              <div>
                <strong>{{ t("system.main.httpCredentials") }}</strong>
                <span>{{ t("system.main.keepCredentials") }}</span>
              </div>
              <span v-if="frigateConfigured" class="status-pill">
                {{ t("system.main.existing") }} {{ frigateConfigured ? t("system.main.configured") : t("system.main.none") }}
              </span>
            </div>
            <div class="system-form-row system-form-row--three">
              <label>
                <span>{{ t("system.main.bearerToken") }}</span>
                <input v-model="frigateForm.bearerToken" type="password" />
              </label>
              <label>
                <span>{{ t("system.main.username") }}</span>
                <input v-model="frigateForm.httpUsername" />
              </label>
              <label>
                <span>{{ t("system.main.password") }}</span>
                <input v-model="frigateForm.httpPassword" type="password" />
              </label>
            </div>
          </div>

          <div class="system-subsection">
            <div class="system-subsection__heading">
              <div>
                <strong>{{ t("system.main.mqtt") }}</strong>
                <span>{{ t("system.main.mqttHint") }}</span>
              </div>
              <label class="storage-check">
                <input v-model="frigateForm.mqttEnabled" type="checkbox" />
                <span>{{ t("system.main.enableMqtt") }}</span>
              </label>
            </div>
            <div class="system-form-row system-form-row--three">
              <label>
                <span>{{ t("system.main.host") }}</span>
                <input v-model="frigateForm.mqttHost" placeholder="mosquitto" />
              </label>
              <label>
                <span>{{ t("system.main.port") }}</span>
                <input v-model.number="frigateForm.mqttPort" type="number" min="1" max="65535" />
              </label>
              <label>
                <span>{{ t("system.main.topicPrefix") }}</span>
                <input v-model="frigateForm.mqttTopicPrefix" />
              </label>
            </div>
          </div>

          <div class="system-form-actions">
            <span v-if="frigateVersion" class="system-form-hint">
              Frigate {{ frigateVersion }}
            </span>
            <button class="button button--primary" type="submit" :disabled="frigateSaving">
              {{ frigateSaving ? t("system.main.saving") : t("system.main.saveFrigate") }}
            </button>
          </div>
        </form>
      </template>

      <template v-else-if="tab === 'backup'">
        <header class="system-page-header">
          <div>
            <strong>{{ t("system.main.backup") }}</strong>
            <span>{{ t("system.main.backupDesc") }}</span>
          </div>
          <div
            v-if="auth.hasPermission('system.manage')"
            class="system-page-actions"
          >
            <input
              ref="configImportInput"
              type="file"
              accept=".json,application/json"
              hidden
              @change="handleConfigurationFile"
            />
            <button
              class="button button--ghost"
              type="button"
              :disabled="configImportValidating"
              @click="openConfigurationValidation"
            >
              <UiIcon name="check" :size="14" />
              {{
                configImportValidating
                  ? t("system.main.validating")
                  : t("system.main.validateImport")
              }}
            </button>
            <button
              class="button button--ghost"
              type="button"
              @click="exportConfiguration"
            >
              <UiIcon name="download" :size="14" />
              {{ t("system.main.exportConfig") }}
            </button>
            <button
              class="button button--ghost"
              type="button"
              :disabled="backupRefreshing"
              @click="loadBackups"
            >
              <UiIcon name="refresh" :size="14" />
              {{ backupRefreshing ? t("system.main.refreshing") : t("system.main.refresh") }}
            </button>
            <button
              class="button button--primary"
              type="button"
              @click="openBackupPanel"
            >
              <UiIcon name="plus" :size="14" />
              {{ t("system.main.addPolicy") }}
            </button>
          </div>
        </header>

        <section class="backup-recovery-card">
          <div class="backup-recovery-card__heading">
            <div>
              <strong>{{ t("system.main.disasterRecovery") }}</strong>
              <span>
                {{ t("system.main.disasterRecoveryHint") }}
              </span>
            </div>
            <span class="status-pill">{{ t("system.main.restoreHostOnly") }}</span>
          </div>

          <SystemRecoveryKitPanel
            :policies="backupPolicies"
          />

          <div class="backup-recovery-commands">
            <div>
              <span>{{ t("system.main.listSnapshots") }}</span>
              <code>./deploy.sh restore list</code>
              <button
                class="button button--ghost button--compact"
                type="button"
                @click="copyHostCommand('./deploy.sh restore list')"
              >
                {{ t("system.main.copy") }}
              </button>
            </div>

            <div>
              <span>{{ t("system.main.restoreLatest") }}</span>
              <code>./deploy.sh restore latest --force</code>
              <button
                class="button button--ghost button--compact"
                type="button"
                @click="
                  copyHostCommand(
                    './deploy.sh restore latest --force'
                  )
                "
              >
                {{ t("system.main.copy") }}
              </button>
            </div>

            <div>
              <span>{{ t("system.main.exportRecoveryKit") }}</span>
              <code>./deploy.sh recovery-kit export</code>
              <button
                class="button button--ghost button--compact"
                type="button"
                @click="
                  copyHostCommand(
                    './deploy.sh recovery-kit export'
                  )
                "
              >
                {{ t("system.main.copy") }}
              </button>
            </div>

            <div>
              <span>{{ t("system.main.decryptKit") }}</span>
              <code>./deploy.sh recovery-kit decrypt /path/to/kit.znrk ./recovery-kit-restored</code>
              <button
                class="button button--ghost button--compact"
                type="button"
                @click="
                  copyHostCommand(
                    './deploy.sh recovery-kit decrypt /path/to/kit.znrk ./recovery-kit-restored'
                  )
                "
              >
                {{ t("system.main.copy") }}
              </button>
            </div>
          </div>

          <div class="storage-notice">
            <UiIcon name="warning" :size="14" />
            <span>
              {{ t("system.main.restoreWarning") }}
            </span>
          </div>
        </section>

        <section
          v-if="configImportValidation"
          class="backup-policy-card"
        >
          <div class="backup-policy-card__top">
            <div>
              <strong>{{ t("system.main.configPreflight") }}</strong>
              <span>
                {{
                  configImportFileName
                    ? `${configImportFileName} · ready to merge`
                    : t("system.main.readyMerge")
                }}
              </span>
            </div>
            <span class="status-pill status-pill--ok">
              {{ t("system.main.valid") }}
            </span>
          </div>

          <div class="system-summary-grid">
            <div>
              <span>{{ t("system.main.format") }}</span>
              <strong>
                {{ configImportValidation.format }} v{{
                  configImportValidation.format_version
                }}
              </strong>
            </div>
            <div>
              <span>{{ t("system.main.sourceVersion") }}</span>
              <strong>
                {{
                  configImportValidation.source_application_version ||
                  t("system.main.unknown")
                }}
              </strong>
            </div>
            <div>
              <span>{{ t("system.main.credentialsRequired") }}</span>
              <strong>
                {{
                  configImportValidation.credentials_required.length
                }}
              </strong>
            </div>
          </div>

          <div class="system-table-wrap">
            <table class="system-table">
              <thead>
                <tr>
                  <th>{{ t("system.main.section") }}</th>
                  <th>{{ t("system.main.resources") }}</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="(count, sectionName) in configImportValidation.section_counts"
                  :key="sectionName"
                >
                  <td>{{ pretty(String(sectionName)) }}</td>
                  <td>{{ count }}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div
            v-if="configImportValidation.credentials_required.length"
            class="system-table-wrap"
          >
            <table class="system-table">
              <thead>
                <tr>
                  <th>{{ t("system.main.credentialReenter") }}</th>
                  <th>{{ t("system.main.resource") }}</th>
                  <th>{{ t("system.main.section") }}</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="(item, index) in configImportValidation.credentials_required"
                  :key="`${item.section}-${item.resource_id || index}-${item.credential}`"
                >
                  <td>{{ pretty(item.credential) }}</td>
                  <td>
                    <strong>
                      {{ item.name || pretty(item.resource_type) }}
                    </strong>
                    <small v-if="item.resource_id">
                      {{ item.resource_id }}
                    </small>
                  </td>
                  <td>{{ pretty(item.section) }}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div
            v-for="warning in configImportValidation.warnings"
            :key="warning"
            class="storage-notice"
          >
            <UiIcon name="warning" :size="14" />
            <span>{{ warning }}</span>
          </div>

          <div class="storage-notice">
            <UiIcon name="check" :size="14" />
            <span>
              {{ t("system.main.preflightHint") }}
            </span>
          </div>

          <div
            v-if="!configImportApplyResult"
            class="system-form-actions"
          >
            <button
              class="button button--ghost"
              type="button"
              :disabled="configImportApplying"
              @click="discardConfigurationImport"
            >
              {{ t("system.main.discard") }}
            </button>
            <button
              class="button button--primary"
              type="button"
              :disabled="
                configImportApplying ||
                !configImportBundle ||
                !auth.hasPermission('system.manage')
              "
              @click="applyValidatedConfigurationImport"
            >
              {{
                configImportApplying
                  ? t("system.main.applying")
                  : t("system.main.applyConfigMerge")
              }}
            </button>
          </div>

          <div
            v-else
            class="configuration-import-result"
          >
            <div class="system-summary-grid">
              <div>
                <span>{{ t("system.main.applied") }}</span>
                <strong>
                  {{ configImportApplyResult.applied_count }}
                </strong>
              </div>
              <div>
                <span>{{ t("system.main.skipped") }}</span>
                <strong>
                  {{ configImportApplyResult.skipped_count }}
                </strong>
              </div>
              <div>
                <span>{{ t("system.main.mode") }}</span>
                <strong>{{ pretty(configImportApplyResult.mode) }}</strong>
              </div>
            </div>

            <div
              v-if="configImportApplyResult.applied.length"
              class="system-table-wrap"
            >
              <table class="system-table">
                <thead>
                  <tr>
                    <th>{{ t("system.main.appliedResource") }}</th>
                    <th>{{ t("system.main.section") }}</th>
                    <th>{{ t("system.main.action") }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="(item, index) in configImportApplyResult.applied"
                    :key="`applied-${item.section}-${item.target_id || item.source_id || index}`"
                  >
                    <td>
                      <strong>
                        {{ item.name || pretty(item.resource_type) }}
                      </strong>
                      <small v-if="item.target_id">
                        {{ item.target_id }}
                      </small>
                    </td>
                    <td>{{ pretty(item.section) }}</td>
                    <td>
                      <span class="status-pill status-pill--ok">
                        {{ pretty(item.action) }}
                      </span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div
              v-if="configImportApplyResult.skipped.length"
              class="system-table-wrap"
            >
              <table class="system-table">
                <thead>
                  <tr>
                    <th>{{ t("system.main.skippedResource") }}</th>
                    <th>{{ t("system.main.section") }}</th>
                    <th>{{ t("system.main.reason") }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="(item, index) in configImportApplyResult.skipped"
                    :key="`skipped-${item.section}-${item.source_id || index}`"
                  >
                    <td>
                      <strong>
                        {{ item.name || pretty(item.resource_type) }}
                      </strong>
                    </td>
                    <td>{{ pretty(item.section) }}</td>
                    <td>
                      {{ pretty(item.reason || "skipped") }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div
              v-for="warning in configImportApplyResult.warnings"
              :key="`applied-${warning}`"
              class="storage-notice"
            >
              <UiIcon name="warning" :size="14" />
              <span>{{ warning }}</span>
            </div>

            <div class="system-form-actions">
              <button
                class="button button--ghost"
                type="button"
                @click="discardConfigurationImport"
              >
                {{ t("system.main.closeResult") }}
              </button>
            </div>
          </div>
        </section>

        <div class="backup-policy-grid">
          <article
            v-for="policy in backupPolicies"
            :key="policy.id"
            class="backup-policy-card"
          >
            <div class="backup-policy-card__top">
              <div>
                <strong>{{ policy.name }}</strong>
                <span>
                  {{
                    policy.schedule.cron
                      ? String(policy.schedule.cron)
                      : t("system.main.manualOnly")
                  }}
                </span>
              </div>
              <span
                class="status-pill"
                :class="policy.enabled ? 'status-pill--ok' : 'status-pill--muted'"
              >
                {{ policy.enabled ? t("system.main.enabled") : t("system.main.disabled") }}
              </span>
            </div>
            <dl>
              <div>
                <dt>{{ t("system.main.database") }}</dt>
                <dd>{{ policy.database_backend }}</dd>
              </div>
              <div>
                <dt>{{ t("system.main.verify") }}</dt>
                <dd>{{ policy.verify_after_backup ? t("system.main.afterEveryRun") : t("system.main.manual") }}</dd>
              </div>
              <div>
                <dt>{{ t("system.main.lastRun") }}</dt>
                <dd>
                  {{
                    latestBackupByPolicy.get(policy.id)
                      ? formatTime(latestBackupByPolicy.get(policy.id)!.started_at)
                      : t("system.main.never")
                  }}
                </dd>
              </div>
            </dl>
            <div
              v-if="auth.hasPermission('system.manage')"
              class="system-form-actions"
            >
              <button
                class="button button--ghost"
                type="button"
                @click="openEditBackupPolicy(policy)"
              >
                <UiIcon name="settings" :size="14" />
                {{ t("system.main.edit") }}
              </button>
              <button
                class="button button--ghost"
                type="button"
                :disabled="runningBackupId === policy.id"
                @click="runPolicy(policy)"
              >
                <UiIcon name="backup" :size="14" />
                {{ runningBackupId === policy.id ? t("system.main.starting") : t("system.main.runNow") }}
              </button>
            </div>
          </article>
        </div>

        <div class="system-section">
          <div class="system-section__heading">
            <strong>{{ t("system.main.backupHistory") }}</strong>
            <span>{{ t("system.main.backupHistoryHint") }}</span>
          </div>
          <div class="system-table-wrap">
            <table class="system-table">
              <thead>
                <tr>
                  <th>{{ t("system.main.backup") }}</th>
                  <th>{{ t("system.main.state") }}</th>
                  <th>{{ t("system.main.size") }}</th>
                  <th>{{ t("system.main.verification") }}</th>
                  <th>{{ t("system.main.version") }}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in backups" :key="item.id">
                  <td>
                    <strong>
                      {{ backupPolicyName(item.backup_policy_id) }}
                    </strong>
                    <small>
                      {{ formatTime(item.started_at) }} ·
                      {{ pretty(item.reason) }}
                    </small>
                    <small v-if="item.error_code">
                      {{ pretty(item.error_code) }}
                      <template v-if="item.sanitized_error">
                        · {{ item.sanitized_error }}
                      </template>
                    </small>
                  </td>
                  <td>
                    <span class="status-pill" :class="statusClass(item.state)">
                      {{ stateLabel(item.state) }}
                    </span>
                  </td>
                  <td>{{ formatBytes(item.size_bytes) }}</td>
                  <td>{{ stateLabel(item.verification_state) }}</td>
                  <td>{{ item.app_version }}</td>
                  <td class="system-table__actions">
                    <button
                      v-if="auth.hasPermission('system.manage') && item.state === 'COMPLETED'"
                      class="button button--ghost button--compact"
                      type="button"
                      :disabled="verifyingBackupId === item.id"
                      @click="verifySet(item)"
                    >
                      {{ verifyingBackupId === item.id ? t("system.main.queuing") : t("system.main.verify") }}
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <aside v-if="backupPanelOpen" class="system-drawer">
          <header class="storage-editor__header">
            <div>
              <strong>
                {{
                  editingBackupPolicy
                    ? t("system.main.editBackupPolicy")
                    : t("system.main.addBackupPolicy")
                }}
              </strong>
              <span>{{ t("system.main.resticRepository") }}</span>
            </div>
            <button class="icon-button" type="button" @click="backupPanelOpen = false; editingBackupPolicy = null">
              <UiIcon name="close" :size="16" />
            </button>
          </header>
          <form class="storage-editor__form" @submit.prevent="saveBackupPolicy">
            <label>
              <span>{{ t("system.main.name") }}</span>
              <input v-model="backupForm.name" required />
            </label>
            <label>
              <span>{{ t("system.main.repository") }}</span>
              <input
                v-model="backupForm.repository"
                :required="!editingBackupPolicy"
                :placeholder="
                  editingBackupPolicy
                    ? t("system.main.leaveRepo")
                    : '/backups/zero-nvr or s3:...'
                "
              />
              <small v-if="editingBackupPolicy">
                {{ t("system.main.repositoryKeepHint") }}
              </small>
            </label>
            <label>
              <span>{{ t("system.main.resticPassword") }}</span>
              <input
                v-model="backupForm.password"
                type="password"
                :required="!editingBackupPolicy"
                autocomplete="new-password"
              />
              <small v-if="editingBackupPolicy">
                {{ t("system.main.passwordKeepHint") }}
              </small>
            </label>
            <label>
              <span>{{ t("system.main.repoEnvCredentials") }}</span>
              <textarea
                v-model="backupForm.environmentCredentials"
                rows="5"
                spellcheck="false"
                placeholder="AWS_ACCESS_KEY_ID=…&#10;AWS_SECRET_ACCESS_KEY=…"
              />
              <small>
                {{ t("system.main.repoEnvHint") }}
                {{
                  editingBackupPolicy
                    ? t("system.main.leaveEnv")
                    : t("system.main.envBackendHint")
                }}
              </small>
            </label>
            <label
              v-if="!editingBackupPolicy"
              class="storage-check"
            >
              <input v-model="backupForm.initializeIfMissing" type="checkbox" />
              <span>{{ t("system.main.initRepository") }}</span>
            </label>
            <label class="storage-check">
              <input v-model="backupForm.enabled" type="checkbox" />
              <span>{{ t("system.main.policyEnabled") }}</span>
            </label>
            <label class="storage-check">
              <input v-model="backupForm.scheduled" type="checkbox" />
              <span>{{ t("system.main.scheduled") }}</span>
            </label>
            <label v-if="backupForm.scheduled">
              <span>{{ t("system.main.cron") }}</span>
              <input v-model="backupForm.cron" placeholder="0 3 * * *" />
              <small>{{ t("system.main.cronTimezone") }} {{ settings?.general.display_timezone || "UTC" }}</small>
            </label>
            <div class="retention-days-grid">
              <label>
                <span>{{ t("system.main.keepLast") }}</span>
                <input v-model.number="backupForm.keepLast" type="number" min="0" />
              </label>
              <label>
                <span>{{ t("system.main.daily") }}</span>
                <input v-model.number="backupForm.keepDaily" type="number" min="0" />
              </label>
              <label>
                <span>{{ t("system.main.weekly") }}</span>
                <input v-model.number="backupForm.keepWeekly" type="number" min="0" />
              </label>
              <label>
                <span>{{ t("system.main.monthly") }}</span>
                <input v-model.number="backupForm.keepMonthly" type="number" min="0" />
              </label>
            </div>
            <label class="storage-check">
              <input v-model="backupForm.verifyAfter" type="checkbox" />
              <span>{{ t("system.main.verifyAfter") }}</span>
            </label>
            <label class="storage-check">
              <input v-model="backupForm.includeDeploymentConfig" type="checkbox" />
              <span>{{ t("system.main.includeDeployment") }}</span>
            </label>
            <div class="storage-editor__actions">
              <button class="button button--ghost" type="button" @click="backupPanelOpen = false; editingBackupPolicy = null">
                {{ t("system.main.cancel") }}
              </button>
              <button class="button button--primary" type="submit" :disabled="backupSaving">
                {{
                  backupSaving
                    ? t("system.main.saving")
                    : editingBackupPolicy
                      ? t("system.main.saveBackupPolicy")
                      : t("system.main.createBackupPolicy")
                }}
              </button>
            </div>
          </form>
        </aside>
      </template>

      <template v-else-if="tab === 'audit'">
        <header class="system-page-header">
          <div>
            <strong>{{ t("system.main.audit") }}</strong>
            <span>{{ t("system.main.auditDesc") }}</span>
          </div>
          <button
            class="button button--ghost"
            type="button"
            :disabled="auditLoading"
            @click="loadAudit"
          >
            <UiIcon name="refresh" :size="14" />
            {{ auditLoading ? t("system.main.refreshing") : t("system.main.refresh") }}
          </button>
        </header>

        <div class="audit-toolbar">
          <label class="audit-filter">
            <span>{{ t("system.main.period") }}</span>
            <select
              v-model="auditFilters.period"
              @change="loadAudit"
            >
              <option value="24h">{{ t("system.main.last24h") }}</option>
              <option value="7d">{{ t("system.main.last7d") }}</option>
              <option value="30d">{{ t("system.main.last30d") }}</option>
              <option value="all">{{ t("system.main.allTime") }}</option>
            </select>
          </label>

          <label class="audit-filter">
            <span>{{ t("system.main.action") }}</span>
            <input
              v-model="auditFilters.action"
              placeholder="camera.update"
              @keydown.enter="loadAudit"
            />
          </label>

          <label class="audit-filter">
            <span>{{ t("system.main.resource") }}</span>
            <input
              v-model="auditFilters.resourceType"
              placeholder="camera"
              @keydown.enter="loadAudit"
            />
          </label>

          <label class="audit-filter">
            <span>{{ t("system.main.result") }}</span>
            <select
              v-model="auditFilters.result"
              @change="loadAudit"
            >
              <option value="">{{ t("system.main.allResults") }}</option>
              <option value="success">{{ t("system.main.success") }}</option>
              <option value="failed">{{ t("system.main.failed") }}</option>
              <option value="denied">{{ t("system.main.denied") }}</option>
            </select>
          </label>

          <div class="audit-toolbar__actions">
            <button
              class="button button--ghost button--compact"
              type="button"
              @click="resetAuditFilters"
            >
              {{ t("system.main.clear") }}
            </button>
            <button
              class="button button--primary button--compact"
              type="button"
              :disabled="auditLoading"
              @click="loadAudit"
            >
              {{ t("system.main.apply") }}
            </button>
          </div>
        </div>

        <div
          v-if="auditLoading && !auditEvents.length"
          class="audit-empty"
        >
          {{ t("system.main.loadingAudit") }}
        </div>

        <div
          v-else-if="!auditEvents.length"
          class="audit-empty"
        >
          {{ t("system.main.noAudit") }}
        </div>

        <div v-else class="audit-list">
          <article v-for="item in auditEvents" :key="item.id">
            <span class="audit-list__icon">
              <UiIcon name="audit" :size="15" />
            </span>
            <div class="audit-list__main">
              <strong>{{ pretty(item.action) }}</strong>
              <span>
                {{ pretty(item.resource_type) }}
                <template v-if="item.source_ip"> · {{ item.source_ip }}</template>
                <template v-if="item.reason"> · {{ pretty(item.reason) }}</template>
              </span>
            </div>
            <span class="status-pill" :class="statusClass(item.result)">
              {{ stateLabel(item.result) }}
            </span>
            <time>{{ formatTime(item.occurred_at) }}</time>
          </article>
        </div>

        <button
          v-if="auditNextCursor"
          class="audit-load-more"
          type="button"
          :disabled="auditLoadingMore"
          @click="loadMoreAudit"
        >
          {{
            auditLoadingMore
              ? t("system.main.loading")
              : t("system.main.loadMore")
          }}
        </button>
      </template>
    </div>
  </section>
</template>


<style scoped>
.audit-toolbar {
  display: grid;
  grid-template-columns:
    minmax(110px, 0.7fr)
    minmax(150px, 1fr)
    minmax(140px, 1fr)
    minmax(120px, 0.8fr)
    auto;
  gap: 7px;
  align-items: end;
  margin-bottom: 10px;
  padding: 8px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--surface-raised);
}

.audit-filter {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.audit-filter > span {
  color: var(--text-muted);
  font-size: 7px;
  font-weight: 650;
  text-transform: uppercase;
}

.audit-filter input,
.audit-filter select {
  width: 100%;
  min-height: 30px;
  padding: 0 7px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  outline: 0;
  background: var(--surface-base);
  color: var(--text-primary);
  font: inherit;
  font-size: 8px;
}

.audit-filter input:focus,
.audit-filter select:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--focus-ring);
}

.audit-toolbar__actions {
  display: flex;
  gap: 5px;
  justify-content: flex-end;
}

.audit-empty {
  padding: 28px 12px;
  color: var(--text-muted);
  font-size: 9px;
  text-align: center;
}

.audit-load-more {
  width: 100%;
  margin-top: 8px;
  padding: 8px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-secondary);
  font: inherit;
  font-size: 8px;
  cursor: pointer;
}

.audit-load-more:hover:not(:disabled) {
  background: var(--surface-hover);
  color: var(--text-primary);
}

@media (max-width: 980px) {
  .audit-toolbar {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .audit-toolbar__actions {
    grid-column: 1 / -1;
  }
}
</style>


<style scoped>
.backup-recovery-card {
  display: grid;
  gap: 10px;
  margin-bottom: 10px;
  padding: 11px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--surface-raised);
}

.backup-recovery-card__heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.backup-recovery-card__heading strong,
.backup-recovery-card__heading span {
  display: block;
}

.backup-recovery-card__heading strong {
  font-size: 10px;
}

.backup-recovery-card__heading div > span {
  max-width: 680px;
  margin-top: 2px;
  color: var(--text-muted);
  font-size: 8px;
  line-height: 1.45;
}

.backup-recovery-commands {
  display: grid;
  gap: 5px;
}

.backup-recovery-commands > div {
  display: grid;
  grid-template-columns:
    minmax(180px, 0.9fr)
    minmax(260px, 1.4fr)
    auto;
  align-items: center;
  gap: 8px;
  padding: 6px 7px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: var(--surface-base);
}

.backup-recovery-commands span {
  color: var(--text-secondary);
  font-size: 8px;
}

.backup-recovery-commands code {
  overflow-x: auto;
  color: var(--text-primary);
  font-size: 8px;
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
