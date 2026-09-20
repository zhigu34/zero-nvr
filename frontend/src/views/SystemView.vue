<script setup lang="ts">
import {
  computed,
  onBeforeUnmount,
  onMounted,
  reactive,
  ref,
  watch
} from "vue"

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
  verifyBackup,
  type AuditEvent,
  type BackupPolicy,
  type CameraClockHealth,
  type CameraNtpApplyResult,
  type BackupSet,
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
import SystemAlertRulesPanel from "../components/system/SystemAlertRulesPanel.vue"
import UiIcon from "../components/ui/UiIcon.vue"
import { useAuthStore } from "../stores/auth"

type SystemTab =
  | "overview"
  | "general"
  | "users"
  | "tokens"
  | "notifications"
  | "alerts"
  | "ai"
  | "backup"
  | "audit"

const auth = useAuthStore()
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
const runningBackupId = ref<string | null>(null)
const verifyingBackupId = ref<string | null>(null)
const backupForm = reactive({
  name: "System backup",
  repository: "",
  password: "",
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
const generalForm = reactive({
  systemName: "",
  displayTimezone: "UTC",
  ntpServers: ""
})
const generalSaving = ref(false)
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
    { id: "overview", label: "Overview", icon: "dashboard", visible: true },
    { id: "general", label: "General", icon: "system", visible: true },
    {
      id: "users",
      label: "Users",
      icon: "users",
      visible: auth.hasPermission("user.manage")
    },
    {
      id: "tokens",
      label: "API tokens",
      icon: "shield",
      visible: true
    },
    {
      id: "notifications",
      label: "Notifications",
      icon: "bell",
      visible: auth.hasPermission("alert.manage")
    },
    {
      id: "alerts",
      label: "Alert rules",
      icon: "bell",
      visible: auth.hasPermission("alert.manage")
    },
    {
      id: "ai",
      label: "AI / Frigate",
      icon: "brain",
      visible: auth.hasPermission("integration.manage")
    },
    {
      id: "backup",
      label: "Backup",
      icon: "backup",
      visible: auth.hasPermission("system.view")
    },
    {
      id: "audit",
      label: "Audit",
      icon: "audit",
      visible: auth.hasPermission("audit.view")
    }
  ]
  return items.filter((item) => item.visible)
})

const healthComponents = computed(() =>
  Object.entries(health.value?.components ?? {})
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

function pretty(value: string): string {
  return value
    .replaceAll("_", " ")
    .replaceAll(".", " · ")
    .replace(/\b\w/g, (match) => match.toUpperCase())
}

function formatTime(value: string | null): string {
  if (!value) return "—"
  return new Intl.DateTimeFormat(undefined, {
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
  return item.message || "Healthy"
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
    generalForm.displayTimezone =
      settingsValue.general.display_timezone
    generalForm.ntpServers =
      settingsValue.general.camera_ntp_servers.join("\n")
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    loading.value = false
  }
}

async function loadNotifications(): Promise<void> {
  if (!auth.hasPermission("alert.manage")) return
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
  try {
    const [policyPage, backupPage] = await Promise.all([
      listBackupPolicies(),
      listBackups()
    ])
    backupPolicies.value = policyPage
    backups.value = backupPage.items
  } catch (caught) {
    error.value = errorMessage(caught)
  }
}

async function loadAudit(): Promise<void> {
  if (!auth.hasPermission("audit.view")) return
  try {
    auditEvents.value = (await listAuditEvents()).items
  } catch (caught) {
    error.value = errorMessage(caught)
  }
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
    const updated = await patchSystemSettings({
      system_name: generalForm.systemName.trim(),
      display_timezone: generalForm.displayTimezone.trim(),
      camera_ntp_servers: generalForm.ntpServers
        .split(/\r?\n|,/)
        .map((item) => item.trim())
        .filter(Boolean)
    })
    settings.value = updated
    ntpApplyResult.value = null
    try {
      const applied = await applyCameraNtpSettings()
      ntpApplyResult.value = applied
      if (applied.total_devices === 0) {
        notice.value =
          "General settings saved. No enabled ONVIF devices were found for NTP configuration."
      } else if (applied.failed === 0) {
        notice.value =
          `General settings saved. NTP applied to ${applied.updated} ONVIF device(s).`
      } else {
        notice.value =
          `General settings saved. NTP applied to ${applied.updated}/${applied.total_devices} ONVIF device(s).`
      }
    } catch (caught) {
      error.value =
        `General settings were saved, but camera NTP apply failed: ${errorMessage(caught)}`
    }
    if (ntpApplyResult.value?.updated) {
      await checkCameraClocks()
    }
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    generalSaving.value = false
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
      const changes: Record<string, unknown> = { name }
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
      notice.value = "Notification target updated."
    } else {
      await createNotificationTarget(
        name,
        url,
        {
          password_reset: notificationForm.passwordReset
        }
      )
      notice.value = "Notification target created."
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
    notice.value = `${item.name} test notification sent.`
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
  if (!window.confirm(`Delete notification target "${item.name}"?`)) {
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
        : null,
      replace_credentials: hasCredentials
    })
    frigateForm.bearerToken = ""
    frigateForm.httpUsername = ""
    frigateForm.httpPassword = ""
    frigateForm.mqttUsername = ""
    frigateForm.mqttPassword = ""
    frigateConfigured.value = true
    notice.value = "Frigate settings saved."
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
    notice.value = `Frigate connected${result.version ? ` · ${result.version}` : ""}.`
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    frigateTesting.value = false
  }
}

