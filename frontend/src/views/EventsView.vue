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
  resolveAlert,
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
import UiIcon from "../components/ui/UiIcon.vue"
import { useAuthStore } from "../stores/auth"

type Period = "24h" | "7d" | "30d" | "all"

const router = useRouter()
const auth = useAuthStore()
const { locale, t, te } = useI18n({
  useScope: "global"
})

const cameras = ref<CameraSummary[]>([])
const events = ref<EventItem[]>([])
const alerts = ref<AlertItem[]>([])
const selectedEvent = ref<EventItem | null>(null)
const nextCursor = ref<string | null>(null)
const period = ref<Period>("24h")
const cameraId = ref("")
const category = ref("")
const label = ref("")
const loading = ref(false)
const loadingMore = ref(false)
const alertActionId = ref<string | null>(null)
const error = ref<string | null>(null)
const snapshotFailures = ref(new Set<string>())

const cameraMap = computed(() =>
  new Map(cameras.value.map((camera) => [camera.id, camera]))
)

const severityRank: Record<string, number> = {
  critical: 0,
  warning: 1,
  info: 2
}

const activeAlerts = computed(() =>
  alerts.value
    .filter((item) => item.state !== "RESOLVED")
    .sort((left, right) => {
      const severity =
        (severityRank[left.severity] ?? 9) -
        (severityRank[right.severity] ?? 9)
      if (severity) return severity
      return (
        new Date(right.created_at).getTime() -
        new Date(left.created_at).getTime()
      )
    })
)

const alertsByEvent = computed(() => {
  const grouped = new Map<string, AlertItem[]>()
  for (const alert of alerts.value) {
    const items = grouped.get(alert.event_id) ?? []
    items.push(alert)
    grouped.set(alert.event_id, items)
  }
  return grouped
})

const selectedEventAlerts = computed(() =>
  selectedEvent.value
    ? alertsByEvent.value.get(selectedEvent.value.id) ?? []
    : []
)

const categories = computed(() =>
  Array.from(
    new Set(events.value.map((item) => item.category).filter(Boolean))
  ).sort()
)

const activeFilterCount = computed(() =>
  [
    period.value !== "24h",
    Boolean(cameraId.value),
    Boolean(category.value),
    Boolean(label.value.trim())
  ].filter(Boolean).length
)

function periodRange(): [Date | null, Date | null] {
  if (period.value === "all") return [null, null]

  const now = new Date()
  const hours =
    period.value === "24h"
      ? 24
      : period.value === "7d"
        ? 24 * 7
        : 24 * 30

  return [
    new Date(now.getTime() - hours * 60 * 60 * 1000),
    now
  ]
}

function cameraName(item: EventItem): string {
  if (!item.camera_id) return t("events.system")
  return (
    cameraMap.value.get(item.camera_id)?.name ??
    t("events.unknownCamera")
  )
}

function alertCameraName(item: AlertItem): string {
  if (!item.camera_id) return t("events.system")
  return (
    cameraMap.value.get(item.camera_id)?.name ??
    t("events.unknownCamera")
  )
}

function eventActiveAlert(item: EventItem): AlertItem | null {
  return (
    alertsByEvent.value
      .get(item.id)
      ?.find((alert) => alert.state !== "RESOLVED") ??
    null
  )
}

function eventAlertState(item: EventItem): string {
  const alert = eventActiveAlert(item)
  return alert ? pretty(alert.state) : ""
}

function alertStateClass(item: AlertItem): string {
  if (item.state === "RESOLVED") return "status-pill--muted"
  if (item.severity === "critical") return "status-pill--error"
  if (item.state === "ACKNOWLEDGED") return "status-pill--muted"
  return "status-pill--warning"
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(locale.value, {
    month: "short",
    day: "numeric"
  }).format(new Date(value))
}

function formatTime(value: string): string {
  return new Intl.DateTimeFormat(locale.value, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false
  }).format(new Date(value))
}

