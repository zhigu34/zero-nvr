<script setup lang="ts">
import {
  computed,
  onBeforeUnmount,
  onMounted,
  ref
} from "vue"
import { useRouter } from "vue-router"
import { useI18n } from "vue-i18n"

import {
  acknowledgeAlert,
  listAlerts,
  type AlertItem
} from "../api/alerts"
import {
  listCameras,
  type CameraSummary
} from "../api/cameras"
import { errorMessage } from "../api/client"
import {
  eventSnapshotUrl,
  listEvents,
  type EventItem
} from "../api/events"
import {
  listStorageTargets,
  type StorageTarget
} from "../api/storage"
import {
  getSystemHealth,
  listBackups,
  type BackupSet,
  type SystemHealth
} from "../api/system"
import UiIcon from "../components/ui/UiIcon.vue"
import { useAuthStore } from "../stores/auth"

const router = useRouter()
const auth = useAuthStore()
const { locale, t, te } = useI18n({
  useScope: "global"
})

const health = ref<SystemHealth | null>(null)
const cameras = ref<CameraSummary[]>([])
const events = ref<EventItem[]>([])
const alerts = ref<AlertItem[]>([])
const storageTargets = ref<StorageTarget[]>([])
const backups = ref<BackupSet[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const acknowledgingId = ref<string | null>(null)
const snapshotFailures = ref(new Set<string>())

const cameraMap = computed(() =>
  new Map(cameras.value.map((camera) => [camera.id, camera]))
)

const enabledCameraCount = computed(() =>
  cameras.value.filter((camera) => camera.enabled).length
)

const disabledCameraCount = computed(() =>
  Math.max(0, cameras.value.length - enabledCameraCount.value)
)

const criticalAlertCount = computed(() =>
  alerts.value.filter(
    (item) =>
      item.state === "OPEN" &&
      item.severity.toLowerCase() === "critical"
  ).length
)

const openAlertCount = computed(() =>
  alerts.value.filter((item) => item.state === "OPEN").length
)

const recentEvents = computed(() => events.value.slice(0, 6))
const recentAlerts = computed(() =>
  alerts.value
    .filter((item) => item.state !== "RESOLVED")
    .slice(0, 5)
)

const healthComponents = computed(() =>
  Object.entries(health.value?.components ?? {})
)

const localTargetCount = computed(() =>
  storageTargets.value.filter(
    (item) => item.type === "local" && item.enabled
  ).length
)

const archiveTargetCount = computed(() =>
  storageTargets.value.filter(
    (item) => item.type === "rclone" && item.enabled
  ).length
)

const latestBackup = computed(() => backups.value[0] ?? null)

async function safe<T>(
  task: Promise<T>,
  apply: (value: T) => void
): Promise<void> {
  try {
    apply(await task)
  } catch (caught) {
    if (!error.value) error.value = errorMessage(caught)
  }
}

async function refresh(): Promise<void> {
  loading.value = true
  error.value = null
  const tasks: Promise<void>[] = []

  if (auth.hasPermission("camera.view")) {
    tasks.push(
      safe(listCameras(), (value) => {
        cameras.value = value
      })
    )
  }

  if (auth.hasPermission("system.view")) {
    tasks.push(
      safe(getSystemHealth(), (value) => {
        health.value = value
      }),
      safe(listBackups(), (value) => {
        backups.value = value.items
      })
    )
  }

  if (auth.hasPermission("event.view")) {
    const now = new Date()
    const from = new Date(now.getTime() - 24 * 60 * 60 * 1000)
    tasks.push(
      safe(
        listEvents({
          from,
          to: now,
          limit: 12
        }),
        (value) => {
          events.value = value.items
        }
      ),
      safe(
        listAlerts({ limit: 20 }),
        (value) => {
          alerts.value = value.items
        }
      )
    )
  }

  if (auth.hasPermission("storage.manage")) {
    tasks.push(
      safe(listStorageTargets(), (value) => {
        storageTargets.value = value
      })
    )
  }

  await Promise.all(tasks)
  loading.value = false
}

function cameraName(cameraId: string | null): string {
  if (!cameraId) return t("dashboard.systemSource")
  return (
    cameraMap.value.get(cameraId)?.name ??
    t("dashboard.unknownCamera")
  )
}

function formatTime(value: string | null): string {
  if (!value) return "—"
  return new Intl.DateTimeFormat(locale.value, {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  }).format(new Date(value))
}

function formatDateTime(value: string | null): string {
  if (!value) return t("dashboard.never")
  return new Intl.DateTimeFormat(locale.value, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  }).format(new Date(value))
}