async function queueBackfill(): Promise<void> {
  try {
    await backfillFrigate(600)
    notice.value = "Frigate event backfill queued."
  } catch (caught) {
    error.value = errorMessage(caught)
  }
}

function openBackupPanel(): void {
  editingBackupPolicy.value = null
  backupForm.name = "System backup"
  backupForm.repository = ""
  backupForm.password = ""
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
    settings.value?.general.display_timezone || "UTC"
  try {
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
        credentials?: { password?: string }
      } = {
        name: backupForm.name.trim(),
        enabled: backupForm.enabled,
        schedule,
        retention,
        verify_after_backup: backupForm.verifyAfter,
        include_deployment_config:
          backupForm.includeDeploymentConfig
      }

      if (backupForm.repository.trim()) {
        changes.repository = backupForm.repository.trim()
      }
      if (backupForm.password) {
        changes.credentials = {
          password: backupForm.password
        }
      }

      await updateBackupPolicy(
        editingBackupPolicy.value.id,
        changes
      )
      notice.value = "Backup policy updated."
    } else {
      await createBackupPolicy({
        name: backupForm.name.trim(),
        enabled: backupForm.enabled,
        repository: backupForm.repository.trim(),
        credentials: {
          password: backupForm.password,
          environment: {}
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
      notice.value = "Backup policy created."
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
    notice.value = `Backup started for ${policy.name}.`
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
    notice.value = "Backup verification queued."
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
        <strong>System</strong>
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
            <strong>System overview</strong>
            <span>Core health and runtime status.</span>
          </div>
          <button
            class="button button--ghost"
            type="button"
            :disabled="loading"
            @click="loadBase"
          >
            <UiIcon name="refresh" :size="14" />
            Refresh
          </button>
        </header>

        <div class="system-overview-grid">
          <article class="system-overview-card system-overview-card--hero">
            <div>
              <span>Overall health</span>
              <strong>{{ health?.status || "—" }}</strong>
            </div>
            <span
              class="system-health-orb"
              :class="`system-health-orb--${(health?.status || 'DISABLED').toLowerCase()}`"
            />
          </article>
          <article class="system-overview-card">
            <span>Version</span>
            <strong>{{ info?.version || "—" }}</strong>
            <small>{{ info?.environment || "—" }}</small>
          </article>
          <article class="system-overview-card">
            <span>Database</span>
            <strong>{{ pretty(info?.database_backend || "—") }}</strong>
            <small>Active backend</small>
          </article>
          <article class="system-overview-card">
            <span>Updates</span>
            <strong>{{ pretty(updateInfo?.status || "unknown") }}</strong>
            <small>{{ updateInfo?.latest_version || "No remote version reported" }}</small>
          </article>
        </div>

        <div class="system-section">
          <div class="system-section__heading">
            <strong>Components</strong>
            <span>Live health checks from the control plane.</span>
          </div>
          <div class="health-component-grid">
            <article
              v-for="[name, component] in healthComponents"
              :key="name"
              class="health-component"
            >
              <div class="health-component__title">
                <strong>{{ pretty(name) }}</strong>
                <span
                  class="status-pill"
                  :class="statusClass(component.status)"
                >
                  {{ component.status }}
                </span>
              </div>
              <p>{{ healthMessage(component) }}</p>
            </article>
          </div>
        </div>
      </template>

      <template v-else-if="tab === 'general'">
        <header class="system-page-header">
          <div>
            <strong>General</strong>
            <span>Identity, display timezone and camera time sources.</span>
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
                ? "Checking clocks…"
                : "Check camera clocks"
            }}
          </button>
        </header>

        <form
          class="system-form-card"
          @submit.prevent="saveGeneral"
        >
          <label>
            <span>System name</span>
            <input
              v-model="generalForm.systemName"
              required
              maxlength="128"
            />
          </label>
          <label>
            <span>Display timezone</span>
            <input
              v-model="generalForm.displayTimezone"
              required
              placeholder="America/Los_Angeles"
            />
            <small>IANA timezone used by the UI and scheduled jobs.</small>
          </label>
          <label>
            <span>Camera NTP servers</span>
            <textarea
              v-model="generalForm.ntpServers"
              rows="5"
              placeholder="pool.ntp.org&#10;time.cloudflare.com"
            />
            <small>
              One hostname or IP per line. Leave empty to use DHCP-provided
              NTP. Saving applies the canonical setting to enabled ONVIF
              devices and switches their clock mode to NTP.
            </small>
          </label>

          <div
            v-if="ntpApplyResult"
            class="system-ntp-result"
          >
            <strong>
              Camera NTP ·
              {{ ntpApplyResult.updated }}/{{ ntpApplyResult.total_devices }}
              updated
            </strong>
            <span>
              {{
                ntpApplyResult.mode === "manual"
                  ? "Manual NTP servers"
                  : "DHCP-provided NTP"
              }}
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
                <strong>Camera clock health</strong>
                <span>
                  {{ cameraClockHealth.total_devices }} enabled ONVIF device(s)
                  · checked {{ formatTime(cameraClockHealth.checked_at) }}
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
              No enabled ONVIF devices to inspect.
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
                        : `${item.date_time_type || "Unknown mode"} · ${item.timezone || "timezone unknown"}`
                    }}
                  </span>
                </div>
                <div class="camera-clock-health__metrics">
                  <span>
                    Offset
                    <strong>
                      {{
                        item.offset_ms === null
                          ? "—"
                          : `${item.offset_ms > 0 ? "+" : ""}${item.offset_ms} ms`
                      }}
                    </strong>
                  </span>
                  <span>
                    RTT
                    <strong>
                      {{
                        item.rtt_ms === null
                          ? "—"
                          : `${item.rtt_ms} ms`
                      }}
                    </strong>
                  </span>
                </div>
                <span
                  class="status-pill"
                  :class="statusClass(item.status)"
                >
                  {{ item.status }}
                </span>
              </article>
            </div>
          </div>

          <div class="system-form-actions">
            <button
              class="button button--primary"
              type="submit"
              :disabled="generalSaving || !auth.hasPermission('system.manage')"
            >
              {{ generalSaving ? "Saving…" : "Save settings" }}
            </button>
          </div>
        </form>
      </template>

      <template v-else-if="tab === 'users'">
        <SystemAccessControlPanel />
      </template>

      <template v-else-if="tab === 'tokens'">
        <SystemApiTokensPanel />
      </template>

      <template v-else-if="tab === 'notifications'">
        <header class="system-page-header">
          <div>
            <strong>Notifications</strong>
            <span>Apprise targets for alerts, including SMTP and push services.</span>
          </div>
          <button
            class="button button--primary"
            type="button"
            @click="openNotificationPanel"
          >
            <UiIcon name="plus" :size="14" />
            Add target
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
                {{ item.url_configured ? "Destination configured" : "Destination missing" }}
                <template v-if="item.config.password_reset === true">
                  · Password reset email
                </template>
              </span>
            </div>
            <span
              class="status-pill"
              :class="item.enabled ? 'status-pill--ok' : 'status-pill--muted'"
            >
              {{ item.enabled ? "Enabled" : "Disabled" }}
            </span>
            <div class="notification-card__actions">
              <button
                class="button button--ghost button--compact"
                type="button"
                :disabled="testingNotificationId === item.id"
                @click="testNotification(item)"
              >
                {{ testingNotificationId === item.id ? "Testing…" : "Test" }}
              </button>
              <button
                class="icon-button"
                type="button"
                title="Edit target"
                @click="openEditNotification(item)"
              >
                <UiIcon name="settings" :size="14" />
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
            <strong>Recent deliveries</strong>
            <span>Latest alert and security notification attempts.</span>
          </div>
          <div class="system-table-wrap">
            <table class="system-table">
              <thead>
                <tr>
                  <th>Message</th>
                  <th>Purpose</th>
                  <th>Status</th>
                  <th>Attempts</th>
                  <th>Sent</th>
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
                      {{ item.state }}
                    </span>
                  </td>
                  <td>{{ item.attempt_count }}</td>
                  <td>{{ formatTime(item.sent_at || item.last_attempt_at) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <aside v-if="notificationPanelOpen" class="system-drawer">
          <header class="storage-editor__header">
            <div>
              <strong>
                {{
                  editingNotification
                    ? "Edit notification target"
                    : "Add notification target"
                }}
              </strong>
              <span>Any Apprise-compatible URL</span>
            </div>
            <button class="icon-button" type="button" @click="notificationPanelOpen = false; editingNotification = null">
              <UiIcon name="close" :size="16" />
            </button>
          </header>
          <form class="storage-editor__form" @submit.prevent="saveNotification">
            <label>
              <span>Name</span>
              <input v-model="notificationForm.name" required />
            </label>
            <label>
              <span>Apprise URL</span>
              <textarea
                v-model="notificationForm.url"
                rows="7"
                :required="!editingNotification"
                spellcheck="false"
                :placeholder="
                  editingNotification
                    ? 'Leave blank to keep the existing destination'
                    : 'mailto://user:pass@smtp.example.com?to=alerts@example.com'
                "
              />
              <small>
                {{
                  editingNotification
                    ? "Leave blank to keep the existing encrypted URL."
                    : "Stored encrypted and never returned to the browser."
                }}
              </small>
            </label>
            <label class="storage-check">
              <input
                v-model="notificationForm.passwordReset"
                type="checkbox"
              />
              <span>
                Use as password reset email target
                <small>
                  Requires mailto/mailtos. zero-nvr replaces To/CC/BCC
                  with the account email for each reset message.
                </small>
              </span>
            </label>
            <div class="storage-editor__actions">
              <button class="button button--ghost" type="button" @click="notificationPanelOpen = false; editingNotification = null">
                Cancel
              </button>
              <button class="button button--primary" type="submit" :disabled="notificationSaving">
                {{
                  notificationSaving
                    ? "Saving…"
                    : editingNotification
                      ? "Save target"
                      : "Create target"
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
            <strong>AI / Frigate</strong>
            <span>External or managed Frigate event provider.</span>
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
              {{ frigateTesting ? "Testing…" : "Test" }}
            </button>
            <button
              v-if="frigateConfigured && frigateForm.enabled"
              class="button button--ghost"
              type="button"
              @click="queueBackfill"
            >
              Backfill 10m
            </button>
          </div>
        </header>

        <form class="system-form-card system-form-card--wide" @submit.prevent="saveFrigate">
          <div class="system-form-row">
            <label>
              <span>Mode</span>
              <select v-model="frigateForm.mode">
                <option value="external">External Frigate</option>
                <option value="managed">Managed profile</option>
              </select>
            </label>
            <label>
              <span>Base URL</span>
              <input
                v-model="frigateForm.baseUrl"
                required
                placeholder="http://frigate:5000"
              />
            </label>
          </div>

          <label class="storage-check">
            <input v-model="frigateForm.enabled" type="checkbox" />
            <span>Enable Frigate event ingest</span>
          </label>

          <div class="system-subsection">
            <div class="system-subsection__heading">
              <div>
                <strong>Camera mapping</strong>
                <span>Map Frigate camera keys to zero-nvr cameras.</span>
              </div>
              <button class="button button--ghost button--compact" type="button" @click="addFrigateMapping">
                <UiIcon name="plus" :size="13" />
                Add mapping
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
                  <option value="" disabled>Select camera</option>
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
                <strong>HTTP credentials</strong>
                <span>Leave blank to keep existing credentials.</span>
              </div>
              <span v-if="frigateConfigured" class="status-pill">
                Existing: {{ frigateConfigured ? "configured" : "none" }}
              </span>
            </div>
            <div class="system-form-row system-form-row--three">
              <label>
                <span>Bearer token</span>
                <input v-model="frigateForm.bearerToken" type="password" />
              </label>
              <label>
                <span>Username</span>
                <input v-model="frigateForm.httpUsername" />
              </label>
              <label>
                <span>Password</span>
                <input v-model="frigateForm.httpPassword" type="password" />
              </label>
            </div>
          </div>

          <div class="system-subsection">
            <div class="system-subsection__heading">
              <div>
                <strong>MQTT</strong>
                <span>Optional low-latency Frigate event ingest.</span>
              </div>
              <label class="storage-check">
                <input v-model="frigateForm.mqttEnabled" type="checkbox" />
                <span>Enable MQTT</span>
              </label>
            </div>
            <div class="system-form-row system-form-row--three">
              <label>
                <span>Host</span>
                <input v-model="frigateForm.mqttHost" placeholder="mosquitto" />
              </label>
              <label>
                <span>Port</span>
                <input v-model.number="frigateForm.mqttPort" type="number" min="1" max="65535" />
              </label>
              <label>
                <span>Topic prefix</span>
                <input v-model="frigateForm.mqttTopicPrefix" />
              </label>
            </div>
          </div>

          <div class="system-form-actions">
            <span v-if="frigateVersion" class="system-form-hint">
              Frigate {{ frigateVersion }}
            </span>
            <button class="button button--primary" type="submit" :disabled="frigateSaving">
              {{ frigateSaving ? "Saving…" : "Save Frigate" }}
            </button>
          </div>
        </form>
      </template>

      <template v-else-if="tab === 'backup'">
        <header class="system-page-header">
          <div>
            <strong>Backup</strong>
            <span>Restic-backed configuration, database and recovery backups.</span>
          </div>
          <button
            v-if="auth.hasPermission('system.manage')"
            class="button button--primary"
            type="button"
            @click="openBackupPanel"
          >
            <UiIcon name="plus" :size="14" />
            Add policy
          </button>
        </header>

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
                      : "Manual only"
                  }}
                </span>
              </div>
              <span
                class="status-pill"
                :class="policy.enabled ? 'status-pill--ok' : 'status-pill--muted'"
              >
                {{ policy.enabled ? "Enabled" : "Disabled" }}
              </span>
            </div>
            <dl>
              <div>
                <dt>Database</dt>
                <dd>{{ policy.database_backend }}</dd>
              </div>
              <div>
                <dt>Verify</dt>
                <dd>{{ policy.verify_after_backup ? "After every run" : "Manual" }}</dd>
              </div>
              <div>
                <dt>Last run</dt>
                <dd>
                  {{
                    latestBackupByPolicy.get(policy.id)
                      ? formatTime(latestBackupByPolicy.get(policy.id)!.started_at)
                      : "Never"
                  }}
                </dd>
              </div>
            </dl>
            <button
              v-if="auth.hasPermission('system.manage')"
              class="button button--ghost"
              type="button"
              :disabled="runningBackupId === policy.id"
              @click="runPolicy(policy)"
            >
              <UiIcon name="backup" :size="14" />
              {{ runningBackupId === policy.id ? "Starting…" : "Run now" }}
            </button>
          </article>
        </div>

        <div class="system-section">
          <div class="system-section__heading">
            <strong>Backup history</strong>
            <span>Recent backup sets and verification state.</span>
          </div>
          <div class="system-table-wrap">
            <table class="system-table">
              <thead>
                <tr>
                  <th>Started</th>
                  <th>State</th>
                  <th>Size</th>
                  <th>Verification</th>
                  <th>Version</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in backups" :key="item.id">
                  <td>{{ formatTime(item.started_at) }}</td>
                  <td>
                    <span class="status-pill" :class="statusClass(item.state)">
                      {{ item.state }}
                    </span>
                  </td>
                  <td>{{ formatBytes(item.size_bytes) }}</td>
                  <td>{{ item.verification_state }}</td>
                  <td>{{ item.app_version }}</td>
                  <td class="system-table__actions">
                    <button
                      v-if="auth.hasPermission('system.manage') && item.state === 'COMPLETED'"
                      class="button button--ghost button--compact"
                      type="button"
                      :disabled="verifyingBackupId === item.id"
                      @click="verifySet(item)"
                    >
                      {{ verifyingBackupId === item.id ? "Queuing…" : "Verify" }}
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
                    ? "Edit backup policy"
                    : "Add backup policy"
                }}
              </strong>
              <span>Restic repository</span>
            </div>
            <button class="icon-button" type="button" @click="backupPanelOpen = false; editingBackupPolicy = null">
              <UiIcon name="close" :size="16" />
            </button>
          </header>
          <form class="storage-editor__form" @submit.prevent="saveBackupPolicy">
            <label>
              <span>Name</span>
              <input v-model="backupForm.name" required />
            </label>
            <label>
              <span>Repository</span>
              <input
                v-model="backupForm.repository"
                :required="!editingBackupPolicy"
                :placeholder="
                  editingBackupPolicy
                    ? 'Leave blank to keep the existing repository'
                    : '/backups/zero-nvr or s3:...'
                "
              />
              <small v-if="editingBackupPolicy">
                Leave blank to keep the existing encrypted repository.
              </small>
            </label>
            <label>
              <span>Restic password</span>
              <input
                v-model="backupForm.password"
                type="password"
                :required="!editingBackupPolicy"
                autocomplete="new-password"
              />
              <small v-if="editingBackupPolicy">
                Leave blank to keep the current password. A password-only change preserves repository environment credentials.
              </small>
            </label>
            <label
              v-if="!editingBackupPolicy"
              class="storage-check"
            >
              <input v-model="backupForm.initializeIfMissing" type="checkbox" />
              <span>Initialize repository if missing</span>
            </label>
            <label class="storage-check">
              <input v-model="backupForm.enabled" type="checkbox" />
              <span>Policy enabled</span>
            </label>
            <label class="storage-check">
              <input v-model="backupForm.scheduled" type="checkbox" />
              <span>Run on a schedule</span>
            </label>
            <label v-if="backupForm.scheduled">
              <span>Cron</span>
              <input v-model="backupForm.cron" placeholder="0 3 * * *" />
              <small>Five-field cron, timezone: {{ settings?.general.display_timezone || "UTC" }}</small>
            </label>
            <div class="retention-days-grid">
              <label>
                <span>Keep last</span>
                <input v-model.number="backupForm.keepLast" type="number" min="0" />
              </label>
              <label>
                <span>Daily</span>
                <input v-model.number="backupForm.keepDaily" type="number" min="0" />
              </label>
              <label>
                <span>Weekly</span>
                <input v-model.number="backupForm.keepWeekly" type="number" min="0" />
              </label>
              <label>
                <span>Monthly</span>
                <input v-model.number="backupForm.keepMonthly" type="number" min="0" />
              </label>
            </div>
            <label class="storage-check">
              <input v-model="backupForm.verifyAfter" type="checkbox" />
              <span>Verify after every backup</span>
            </label>
            <label class="storage-check">
              <input v-model="backupForm.includeDeploymentConfig" type="checkbox" />
              <span>Include deployment configuration / RecoveryKit inputs</span>
            </label>
            <div class="storage-editor__actions">
              <button class="button button--ghost" type="button" @click="backupPanelOpen = false; editingBackupPolicy = null">
                Cancel
              </button>
              <button class="button button--primary" type="submit" :disabled="backupSaving">
                {{
                  backupSaving
                    ? "Saving…"
                    : editingBackupPolicy
                      ? "Save policy"
                      : "Create policy"
                }}
              </button>
            </div>
          </form>
        </aside>
      </template>

      <template v-else-if="tab === 'audit'">
        <header class="system-page-header">
          <div>
            <strong>Audit</strong>
            <span>Recent privileged actions and configuration changes.</span>
          </div>
          <button class="button button--ghost" type="button" @click="loadAudit">
            <UiIcon name="refresh" :size="14" />
            Refresh
          </button>
        </header>

        <div class="audit-list">
          <article v-for="item in auditEvents" :key="item.id">
            <span class="audit-list__icon">
              <UiIcon name="audit" :size="15" />
            </span>
            <div class="audit-list__main">
              <strong>{{ pretty(item.action) }}</strong>
              <span>
                {{ pretty(item.resource_type) }}
                <template v-if="item.source_ip"> · {{ item.source_ip }}</template>
              </span>
            </div>
            <span class="status-pill" :class="statusClass(item.result)">
              {{ item.result }}
            </span>
            <time>{{ formatTime(item.occurred_at) }}</time>
          </article>
        </div>
      </template>
    </div>
  </section>
</template>