function formatDuration(item: EventItem): string | null {
  if (!item.ended_at) return null
  const seconds = Math.max(
    0,
    Math.round(
      (new Date(item.ended_at).getTime() -
        new Date(item.started_at).getTime()) /
        1000
    )
  )
  if (seconds < 60) {
    return locale.value === "zh-CN"
      ? `${seconds} 秒`
      : `${seconds}s`
  }
  const minutes = Math.floor(seconds / 60)
  const remaining = seconds % 60
  if (locale.value === "zh-CN") {
    return remaining
      ? `${minutes} 分 ${remaining} 秒`
      : `${minutes} 分`
  }
  return remaining
    ? `${minutes}m ${remaining}s`
    : `${minutes}m`
}

function confidenceLabel(value: number | null): string | null {
  return value === null ? null : `${Math.round(value * 100)}%`
}

function pretty(value: string): string {
  const normalized = value
    .toLowerCase()
    .replaceAll("-", "_")
    .replaceAll(".", "_")

  for (const prefix of [
    "events.status",
    "events.sourceMap",
    "events.categoryMap"
  ]) {
    const key = `${prefix}.${normalized}`
    if (te(key)) return t(key)
  }

  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (match) =>
      match.toUpperCase()
    )
}

function metadataRows(item: EventItem): Array<[string, string]> {
  const rows: Array<[string, string]> = []
  const metadata = item.metadata ?? {}

  const description = metadata.description
  if (typeof description === "string" && description.trim()) {
    rows.push([
      t("events.metadata.description"),
      description.trim()
    ])
  }

  const plate = metadata.recognized_license_plate
  if (typeof plate === "string" && plate.trim()) {
    rows.push([
      t("events.metadata.plate"),
      plate.trim()
    ])
  }

  const speed = metadata.average_estimated_speed
  if (typeof speed === "number" || typeof speed === "string") {
    rows.push([
      t("events.metadata.estimatedSpeed"),
      String(speed)
    ])
  }

  const zones = metadata.zones
  if (Array.isArray(zones) && zones.length) {
    rows.push([
      t("events.metadata.zones"),
      zones.filter((value) => typeof value === "string").join(", ")
    ])
  }

  return rows
}

async function refresh(): Promise<void> {
  if (!auth.hasPermission("event.view")) return

  const [from, to] = periodRange()
  loading.value = true
  error.value = null

  try {
    const [eventPage, alertPage] = await Promise.all([
      listEvents({
        cameraId: cameraId.value || null,
        from,
        to,
        category: category.value || null,
        label: label.value.trim() || null,
        limit: 48
      }),
      listAlerts({
        cameraId: cameraId.value || null,
        limit: 100
      })
    ])
    events.value = eventPage.items
    nextCursor.value = eventPage.next_cursor
    alerts.value = alertPage.items

    if (
      selectedEvent.value &&
      !events.value.some((item) => item.id === selectedEvent.value?.id)
    ) {
      selectedEvent.value = null
    }
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    loading.value = false
  }
}

async function loadMore(): Promise<void> {
  if (!nextCursor.value || loadingMore.value) return

  const [from, to] = periodRange()
  loadingMore.value = true
  try {
    const page = await listEvents({
      cameraId: cameraId.value || null,
      from,
      to,
      category: category.value || null,
      label: label.value.trim() || null,
      cursor: nextCursor.value,
      limit: 48
    })
    const known = new Set(events.value.map((item) => item.id))
    events.value.push(
      ...page.items.filter((item) => !known.has(item.id))
    )
    nextCursor.value = page.next_cursor
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    loadingMore.value = false
  }
}

function resetFilters(): void {
  period.value = "24h"
  cameraId.value = ""
  category.value = ""
  label.value = ""
  void refresh()
}

function selectEvent(item: EventItem): void {
  selectedEvent.value = item
}

function selectAlertEvent(item: AlertItem): void {
  const event = events.value.find(
    (candidate) => candidate.id === item.event_id
  )
  if (event) {
    selectedEvent.value = event
  }
}