function pretty(value: string): string {
  const normalized = value
    .toLowerCase()
    .replaceAll(".", "_")
    .replaceAll("-", "_")
  const statusKey = `dashboard.status.${normalized}`
  if (te(statusKey)) return t(statusKey)

  return value
    .replaceAll("_", " ")
    .replaceAll(".", " · ")
    .replace(/\b\w/g, (match) => match.toUpperCase())
}

function snapshotFailed(eventId: string): void {
  const next = new Set(snapshotFailures.value)
  next.add(eventId)
  snapshotFailures.value = next
}

function canShowSnapshot(item: EventItem): boolean {
  return Boolean(
    item.snapshot_ref && !snapshotFailures.value.has(item.id)
  )
}

function openEvent(item: EventItem): void {
  if (!item.camera_id) {
    void router.push("/events")
    return
  }
  void router.push({
    name: "playback",
    query: {
      camera: item.camera_id,
      at: item.started_at
    }
  })
}

async function acknowledge(item: AlertItem): Promise<void> {
  acknowledgingId.value = item.id
  try {
    const updated = await acknowledgeAlert(item.id)
    alerts.value = alerts.value.map((current) =>
      current.id === updated.id ? updated : current
    )
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    acknowledgingId.value = null
  }
}

function severityClass(value: string): string {
  const normalized = value.toLowerCase()
  if (normalized === "critical") return "dashboard-alert--critical"
  if (normalized === "warning") return "dashboard-alert--warning"
  return "dashboard-alert--info"
}

function statusClass(value: string): string {
  const normalized = value.toUpperCase()
  if (normalized === "OK" || normalized === "COMPLETED") {
    return "status-pill--ok"
  }
  if (normalized === "ERROR" || normalized === "FAILED") {
    return "status-pill--error"
  }
  return "status-pill--muted"
}

function handleRefresh(): void {
  void refresh()
}

onMounted(() => {
  void refresh()
  window.addEventListener("zero-nvr:refresh", handleRefresh)
})

onBeforeUnmount(() => {
  window.removeEventListener("zero-nvr:refresh", handleRefresh)
})
</script>

