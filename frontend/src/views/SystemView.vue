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
  backfillFrigate,
  createBackupPolicy,
  createNotificationTarget,
  createUser,
  deleteNotificationTarget,
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
  listRoles,
  listUsers,
  patchSystemSettings,
  putFrigateProvider,
  runBackup,
  setUserEnabled,
  testFrigateProvider,
  testNotificationTarget,
  updateNotificationTarget,
  verifyBackup,
  type AdminUser,
  type AuditEvent,
  type BackupPolicy,
  type BackupSet,
  type FrigateCameraMapping,
  type HealthComponent,
  type NotificationDelivery,
  type NotificationTarget,
  type Role,
  type SystemHealth,
  type SystemInfo,
  type SystemSettings,
  type SystemUpdateInfo
} from "../api/system"
import UiIcon from "../components/ui/UiIcon.vue"
import { useAuthStore } from "../stores/auth"

type SystemTab =
  | "overview"
  | "general"
  | "users"
  | "notifications"
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

const users = ref<AdminUser[]>([])
const roles = ref<Role[]>([])
const cameras = ref<CameraSummary[]>([])
const userPanelOpen = ref(false)
const userSaving = ref(false)
const userForm = reactive({
  username: "",
  displayName: "",
  email: "",
  password: "",
  roleIds: [] as string[]
})

const targets = ref<NotificationTarget[]>([])
const deliveries = ref<NotificationDelivery[]>([])
const notificationPanelOpen = ref(false)
const notificationSaving = ref(false)
const testingNotificationId = ref<string | null>(null)
const notificationForm = reactive({
  name: "",
  url: ""
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
  includeDeploymentConfig: true
})

const auditEvents = ref<AuditEvent[]>([])
const generalForm = reactive({
  systemName: "",
  displayTimezone: "UTC",
  ntpServers: ""
})
const generalSaving = ref(false)

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
      id: "notifications",
      label: "Notifications",
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

async function loadUsers(): Promise<void> {
  if (!auth.hasPermission("user.manage")) return
  try {
    ;[users.value, roles.value] = await Promise.all([
      listUsers(),
      listRoles()
    ])
  } catch (caught) {
    error.value = errorMessage(caught)
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
  if (value === "users") await loadUsers()
  if (value === "notifications") await loadNotifications()
  if (value === "ai") await loadFrigate()
  if (value === "backup") await loadBackups()
  if (value === "audit") await loadAudit()
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
    notice.value = "General settings saved."
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    generalSaving.value = false
  }
}

function openUserPanel(): void {
  userForm.username = ""
  userForm.displayName = ""
  userForm.email = ""
  userForm.password = ""
  const defaultRole = roles.value.find((role) => role.name === "Viewer")
  userForm.roleIds = defaultRole ? [defaultRole.id] : []
  userPanelOpen.value = true
}

async function saveUser(): Promise<void> {
  userSaving.value = true
  error.value = null
  try {
    await createUser({
      username: userForm.username.trim(),
      display_name: userForm.displayName.trim(),
      email: userForm.email.trim() || null,
      password: userForm.password,
      role_ids: userForm.roleIds
    })
    userPanelOpen.value = false
    notice.value = "User created."
    await loadUsers()
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    userSaving.value = false
  }
}

async function toggleUser(user: AdminUser): Promise<void> {
  try {
    await setUserEnabled(user.id, !user.enabled)
    await loadUsers()
  } catch (caught) {
    error.value = errorMessage(caught)
  }
}

function openNotificationPanel(): void {
  notificationForm.name = ""
  notificationForm.url = ""
  notificationPanelOpen.value = true
}