function replaceAlert(updated: AlertItem): void {
  const index = alerts.value.findIndex(
    (item) => item.id === updated.id
  )
  if (index >= 0) {
    alerts.value.splice(index, 1, updated)
  } else {
    alerts.value.unshift(updated)
  }
}

async function acknowledge(item: AlertItem): Promise<void> {
  if (
    item.state !== "OPEN" ||
    !auth.hasPermission("alert.acknowledge") ||
    alertActionId.value
  ) {
    return
  }
  alertActionId.value = item.id
  error.value = null
  try {
    replaceAlert(await acknowledgeAlert(item.id))
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    alertActionId.value = null
  }
}

async function resolve(item: AlertItem): Promise<void> {
  if (
    item.state === "RESOLVED" ||
    !auth.hasPermission("alert.manage") ||
    alertActionId.value
  ) {
    return
  }
  alertActionId.value = item.id
  error.value = null
  try {
    replaceAlert(await resolveAlert(item.id))
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    alertActionId.value = null
  }
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

function viewRecording(item: EventItem): void {
  if (!item.camera_id) return
  void router.push({
    name: "playback",
    query: {
      camera: item.camera_id,
      at: item.started_at
    }
  })
}

async function loadInitial(): Promise<void> {
  error.value = null
  try {
    if (auth.hasPermission("camera.view")) {
      cameras.value = await listCameras({
        includeRetired: true
      })
    }
  } catch (caught) {
    error.value = errorMessage(caught)
  }
  await refresh()
}

function handleRefreshEvent(): void {
  void refresh()
}

onMounted(() => {
  void loadInitial()
  window.addEventListener("zero-nvr:refresh", handleRefreshEvent)
})

onBeforeUnmount(() => {
  window.removeEventListener("zero-nvr:refresh", handleRefreshEvent)
})
</script>

<template>
  <section class="events-workspace">
    <header class="events-header">
      <div class="events-header__copy">
        <strong>{{ t("events.title") }}</strong>
        <span>
          {{ t("events.description") }}
        </span>
      </div>

      <button
        class="button button--ghost"
        type="button"
        :disabled="loading"
        @click="refresh"
      >
        <UiIcon name="refresh" :size="15" />
        {{ t("events.refresh") }}
      </button>
    </header>

    <div class="events-filters">
      <label class="events-filter">
        <span>{{ t("events.period") }}</span>
        <select v-model="period" @change="refresh">
          <option value="24h">{{ t("events.last24Hours") }}</option>
          <option value="7d">{{ t("events.last7Days") }}</option>
          <option value="30d">{{ t("events.last30Days") }}</option>
          <option value="all">{{ t("events.allTime") }}</option>
        </select>
      </label>

      <label class="events-filter">
        <span>{{ t("events.camera") }}</span>
        <select v-model="cameraId" @change="refresh">
          <option value="">{{ t("events.allCameras") }}</option>
          <option
            v-for="camera in cameras"
            :key="camera.id"
            :value="camera.id"
          >
            {{ camera.name }}
          </option>
        </select>
      </label>

      <label class="events-filter">
        <span>{{ t("events.type") }}</span>
        <select v-model="category" @change="refresh">
          <option value="">{{ t("events.allTypes") }}</option>
          <option
            v-for="item in categories"
            :key="item"
            :value="item"
          >
            {{ pretty(item) }}
          </option>
        </select>
      </label>

      <label class="events-filter events-filter--search">
        <span>{{ t("events.label") }}</span>
        <div class="events-filter-search">
          <UiIcon name="search" :size="14" />
          <input
            v-model="label"
            type="search"
            :placeholder="t('events.labelPlaceholder')"
            @keydown.enter="refresh"
          />
        </div>
      </label>

      <button
        v-if="activeFilterCount"
        class="events-clear"
        type="button"
        @click="resetFilters"
      >
        {{ t("events.clearFilters", { count: activeFilterCount }) }}
      </button>
    </div>

    <div v-if="error" class="events-error">
      <UiIcon name="warning" :size="16" />
      <span>{{ error }}</span>
    </div>

    <section
      v-if="activeAlerts.length"
      class="events-alerts"
    >
      <div class="events-alerts__heading">
        <div>
          <strong>{{ t("events.activeAlerts") }}</strong>
          <span>{{ t("events.requireAttention", { count: activeAlerts.length }) }}</span>
        </div>
      </div>

      <div class="events-alerts__list">
        <article
          v-for="alert in activeAlerts.slice(0, 8)"
          :key="alert.id"
          class="events-alert-row"
          :class="`events-alert-row--${alert.severity}`"
        >
          <button
            class="events-alert-row__main"
            type="button"
            @click="selectAlertEvent(alert)"
          >
            <span
              class="events-alert-row__severity"
              :class="`events-alert-row__severity--${alert.severity}`"
            />
            <span class="events-alert-row__copy">
              <strong>{{ alert.title }}</strong>
              <small>
                {{ alertCameraName(alert) }} ·
                {{ formatTime(alert.created_at) }}
              </small>
            </span>
            <span
              class="status-pill"
              :class="alertStateClass(alert)"
            >
              {{ pretty(alert.state) }}
            </span>
          </button>

          <div class="events-alert-row__actions">
            <button
              v-if="
                alert.state === 'OPEN' &&
                auth.hasPermission('alert.acknowledge')
              "
              class="button button--ghost button--compact"
              type="button"
              :disabled="alertActionId === alert.id"
              @click="acknowledge(alert)"
            >
              {{ t("events.acknowledge") }}
            </button>
            <button
              v-if="auth.hasPermission('alert.manage')"
              class="button button--ghost button--compact"
              type="button"
              :disabled="alertActionId === alert.id"
              @click="resolve(alert)"
            >
              {{ t("events.resolve") }}
            </button>
          </div>
        </article>
      </div>
    </section>

    <div class="events-body">
      <div class="events-feed">
        <div v-if="loading && !events.length" class="events-empty">
          <UiIcon name="events" :size="30" />
          <strong>{{ t("events.loadingEvents") }}</strong>
        </div>

        <div
          v-else-if="!events.length"
          class="events-empty"
        >
          <UiIcon name="events" :size="30" />
          <strong>{{ t("events.noEvents") }}</strong>
          <span>{{ t("events.noEventsHint") }}</span>
        </div>

        <div v-else class="event-card-grid">
          <button
            v-for="item in events"
            :key="item.id"
            class="event-card"
            :class="{
              'event-card--selected':
                selectedEvent?.id === item.id
            }"
            type="button"
            @click="selectEvent(item)"
          >
            <div class="event-card__preview">
              <img
                v-if="canShowSnapshot(item)"
                :src="eventSnapshotUrl(item.id)"
                :alt="t('events.eventAlt', { name: item.label || pretty(item.category) })"
                loading="lazy"
                @error="snapshotFailed(item.id)"
              />
              <div v-else class="event-card__placeholder">
                <UiIcon name="events" :size="24" />
              </div>

              <span class="event-card__time">
                {{ formatTime(item.started_at) }}
              </span>

              <span
                v-if="confidenceLabel(item.confidence)"
                class="event-card__confidence"
              >
                {{ confidenceLabel(item.confidence) }}
              </span>

              <span
                v-if="eventActiveAlert(item)"
                class="event-card__alert"
                :class="`event-card__alert--${eventActiveAlert(item)?.severity}`"
              >
                {{ eventAlertState(item) }}
              </span>
            </div>

            <div class="event-card__content">
              <div class="event-card__title">
                <strong>{{ item.label || pretty(item.category) }}</strong>
                <span>{{ formatDate(item.started_at) }}</span>
              </div>

              <div class="event-card__meta">
                <span>
                  <UiIcon name="cameras" :size="12" />
                  {{ cameraName(item) }}
                </span>
                <span v-if="item.zone">
                  <UiIcon name="zone" :size="12" />
                  {{ item.zone }}
                </span>
              </div>
            </div>
          </button>
        </div>

        <button
          v-if="nextCursor"
          class="events-load-more"
          type="button"
          :disabled="loadingMore"
          @click="loadMore"
        >
          {{ loadingMore ? t("events.loading") : t("events.loadMore") }}
        </button>
      </div>

      <aside
        v-if="selectedEvent"
        class="event-detail"
      >
        <header class="event-detail__header">
          <div>
            <strong>
              {{ selectedEvent.label || pretty(selectedEvent.category) }}
            </strong>
            <span>{{ cameraName(selectedEvent) }}</span>
          </div>
          <button
            class="icon-button"
            type="button"
            :aria-label="t('events.closeDetails')"
            :title="t('events.close')"
            @click="selectedEvent = null"
          >
            <UiIcon name="close" :size="16" />
          </button>
        </header>

        <div class="event-detail__preview">
          <img
            v-if="canShowSnapshot(selectedEvent)"
            :src="eventSnapshotUrl(selectedEvent.id)"
            :alt="t('events.snapshotAlt')"
            @error="snapshotFailed(selectedEvent.id)"
          />
          <div v-else class="event-detail__placeholder">
            <UiIcon name="events" :size="30" />
          </div>
        </div>

        <div class="event-detail__section">
          <div class="event-detail__time">
            <strong>{{ formatDate(selectedEvent.started_at) }}</strong>
            <span>{{ formatTime(selectedEvent.started_at) }}</span>
          </div>

          <dl class="event-detail__facts">
            <div>
              <dt>{{ t("events.type") }}</dt>
              <dd>{{ pretty(selectedEvent.category) }}</dd>
            </div>
            <div>
              <dt>{{ t("events.source") }}</dt>
              <dd>{{ pretty(selectedEvent.source) }}</dd>
            </div>
            <div v-if="selectedEvent.zone">
              <dt>{{ t("events.zone") }}</dt>
              <dd>{{ selectedEvent.zone }}</dd>
            </div>
            <div v-if="confidenceLabel(selectedEvent.confidence)">
              <dt>{{ t("events.confidence") }}</dt>
              <dd>{{ confidenceLabel(selectedEvent.confidence) }}</dd>
            </div>
            <div v-if="formatDuration(selectedEvent)">
              <dt>{{ t("events.duration") }}</dt>
              <dd>{{ formatDuration(selectedEvent) }}</dd>
            </div>
            <div v-if="selectedEvent.severity">
              <dt>{{ t("events.severity") }}</dt>
              <dd>{{ pretty(selectedEvent.severity) }}</dd>
            </div>
          </dl>
        </div>

        <div
          v-if="selectedEventAlerts.length"
          class="event-detail__section event-detail__alerts"
        >
          <h3>{{ t("events.alerts") }}</h3>
          <article
            v-for="alert in selectedEventAlerts"
            :key="alert.id"
            class="event-detail-alert"
          >
            <div>
              <strong>{{ alert.title }}</strong>
              <span>{{ alert.message || pretty(alert.severity) }}</span>
            </div>
            <span
              class="status-pill"
              :class="alertStateClass(alert)"
            >
              {{ pretty(alert.state) }}
            </span>
            <div class="event-detail-alert__actions">
              <button
                v-if="
                  alert.state === 'OPEN' &&
                  auth.hasPermission('alert.acknowledge')
                "
                class="button button--ghost button--compact"
                type="button"
                :disabled="alertActionId === alert.id"
                @click="acknowledge(alert)"
              >
                {{ t("events.acknowledge") }}
              </button>
              <button
                v-if="
                  alert.state !== 'RESOLVED' &&
                  auth.hasPermission('alert.manage')
                "
                class="button button--ghost button--compact"
                type="button"
                :disabled="alertActionId === alert.id"
                @click="resolve(alert)"
              >
                {{ t("events.resolve") }}
              </button>
            </div>
          </article>
        </div>

        <div
          v-if="metadataRows(selectedEvent).length"
          class="event-detail__section"
        >
          <h3>{{ t("events.details") }}</h3>
          <dl class="event-detail__facts">
            <div
              v-for="[key, value] in metadataRows(selectedEvent)"
              :key="key"
            >
              <dt>{{ key }}</dt>
              <dd>{{ value }}</dd>
            </div>
          </dl>
        </div>

        <div class="event-detail__actions">
          <button
            v-if="selectedEvent.camera_id"
            class="button button--primary"
            type="button"
            @click="viewRecording(selectedEvent)"
          >
            <UiIcon name="playback" :size="15" />
            {{ t("events.viewRecording") }}
          </button>
        </div>
      </aside>
    </div>
  </section>