<template>
  <section class="dashboard-workspace">
    <header class="dashboard-header">
      <div>
        <strong>{{ t("dashboard.overview") }}</strong>
        <span>{{ t("dashboard.description") }}</span>
      </div>
      <button
        class="button button--ghost"
        type="button"
        :disabled="loading"
        @click="refresh"
      >
        <UiIcon name="refresh" :size="14" />
        {{ loading ? t("dashboard.refreshing") : t("dashboard.refresh") }}
      </button>
    </header>

    <div v-if="error" class="events-error">
      <UiIcon name="warning" :size="16" />
      <span>{{ error }}</span>
    </div>

    <div class="dashboard-metrics">
      <RouterLink to="/system" class="dashboard-metric">
        <div class="dashboard-metric__icon">
          <UiIcon name="activity" :size="18" />
        </div>
        <div>
          <span>{{ t("dashboard.systemHealth") }}</span>
          <strong>{{ health?.status || "—" }}</strong>
          <small>
            {{ t("dashboard.monitoredComponents", { count: healthComponents.length }) }}
          </small>
        </div>
      </RouterLink>

      <RouterLink to="/cameras" class="dashboard-metric">
        <div class="dashboard-metric__icon">
          <UiIcon name="cameras" :size="18" />
        </div>
        <div>
          <span>{{ t("dashboard.cameras") }}</span>
          <strong>{{ enabledCameraCount }}/{{ cameras.length }}</strong>
          <small>
            {{
              disabledCameraCount
                ? t("dashboard.disabledCount", { count: disabledCameraCount })
                : t("dashboard.allEnabled")
            }}
          </small>
        </div>
      </RouterLink>

      <RouterLink to="/events" class="dashboard-metric">
        <div class="dashboard-metric__icon">
          <UiIcon name="events" :size="18" />
        </div>
        <div>
          <span>{{ t("dashboard.events24h") }}</span>
          <strong>{{ events.length }}</strong>
          <small>{{ t("dashboard.recentActivityLoaded") }}</small>
        </div>
      </RouterLink>

      <RouterLink to="/events" class="dashboard-metric">
        <div
          class="dashboard-metric__icon"
          :class="{ 'dashboard-metric__icon--danger': criticalAlertCount }"
        >
          <UiIcon name="bell" :size="18" />
        </div>
        <div>
          <span>{{ t("dashboard.openAlerts") }}</span>
          <strong>{{ openAlertCount }}</strong>
          <small>
            {{
              criticalAlertCount
                ? t("dashboard.criticalCount", { count: criticalAlertCount })
                : t("dashboard.noCriticalAlerts")
            }}
          </small>
        </div>
      </RouterLink>
    </div>

    <div class="dashboard-quick-actions">
      <RouterLink to="/live">
        <UiIcon name="live" :size="15" />
        {{ t("dashboard.liveView") }}
      </RouterLink>
      <RouterLink to="/playback">
        <UiIcon name="playback" :size="15" />
        {{ t("dashboard.playback") }}
      </RouterLink>
      <RouterLink to="/events">
        <UiIcon name="events" :size="15" />
        {{ t("dashboard.events") }}
      </RouterLink>
      <RouterLink to="/cameras">
        <UiIcon name="cameras" :size="15" />
        {{ t("dashboard.cameras") }}
      </RouterLink>
    </div>

    <div class="dashboard-grid">
      <section class="dashboard-panel dashboard-panel--events">
        <header>
          <div>
            <strong>{{ t("dashboard.recentActivity") }}</strong>
            <span>{{ t("dashboard.recentActivityDescription") }}</span>
          </div>
          <RouterLink to="/events">{{ t("dashboard.viewAll") }}</RouterLink>
        </header>

        <div v-if="!recentEvents.length" class="dashboard-empty">
          <UiIcon name="events" :size="22" />
          <span>{{ t("dashboard.noRecentEvents") }}</span>
        </div>

        <div v-else class="dashboard-event-strip">
          <button
            v-for="item in recentEvents"
            :key="item.id"
            type="button"
            class="dashboard-event"
            @click="openEvent(item)"
          >
            <div class="dashboard-event__preview">
              <img
                v-if="canShowSnapshot(item)"
                :src="eventSnapshotUrl(item.id)"
                alt=""
                loading="lazy"
                @error="snapshotFailed(item.id)"
              />
              <UiIcon v-else name="events" :size="20" />
              <span>{{ formatTime(item.started_at) }}</span>
            </div>
            <div>
              <strong>{{ item.label || pretty(item.category) }}</strong>
              <small>{{ cameraName(item.camera_id) }}</small>
            </div>
          </button>
        </div>
      </section>

      <section class="dashboard-panel">
        <header>
          <div>
            <strong>{{ t("dashboard.alerts") }}</strong>
            <span>{{ t("dashboard.alertsDescription") }}</span>
          </div>
        </header>

        <div v-if="!recentAlerts.length" class="dashboard-empty">
          <UiIcon name="check" :size="22" />
          <span>{{ t("dashboard.noActiveAlerts") }}</span>
        </div>

        <div v-else class="dashboard-alert-list">
          <article
            v-for="item in recentAlerts"
            :key="item.id"
            class="dashboard-alert"
            :class="severityClass(item.severity)"
          >
            <span class="dashboard-alert__marker" />
            <div>
              <strong>{{ item.title }}</strong>
              <small>
                {{ cameraName(item.camera_id) }} ·
                {{ formatDateTime(item.created_at) }}
              </small>
            </div>
            <button
              v-if="
                item.state === 'OPEN' &&
                auth.hasPermission('alert.acknowledge')
              "
              class="button button--ghost button--compact"
              type="button"
              :disabled="acknowledgingId === item.id"
              @click="acknowledge(item)"
            >
              {{ acknowledgingId === item.id ? "…" : t("dashboard.acknowledge") }}
            </button>
            <span
              v-else
              class="status-pill"
              :class="statusClass(item.state)"
            >
              {{ pretty(item.state) }}
            </span>
          </article>
        </div>
      </section>

      <section class="dashboard-panel">
        <header>
          <div>
            <strong>{{ t("dashboard.cameraInventory") }}</strong>
            <span>{{ t("dashboard.cameraInventoryDescription") }}</span>
          </div>
          <RouterLink to="/cameras">{{ t("dashboard.manage") }}</RouterLink>
        </header>

        <div v-if="!cameras.length" class="dashboard-empty">
          <UiIcon name="cameras" :size="22" />
          <span>{{ t("dashboard.noCameras") }}</span>
        </div>

        <div v-else class="dashboard-camera-list">
          <article
            v-for="camera in cameras.slice(0, 7)"
            :key="camera.id"
          >
            <span
              class="live-camera-row__status"
              :class="{
                'live-camera-row__status--enabled': camera.enabled
              }"
            />
            <div>
              <strong>{{ camera.name }}</strong>
              <small>{{ camera.location || t("dashboard.noLocation") }}</small>
            </div>
            <span>{{ camera.adapter_type || t("dashboard.manual") }}</span>
          </article>
        </div>
      </section>

      <section class="dashboard-panel">
        <header>
          <div>
            <strong>{{ t("dashboard.coreServices") }}</strong>
            <span>{{ t("dashboard.coreServicesDescription") }}</span>
          </div>
          <RouterLink to="/system">{{ t("dashboard.system") }}</RouterLink>
        </header>

        <div class="dashboard-health-list">
          <article
            v-for="[name, component] in healthComponents.slice(0, 7)"
            :key="name"
          >
            <span
              class="status-dot"
              :class="`status-dot--${component.status.toLowerCase()}`"
            />
            <strong>{{ pretty(name) }}</strong>
            <span>{{ pretty(component.status) }}</span>
          </article>
        </div>
      </section>

      <section
        v-if="
          auth.hasPermission('storage.manage') ||
          auth.hasPermission('system.view')
        "
        class="dashboard-panel dashboard-panel--wide"
      >
        <header>
          <div>
            <strong>{{ t("dashboard.storageBackup") }}</strong>
            <span>{{ t("dashboard.storageBackupDescription") }}</span>
          </div>
          <RouterLink to="/storage">{{ t("dashboard.storage") }}</RouterLink>
        </header>

        <div class="dashboard-storage-row">
          <div>
            <UiIcon name="drive" :size="17" />
            <span>{{ t("dashboard.localRecording") }}</span>
            <strong>{{ localTargetCount }}</strong>
          </div>
          <div>
            <UiIcon name="cloud" :size="17" />
            <span>{{ t("dashboard.remoteArchive") }}</span>
            <strong>{{ archiveTargetCount }}</strong>
          </div>
          <div>
            <UiIcon name="backup" :size="17" />
            <span>{{ t("dashboard.latestBackup") }}</span>
            <strong>
              {{
                latestBackup
                  ? pretty(latestBackup.state)
                  : t("dashboard.never")
              }}
            </strong>
            <small>
              {{
                latestBackup
                  ? formatDateTime(latestBackup.started_at)
                  : t("dashboard.noBackupSet")
              }}
            </small>
          </div>
        </div>
      </section>
    </div>
  </section>