async function saveNotification(): Promise<void> {
  notificationSaving.value = true
  error.value = null
  try {
    await createNotificationTarget(
      notificationForm.name.trim(),
      notificationForm.url.trim()
    )
    notificationPanelOpen.value = false
    notice.value = "Notification target created."
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
  backupPanelOpen.value = true
}

async function saveBackupPolicy(): Promise<void> {
  backupSaving.value = true
  error.value = null
  const timezone =
    settings.value?.general.display_timezone || "UTC"
  try {
    await createBackupPolicy({
      name: backupForm.name.trim(),
      enabled: true,
      repository: backupForm.repository.trim(),
      credentials: {
        password: backupForm.password,
        environment: {}
      },
      initialize_if_missing: backupForm.initializeIfMissing,
      database_backend: info.value?.database_backend || "sqlite",
      schedule: backupForm.scheduled
        ? {
            cron: backupForm.cron.trim(),
            timezone
          }
        : {},
      retention: {
        keep_last: Number(backupForm.keepLast),
        keep_daily: Number(backupForm.keepDaily),
        keep_weekly: Number(backupForm.keepWeekly),
        keep_monthly: Number(backupForm.keepMonthly)
      },
      verify_after_backup: backupForm.verifyAfter,
      repository_check_schedule: {},
      include_deployment_config: backupForm.includeDeploymentConfig
    })
    backupPanelOpen.value = false
    notice.value = "Backup policy created."
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
            <small>One hostname or IP per line; zero-nvr configures cameras that support ONVIF time settings.</small>
          </label>
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
        <header class="system-page-header">
          <div>
            <strong>Users</strong>
            <span>Accounts and role assignments.</span>
          </div>
          <button
            class="button button--primary"
            type="button"
            @click="openUserPanel"
          >
            <UiIcon name="plus" :size="14" />
            Add user
          </button>
        </header>

        <div class="system-table-wrap">
          <table class="system-table">
            <thead>
              <tr>
                <th>User</th>
                <th>Roles</th>
                <th>Email</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              <tr v-for="user in users" :key="user.id">
                <td>
                  <strong>{{ user.display_name }}</strong>
                  <small>@{{ user.username }}</small>
                </td>
                <td>
                  {{ user.roles.map((role) => role.name).join(", ") || "No roles" }}
                </td>
                <td>{{ user.email || "—" }}</td>
                <td>
                  <span
                    class="status-pill"
                    :class="user.enabled ? 'status-pill--ok' : 'status-pill--muted'"
                  >
                    {{ user.enabled ? "Enabled" : "Disabled" }}
                  </span>
                </td>
                <td class="system-table__actions">
                  <button
                    class="button button--ghost button--compact"
                    type="button"
                    @click="toggleUser(user)"
                  >
                    {{ user.enabled ? "Disable" : "Enable" }}
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <aside v-if="userPanelOpen" class="system-drawer">
          <header class="storage-editor__header">
            <div>
              <strong>Add user</strong>
              <span>Local zero-nvr account</span>
            </div>
            <button class="icon-button" type="button" @click="userPanelOpen = false">
              <UiIcon name="close" :size="16" />
            </button>
          </header>
          <form class="storage-editor__form" @submit.prevent="saveUser">
            <label>
              <span>Username</span>
              <input v-model="userForm.username" required />
            </label>
            <label>
              <span>Display name</span>
              <input v-model="userForm.displayName" required />
            </label>
            <label>
              <span>Email</span>
              <input v-model="userForm.email" type="email" />
            </label>
            <label>
              <span>Initial password</span>
              <input
                v-model="userForm.password"
                type="password"
                minlength="12"
                required
              />
            </label>
            <fieldset class="system-role-list">
              <legend>Roles</legend>
              <label v-for="role in roles" :key="role.id">
                <input
                  v-model="userForm.roleIds"
                  type="checkbox"
                  :value="role.id"
                />
                <span>
                  <strong>{{ role.name }}</strong>
                  <small>{{ role.description || "No description" }}</small>
                </span>
              </label>
            </fieldset>
            <div class="storage-editor__actions">
              <button class="button button--ghost" type="button" @click="userPanelOpen = false">
                Cancel
              </button>
              <button class="button button--primary" type="submit" :disabled="userSaving">
                {{ userSaving ? "Saving…" : "Create user" }}
              </button>
            </div>
          </form>
        </aside>
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
            <span>Latest alert notification attempts.</span>
          </div>
          <div class="system-table-wrap">
            <table class="system-table">
              <thead>
                <tr>
                  <th>Message</th>
                  <th>Status</th>
                  <th>Attempts</th>
                  <th>Delivered</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in deliveries" :key="item.id">
                  <td>
                    <strong>{{ item.title }}</strong>
                    <small>{{ item.last_error_code || item.body }}</small>
                  </td>
                  <td>
                    <span class="status-pill" :class="statusClass(item.state)">
                      {{ item.state }}
                    </span>
                  </td>
                  <td>{{ item.attempts }}</td>
                  <td>{{ formatTime(item.delivered_at || item.last_attempt_at) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <aside v-if="notificationPanelOpen" class="system-drawer">
          <header class="storage-editor__header">
            <div>
              <strong>Add notification target</strong>
              <span>Any Apprise-compatible URL</span>
            </div>
            <button class="icon-button" type="button" @click="notificationPanelOpen = false">
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
                required
                spellcheck="false"
                placeholder="mailto://user:pass@smtp.example.com?to=alerts@example.com"
              />
              <small>Stored encrypted and never returned to the browser.</small>
            </label>
            <div class="storage-editor__actions">
              <button class="button button--ghost" type="button" @click="notificationPanelOpen = false">
                Cancel
              </button>
              <button class="button button--primary" type="submit" :disabled="notificationSaving">
                {{ notificationSaving ? "Saving…" : "Create target" }}
              </button>
            </div>
          </form>
        </aside>
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
              <strong>Add backup policy</strong>
              <span>Restic repository</span>
            </div>
            <button class="icon-button" type="button" @click="backupPanelOpen = false">
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
              <input v-model="backupForm.repository" required placeholder="/backups/zero-nvr or s3:..." />
            </label>
            <label>
              <span>Restic password</span>
              <input v-model="backupForm.password" type="password" required />
            </label>
            <label class="storage-check">
              <input v-model="backupForm.initializeIfMissing" type="checkbox" />
              <span>Initialize repository if missing</span>
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
              <button class="button button--ghost" type="button" @click="backupPanelOpen = false">
                Cancel
              </button>
              <button class="button button--primary" type="submit" :disabled="backupSaving">
                {{ backupSaving ? "Saving…" : "Create policy" }}
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