</template>


<style scoped>
.events-alerts {
  display: grid;
  gap: 7px;
  margin: 0 12px 10px;
  padding: 8px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--surface-raised);
}

.events-alerts__heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.events-alerts__heading strong,
.events-alerts__heading span {
  display: block;
}

.events-alerts__heading strong {
  font-size: 10px;
}

.events-alerts__heading span {
  margin-top: 1px;
  color: var(--text-muted);
  font-size: 8px;
}

.events-alerts__list {
  display: grid;
  gap: 2px;
}

.events-alert-row {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  border-radius: var(--radius-sm);
}

.events-alert-row:hover {
  background: var(--surface-hover);
}

.events-alert-row__main {
  display: flex;
  flex: 1;
  align-items: center;
  gap: 7px;
  min-width: 0;
  padding: 6px;
  border: 0;
  background: transparent;
  color: var(--text-primary);
  text-align: left;
  cursor: pointer;
}

.events-alert-row__severity {
  width: 3px;
  height: 28px;
  flex: 0 0 auto;
  border-radius: 99px;
  background: var(--text-muted);
}

.events-alert-row__severity--critical {
  background: var(--danger);
}

.events-alert-row__severity--warning {
  background: var(--warning);
}

.events-alert-row__severity--info {
  background: var(--accent);
}