</template>

<style scoped>
.dashboard-workspace {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.dashboard-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}

.dashboard-header > div > strong,
.dashboard-header > div > span {
  display: block;
}

.dashboard-header > div > strong {
  font-size: 17px;
  letter-spacing: -0.02em;
}

.dashboard-header > div > span {
  margin-top: 3px;
  color: var(--text-muted);
  font-size: 10px;
}

.dashboard-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.dashboard-metric {
  display: grid;
  min-height: 86px;
  grid-template-columns: 38px minmax(0, 1fr);
  align-items: center;
  gap: 10px;
  padding: 11px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--surface-raised);
  color: inherit;
  text-decoration: none;
  transition: border-color 120ms ease, transform 120ms ease;
}

.dashboard-metric:hover {
  border-color: var(--border-strong);
  transform: translateY(-1px);
}

.dashboard-metric__icon {
  display: grid;
  width: 36px;
  height: 36px;
  border-radius: var(--radius-sm);
  background: var(--surface-subtle);
  color: var(--text-secondary);
  place-items: center;
}

.dashboard-metric__icon--danger {
  background: var(--danger-soft);
  color: var(--danger);
}

.dashboard-metric span,
.dashboard-metric strong,
.dashboard-metric small {
  display: block;
}

.dashboard-metric span {
  color: var(--text-muted);
  font-size: 8px;
  font-weight: 650;
  letter-spacing: 0.03em;
  text-transform: uppercase;
}

.dashboard-metric strong {
  margin-top: 3px;
  font-size: 18px;
}

.dashboard-metric small {
  margin-top: 2px;
  color: var(--text-muted);
  font-size: 8px;
}

.dashboard-quick-actions {
  display: flex;
  gap: 5px;
}

.dashboard-quick-actions a {
  display: inline-flex;
  min-height: 32px;
  align-items: center;
  gap: 6px;
  padding: 0 9px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: var(--surface-raised);
  color: var(--text-secondary);
  font-size: 9px;
  font-weight: 600;
  text-decoration: none;
}

.dashboard-quick-actions a:hover {
  background: var(--surface-hover);
  color: var(--text-primary);
}

.dashboard-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 9px;
}

.dashboard-panel {
  min-width: 0;
  overflow: hidden;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--surface-raised);
}

.dashboard-panel--events,
.dashboard-panel--wide {
  grid-column: 1 / -1;
}

.dashboard-panel > header {
  display: flex;
  min-height: 48px;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 0 11px;
  border-bottom: 1px solid var(--border-subtle);
}

.dashboard-panel > header strong,
.dashboard-panel > header span {
  display: block;
}

.dashboard-panel > header strong {
  font-size: 10px;
}

.dashboard-panel > header span {
  margin-top: 2px;
  color: var(--text-muted);
  font-size: 8px;
}

.dashboard-panel > header a {
  color: var(--accent);
  font-size: 8px;
  font-weight: 600;
  text-decoration: none;
}

.dashboard-event-strip {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 1px;
  background: var(--border-subtle);
}

.dashboard-event {
  min-width: 0;
  padding: 0;
  border: 0;
  background: var(--surface-raised);
  color: var(--text-primary);
  cursor: pointer;
  text-align: left;
}

.dashboard-event__preview {
  position: relative;
  display: grid;
  aspect-ratio: 16 / 9;
  overflow: hidden;
  background: #101216;
  color: #5c646e;
  place-items: center;
}

.dashboard-event__preview img {
  width: 100%;
  height: 100%;
  display: block;
  object-fit: cover;
}

.dashboard-event__preview > span {
  position: absolute;
  right: 5px;
  bottom: 5px;
  padding: 2px 4px;
  border-radius: 3px;
  background: rgba(0, 0, 0, 0.68);
  color: #fff;
  font-size: 7px;
}