.events-alert-row__copy {
  min-width: 0;
  flex: 1;
}

.events-alert-row__copy strong,
.events-alert-row__copy small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.events-alert-row__copy strong {
  font-size: 9px;
  font-weight: 600;
}

.events-alert-row__copy small {
  margin-top: 2px;
  color: var(--text-muted);
  font-size: 8px;
}

.events-alert-row__actions {
  display: flex;
  gap: 4px;
  padding-right: 5px;
}

.event-card__alert {
  position: absolute;
  top: 7px;
  left: 7px;
  padding: 3px 5px;
  border-radius: 999px;
  background: rgba(30, 34, 40, 0.86);
  color: white;
  font-size: 7px;
  font-weight: 600;
  letter-spacing: 0.04em;
}

.event-card__alert--critical {
  background: color-mix(in srgb, var(--danger) 85%, transparent);
}

.event-card__alert--warning {
  background: color-mix(in srgb, var(--warning) 85%, transparent);
}

.event-detail__alerts {
  display: grid;
  gap: 6px;
}

.event-detail-alert {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 7px;
  padding: 7px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: var(--surface-base);
}

.event-detail-alert > div:first-child {
  min-width: 0;
}

.event-detail-alert strong,
.event-detail-alert span {
  display: block;
}

.event-detail-alert strong {
  font-size: 9px;
}

.event-detail-alert > div:first-child > span {
  margin-top: 2px;
  color: var(--text-muted);
  font-size: 8px;
  line-height: 1.4;
}

.event-detail-alert__actions {
  grid-column: 1 / -1;
  display: flex;
  gap: 5px;
}

@media (max-width: 900px) {
  .events-alert-row {
    align-items: flex-start;
  }

  .events-alert-row__actions {
    flex-direction: column;
  }
}
</style>