.dashboard-event > div:last-child {
  padding: 7px 8px 8px;
}

.dashboard-event strong,
.dashboard-event small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dashboard-event strong {
  font-size: 9px;
}

.dashboard-event small {
  margin-top: 2px;
  color: var(--text-muted);
  font-size: 7px;
}

.dashboard-alert-list,
.dashboard-camera-list,
.dashboard-health-list {
  display: grid;
}

.dashboard-alert,
.dashboard-camera-list article,
.dashboard-health-list article {
  min-height: 45px;
  border-bottom: 1px solid var(--border-subtle);
}

.dashboard-alert:last-child,
.dashboard-camera-list article:last-child,
.dashboard-health-list article:last-child {
  border-bottom: 0;
}

.dashboard-alert {
  display: grid;
  grid-template-columns: 4px minmax(0, 1fr) auto;
  align-items: center;
  gap: 9px;
  padding: 6px 9px 6px 0;
}

.dashboard-alert__marker {
  align-self: stretch;
  background: var(--text-muted);
}

.dashboard-alert--critical .dashboard-alert__marker {
  background: var(--danger);
}

.dashboard-alert--warning .dashboard-alert__marker {
  background: #d49a45;
}

.dashboard-alert--info .dashboard-alert__marker {
  background: var(--accent);
}

.dashboard-alert strong,
.dashboard-alert small {
  display: block;
}

.dashboard-alert strong {
  font-size: 9px;
}

.dashboard-alert small {
  margin-top: 2px;
  color: var(--text-muted);
  font-size: 7px;
}

.dashboard-camera-list article {
  display: grid;
  grid-template-columns: 8px minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  padding: 0 10px;
}

.dashboard-camera-list strong,
.dashboard-camera-list small {
  display: block;
}

.dashboard-camera-list strong {
  font-size: 9px;
}

.dashboard-camera-list small {
  margin-top: 1px;
  color: var(--text-muted);
  font-size: 7px;
}

.dashboard-camera-list article > span:last-child {
  color: var(--text-muted);
  font-size: 7px;
}

.dashboard-health-list article {
  display: grid;
  grid-template-columns: 8px minmax(0, 1fr) auto;
  align-items: center;
  gap: 7px;
  padding: 0 10px;
}

.dashboard-health-list strong {
  font-size: 9px;
}

.dashboard-health-list article > span:last-child {
  color: var(--text-muted);
  font-size: 7px;
}

.dashboard-storage-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.dashboard-storage-row > div {
  min-height: 88px;
  padding: 12px;
  border-right: 1px solid var(--border-subtle);
}

.dashboard-storage-row > div:last-child {
  border-right: 0;
}

.dashboard-storage-row .ui-icon {
  margin-bottom: 7px;
  color: var(--text-muted);
}

.dashboard-storage-row span,
.dashboard-storage-row strong,
.dashboard-storage-row small {
  display: block;
}

.dashboard-storage-row span {
  color: var(--text-muted);
  font-size: 8px;
}

.dashboard-storage-row strong {
  margin-top: 3px;
  font-size: 14px;
}

.dashboard-storage-row small {
  margin-top: 2px;
  color: var(--text-muted);
  font-size: 7px;
}

.dashboard-empty {
  display: flex;
  min-height: 110px;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: 5px;
  color: var(--text-muted);
  font-size: 8px;
}

@media (max-width: 980px) {
  .dashboard-metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .dashboard-event-strip {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 680px) {
  .dashboard-grid,
  .dashboard-metrics {
    grid-template-columns: 1fr;
  }

  .dashboard-event-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .dashboard-storage-row {
    grid-template-columns: 1fr;
  }

  .dashboard-storage-row > div {
    border-right: 0;
    border-bottom: 1px solid var(--border-subtle);
  }

  .dashboard-storage-row > div:last-child {
    border-bottom: 0;
  }

  .dashboard-quick-actions {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
