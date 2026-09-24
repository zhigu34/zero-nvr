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
import { getEvent } from "../api/events"
import {
  listNotificationDeliveries,
  type NotificationDelivery
} from "../api/system"
import UiIcon from "../components/ui/UiIcon.vue"
import { useAuthStore } from "../stores/auth"

type AlertMode = "active" | "recent"
type SeverityFilter = "" | "info" | "warning" | "critical"

const router = useRouter()
const auth = useAuthStore()
const { locale, t } = useI18n({ useScope: "global" })

const alerts = ref<AlertItem[]>([])
const cameras = ref<CameraSummary[]>([])
const deliveries = ref<NotificationDelivery[]>([])
const mode = ref<AlertMode>("active")
const cameraId = ref("")
const severity = ref<SeverityFilter>("")
const search = ref("")
const loading = ref(false)
const acknowledgingId = ref<string | null>(null)
const playbackId = ref<string | null>(null)
const selectedId = ref<string | null>(null)
const error = ref<string | null>(null)
const notice = ref<string | null>(null)

const selectedAlert = computed(() =>
  alerts.value.find((item) => item.id === selectedId.value) ?? null
)

const visibleAlerts = computed(() => {
  const needle = search.value.trim().toLowerCase()
  return alerts.value.filter((item) => {
    if (mode.value === "active" && item.state === "RESOLVED") {
      return false
    }
    if (!needle) return true
    return [
      item.title,
      item.message,
      item.severity,
      item.state,
      cameraName(item.camera_id)
    ]
      .filter(Boolean)
      .some((value) =>
        String(value).toLowerCase().includes(needle)
      )
  })
})

const openCount = computed(() =>
  alerts.value.filter((item) => item.state === "OPEN").length
)
const acknowledgedCount = computed(() =>
  alerts.value.filter((item) => item.state === "ACKNOWLEDGED").length
)
const resolvedCount = computed(() =>
  alerts.value.filter((item) => item.state === "RESOLVED").length
)

const deliveriesByAlert = computed(() => {
  const result = new Map<string, NotificationDelivery[]>()
  for (const delivery of deliveries.value) {
    if (!delivery.alert_id) continue
    const items = result.get(delivery.alert_id) ?? []
    items.push(delivery)
    result.set(delivery.alert_id, items)
  }
  return result
})

function cameraName(id: string | null): string {
  if (!id) return t("alerts.system")
  return cameras.value.find((item) => item.id === id)?.name ?? t("alerts.cameraFallback")
}

function formatTimestamp(value: string | null): string {
  if (!value) return "—"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return "—"
  return new Intl.DateTimeFormat(locale.value, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false
  }).format(date)
}

function stateLabel(state: AlertItem["state"]): string {
  if (state === "ACKNOWLEDGED") return t("alerts.acknowledged")
  if (state === "RESOLVED") return t("alerts.resolved")
  return t("alerts.open")
}

function severityLabel(value: string): string {
  const normalized = value.toLowerCase()
  if (normalized === "critical") return t("alerts.critical")
  if (normalized === "warning") return t("alerts.warning")
  if (normalized === "info") return t("alerts.info")
  return value
}

function deliveryStateLabel(value: NotificationDelivery["state"]): string {
  if (value === "SENT") return t("alerts.deliverySent")
  if (value === "FAILED") return t("alerts.deliveryFailed")
  if (value === "SKIPPED") return t("alerts.deliverySkipped")
  if (value === "PENDING") return t("alerts.deliveryPending")
  return value
}

function stateClass(state: AlertItem["state"]): string {
  if (state === "RESOLVED") return "status-pill--ok"
  if (state === "ACKNOWLEDGED") return "status-pill--muted"
  return "status-pill--warning"
}

function deliveryClass(state: NotificationDelivery["state"]): string {
  if (state === "SENT") return "status-pill--ok"
  if (state === "FAILED") return "status-pill--danger"
  if (state === "SKIPPED") return "status-pill--muted"
  return "status-pill--warning"
}

function deliverySummary(alertId: string): string {
  if (!auth.hasPermission("notification.view")) {
    return t("alerts.deliveryRestricted")
  }
  const items = deliveriesByAlert.value.get(alertId) ?? []
  if (!items.length) return t("alerts.noNotificationDelivery")
  return Array.from(
    new Set(items.map((item) => deliveryStateLabel(item.state)))
  ).join(" · ")
}

function selectAlert(item: AlertItem): void {
  selectedId.value = item.id
}

async function refresh(): Promise<void> {
  if (!auth.hasPermission("alert.view")) return

  loading.value = true
  error.value = null
  notice.value = null
  try {
    const alertPage = await listAlerts({
      cameraId: cameraId.value || null,
      severity: severity.value || null,
      limit: 100
    })
    alerts.value = alertPage.items

    if (
      selectedId.value &&
      !alerts.value.some((item) => item.id === selectedId.value)
    ) {
      selectedId.value = null
    }

    cameras.value = auth.hasPermission("camera.view")
      ? await listCameras({ includeRetired: true }).catch(() => [])
      : []

    deliveries.value = auth.hasPermission("notification.view")
      ? await listNotificationDeliveries({ limit: 500 }).catch(() => [])
      : []
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    loading.value = false
  }
}

async function acknowledge(item: AlertItem): Promise<void> {
  if (
    item.state !== "OPEN" ||
    !auth.hasPermission("alert.acknowledge")
  ) {
    return
  }

  acknowledgingId.value = item.id
  error.value = null
  notice.value = null
  try {
    const updated = await acknowledgeAlert(item.id)
    const index = alerts.value.findIndex(
      (candidate) => candidate.id === item.id
    )
    if (index >= 0) alerts.value[index] = updated
    notice.value = t("alerts.alertAcknowledged")
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    acknowledgingId.value = null
  }
}

async function openPlayback(item: AlertItem): Promise<void> {
  if (
    !item.camera_id ||
    !auth.hasPermission("recording.view")
  ) {
    return
  }

  playbackId.value = item.id
  error.value = null
  try {
    const event = await getEvent(item.event_id)
    await router.push({
      name: "playback",
      query: {
        camera: event.camera_id ?? item.camera_id,
        at: event.started_at
      }
    })
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    playbackId.value = null
  }
}

function handleRefreshEvent(): void {
  void refresh()
}

onMounted(() => {
  void refresh()
  window.addEventListener(
    "zero-nvr:refresh",
    handleRefreshEvent
  )
})

onBeforeUnmount(() => {
  window.removeEventListener(
    "zero-nvr:refresh",
    handleRefreshEvent
  )
})
</script>

<template>
  <section class="alert-center">
    <header class="alert-center__header">
      <div>
        <strong>{{ t("alerts.title") }}</strong>
        <span>
          {{ t("alerts.description") }}
        </span>
      </div>
      <button
        class="button button--ghost button--compact"
        type="button"
        :disabled="loading"
        @click="refresh"
      >
        <UiIcon name="refresh" :size="14" />
        {{ loading ? t("alerts.refreshing") : t("alerts.refresh") }}
      </button>
    </header>

    <div class="alert-center__summary">
      <button type="button" @click="mode = 'active'">
        <span>{{ t("alerts.open") }}</span>
        <strong>{{ openCount }}</strong>
      </button>
      <button type="button" @click="mode = 'active'">
        <span>{{ t("alerts.acknowledged") }}</span>
        <strong>{{ acknowledgedCount }}</strong>
      </button>
      <button type="button" @click="mode = 'recent'">
        <span>{{ t("alerts.resolved") }}</span>
        <strong>{{ resolvedCount }}</strong>
      </button>
    </div>

    <div class="alert-center__toolbar">
      <div class="alert-center__tabs">
        <button
          type="button"
          :class="{ 'alert-center__tab--active': mode === 'active' }"
          @click="mode = 'active'"
        >
          {{ t("alerts.active") }}
        </button>
        <button
          type="button"
          :class="{ 'alert-center__tab--active': mode === 'recent' }"
          @click="mode = 'recent'"
        >
          {{ t("alerts.recent") }}
        </button>
      </div>

      <label class="alert-center__search">
        <UiIcon name="search" :size="14" />
        <input v-model="search" :placeholder="t('alerts.searchAlerts')" />
      </label>

      <select
        v-if="cameras.length"
        v-model="cameraId"
        @change="refresh"
      >
        <option value="">{{ t("alerts.allCameras") }}</option>
        <option
          v-for="camera in cameras"
          :key="camera.id"
          :value="camera.id"
        >
          {{ camera.name }}
        </option>
      </select>

      <select v-model="severity" @change="refresh">
        <option value="">{{ t("alerts.allSeverity") }}</option>
        <option value="info">{{ t("alerts.info") }}</option>
        <option value="warning">{{ t("alerts.warning") }}</option>
        <option value="critical">{{ t("alerts.critical") }}</option>
      </select>
    </div>

    <div v-if="error" class="events-error">
      <UiIcon name="warning" :size="15" />
      <span>{{ error }}</span>
    </div>

    <div v-if="notice" class="storage-notice">
      <UiIcon name="check" :size="14" />
      <span>{{ notice }}</span>
    </div>

    <div
      v-if="!visibleAlerts.length && !loading"
      class="alert-center__empty"
    >
      <UiIcon name="bell" :size="28" />
      <strong>
        {{ mode === "active" ? t("alerts.noActiveAlerts") : t("alerts.noRecentAlerts") }}
      </strong>
      <span>
        {{ t("alerts.emptyHint") }}
      </span>
    </div>

    <div v-else class="alert-center__body">
      <div class="alert-center__list">
        <article
          v-for="item in visibleAlerts"
          :key="item.id"
          class="alert-card"
          :class="{
            'alert-card--selected': item.id === selectedId
          }"
          @click="selectAlert(item)"
        >
          <span
            class="alert-card__severity"
            :class="`alert-card__severity--${item.severity}`"
          />
          <div class="alert-card__main">
            <div class="alert-card__title">
              <strong>{{ item.title }}</strong>
              <span
                class="status-pill"
                :class="stateClass(item.state)"
              >
                {{ stateLabel(item.state) }}
              </span>
              <span class="status-pill">
                {{ severityLabel(item.severity) }}
              </span>
            </div>
            <span class="alert-card__meta">
              {{ cameraName(item.camera_id) }}
              · {{ formatTimestamp(item.created_at) }}
            </span>
            <p v-if="item.message">{{ item.message }}</p>
            <small>{{ deliverySummary(item.id) }}</small>
          </div>
          <div class="alert-card__actions">
            <button
              v-if="
                item.camera_id &&
                auth.hasPermission('recording.view') &&
                auth.hasPermission('event.view')
              "
              class="icon-button"
              type="button"
              :title="t('alerts.openPlayback')"
              :disabled="playbackId === item.id"
              @click.stop="openPlayback(item)"
            >
              <UiIcon name="playback" :size="14" />
            </button>
            <button
              v-if="
                item.state === 'OPEN' &&
                auth.hasPermission('alert.acknowledge')
              "
              class="button button--ghost button--compact"
              type="button"
              :disabled="acknowledgingId === item.id"
              @click.stop="acknowledge(item)"
            >
              {{ acknowledgingId === item.id ? t("alerts.saving") : t("alerts.acknowledge") }}
            </button>
          </div>
        </article>
      </div>

      <aside v-if="selectedAlert" class="alert-detail">
        <header>
          <div>
            <strong>{{ selectedAlert.title }}</strong>
            <span>{{ cameraName(selectedAlert.camera_id) }}</span>
          </div>
          <button
            class="icon-button"
            type="button"
            :title="t('alerts.closeDetails')"
            @click="selectedId = null"
          >
            <UiIcon name="close" :size="14" />
          </button>
        </header>

        <div class="alert-detail__badges">
          <span
            class="status-pill"
            :class="stateClass(selectedAlert.state)"
          >
            {{ stateLabel(selectedAlert.state) }}
          </span>
          <span class="status-pill">
            {{ severityLabel(selectedAlert.severity) }}
          </span>
        </div>

        <p v-if="selectedAlert.message">
          {{ selectedAlert.message }}
        </p>

        <dl>
          <div>
            <dt>{{ t("alerts.created") }}</dt>
            <dd>{{ formatTimestamp(selectedAlert.created_at) }}</dd>
          </div>
          <div v-if="selectedAlert.acknowledged_at">
            <dt>{{ t("alerts.acknowledged") }}</dt>
            <dd>
              {{ formatTimestamp(selectedAlert.acknowledged_at) }}
            </dd>
          </div>
          <div v-if="selectedAlert.resolved_at">
            <dt>{{ t("alerts.resolved") }}</dt>
            <dd>{{ formatTimestamp(selectedAlert.resolved_at) }}</dd>
          </div>
          <div>
            <dt>{{ t("alerts.event") }}</dt>
            <dd>{{ selectedAlert.event_id }}</dd>
          </div>
        </dl>

        <div class="alert-detail__actions">
          <button
            v-if="
              selectedAlert.camera_id &&
              auth.hasPermission('recording.view') &&
              auth.hasPermission('event.view')
            "
            class="button button--ghost"
            type="button"
            :disabled="playbackId === selectedAlert.id"
            @click="openPlayback(selectedAlert)"
          >
            <UiIcon name="playback" :size="14" />
            {{ t("alerts.openPlayback") }}
          </button>
          <button
            v-if="
              selectedAlert.state === 'OPEN' &&
              auth.hasPermission('alert.acknowledge')
            "
            class="button button--primary"
            type="button"
            :disabled="acknowledgingId === selectedAlert.id"
            @click="acknowledge(selectedAlert)"
          >
            {{ t("alerts.acknowledge") }}
          </button>
        </div>

        <section class="alert-detail__deliveries">
          <h3>{{ t("alerts.notificationDelivery") }}</h3>
          <template v-if="auth.hasPermission('alert.manage')">
            <div
              v-if="
                !(deliveriesByAlert.get(selectedAlert.id) || []).length
              "
              class="alert-detail__muted"
            >
              {{ t("alerts.noNotificationDeliveryCreated") }}
            </div>
            <article
              v-for="delivery in deliveriesByAlert.get(selectedAlert.id) || []"
              :key="delivery.id"
            >
              <div>
                <strong>{{ delivery.title }}</strong>
                <span>
                  {{ t("alerts.deliveryTargetAttempts", {
                    target: delivery.notification_target_id,
                    attempts: delivery.attempt_count
                  }) }}
                </span>
                <small v-if="delivery.last_error_code">
                  {{ delivery.last_error_code }}
                </small>
              </div>
              <span
                class="status-pill"
                :class="deliveryClass(delivery.state)"
              >
                {{ deliveryStateLabel(delivery.state) }}
              </span>
            </article>
          </template>
          <div v-else class="alert-detail__muted">
            {{ t("alerts.deliveryPermissionRequired") }}
          </div>
        </section>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.alert-center {
  display: grid;
  gap: 12px;
  padding: 14px;
}

.alert-center__header,
.alert-center__toolbar,
.alert-card,
.alert-detail > header,
.alert-detail__actions,
.alert-detail__deliveries article {
  display: flex;
  align-items: center;
}

.alert-center__header {
  justify-content: space-between;
  gap: 12px;
}

.alert-center__header strong,
.alert-center__header span {
  display: block;
}

.alert-center__header strong {
  font-size: 14px;
}

.alert-center__header span {
  margin-top: 3px;
  color: var(--text-muted);
  font-size: 9px;
}

.alert-center__summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.alert-center__summary button {
  display: flex;
  min-height: 58px;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: var(--surface-raised);
  color: var(--text-primary);
  cursor: pointer;
}

.alert-center__summary span {
  color: var(--text-muted);
  font-size: 8px;
  text-transform: uppercase;
}

.alert-center__summary strong {
  font-size: 20px;
}

.alert-center__toolbar {
  gap: 8px;
  flex-wrap: wrap;
}

.alert-center__tabs {
  display: flex;
  gap: 2px;
  padding: 2px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: var(--surface-base);
}

.alert-center__tabs button {
  min-height: 30px;
  padding: 0 10px;
  border: 0;
  border-radius: calc(var(--radius-sm) - 2px);
  background: transparent;
  color: var(--text-muted);
  font: inherit;
  font-size: 9px;
  cursor: pointer;
}

.alert-center__tabs .alert-center__tab--active {
  background: var(--surface-raised);
  color: var(--text-primary);
}

.alert-center__search {
  display: flex;
  min-width: 220px;
  flex: 1;
  align-items: center;
  gap: 6px;
  min-height: 34px;
  padding: 0 9px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: var(--surface-base);
  color: var(--text-muted);
}

.alert-center__search input,
.alert-center__toolbar select {
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--text-primary);
  font: inherit;
  font-size: 9px;
}

.alert-center__search input {
  width: 100%;
}

.alert-center__toolbar select {
  min-height: 34px;
  padding: 0 28px 0 9px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: var(--surface-base);
}

.alert-center__body {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(280px, 360px);
  gap: 10px;
  align-items: start;
}

.alert-center__list {
  display: grid;
  gap: 6px;
}

.alert-card {
  position: relative;
  min-width: 0;
  gap: 10px;
  padding: 10px 10px 10px 13px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: var(--surface-raised);
  cursor: pointer;
}

.alert-card--selected {
  border-color: var(--accent);
  box-shadow: 0 0 0 2px var(--focus-ring);
}

.alert-card__severity {
  position: absolute;
  top: 9px;
  bottom: 9px;
  left: 4px;
  width: 3px;
  border-radius: 4px;
  background: var(--text-muted);
}

.alert-card__severity--critical {
  background: var(--danger);
}

.alert-card__severity--warning {
  background: var(--warning);
}

.alert-card__severity--info {
  background: var(--accent);
}

.alert-card__main {
  min-width: 0;
  flex: 1;
}

.alert-card__title {
  display: flex;
  align-items: center;
  gap: 5px;
  flex-wrap: wrap;
}

.alert-card__title strong {
  margin-right: 3px;
  font-size: 10px;
}

.alert-card__meta,
.alert-card small {
  display: block;
  margin-top: 3px;
  color: var(--text-muted);
  font-size: 8px;
}

.alert-card p {
  margin: 5px 0 0;
  overflow: hidden;
  color: var(--text-secondary);
  font-size: 8px;
  line-height: 1.45;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.alert-card__actions {
  display: flex;
  align-items: center;
  gap: 5px;
}

.alert-detail {
  position: sticky;
  top: 10px;
  overflow: hidden;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: var(--surface-raised);
}

.alert-detail > header {
  justify-content: space-between;
  gap: 8px;
  padding: 10px 10px 9px 12px;
  border-bottom: 1px solid var(--border-subtle);
}

.alert-detail > header strong,
.alert-detail > header span {
  display: block;
}

.alert-detail > header strong {
  font-size: 10px;
}

.alert-detail > header span {
  margin-top: 2px;
  color: var(--text-muted);
  font-size: 8px;
}

.alert-detail__badges,
.alert-detail > p,
.alert-detail > dl,
.alert-detail__actions,
.alert-detail__deliveries {
  margin: 0;
  padding: 10px 12px;
}

.alert-detail__badges {
  display: flex;
  gap: 5px;
}

.alert-detail > p {
  padding-top: 0;
  color: var(--text-secondary);
  font-size: 9px;
  line-height: 1.5;
}

.alert-detail > dl {
  display: grid;
  gap: 7px;
  border-top: 1px solid var(--border-subtle);
}

.alert-detail dl div {
  display: grid;
  grid-template-columns: 90px minmax(0, 1fr);
  gap: 8px;
}

.alert-detail dt {
  color: var(--text-muted);
  font-size: 8px;
}

.alert-detail dd {
  margin: 0;
  overflow-wrap: anywhere;
  font-size: 8px;
}

.alert-detail__actions {
  gap: 6px;
  border-top: 1px solid var(--border-subtle);
}

.alert-detail__deliveries {
  border-top: 1px solid var(--border-subtle);
}

.alert-detail__deliveries h3 {
  margin: 0 0 7px;
  color: var(--text-muted);
  font-size: 8px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.alert-detail__deliveries article {
  justify-content: space-between;
  gap: 8px;
  padding: 7px 0;
  border-bottom: 1px solid var(--border-subtle);
}

.alert-detail__deliveries article:last-child {
  border-bottom: 0;
}

.alert-detail__deliveries article div {
  min-width: 0;
}

.alert-detail__deliveries strong,
.alert-detail__deliveries span,
.alert-detail__deliveries small {
  display: block;
}

.alert-detail__deliveries strong {
  font-size: 8px;
}

.alert-detail__deliveries article div > span,
.alert-detail__deliveries small,
.alert-detail__muted {
  margin-top: 2px;
  color: var(--text-muted);
  font-size: 7px;
}

.alert-center__empty {
  display: grid;
  min-height: 220px;
  place-items: center;
  align-content: center;
  gap: 6px;
  color: var(--text-muted);
  text-align: center;
}

.alert-center__empty strong {
  color: var(--text-primary);
  font-size: 10px;
}

.alert-center__empty span {
  font-size: 8px;
}

@media (max-width: 980px) {
  .alert-center__body {
    grid-template-columns: minmax(0, 1fr);
  }

  .alert-detail {
    position: static;
  }
}

@media (max-width: 640px) {
  .alert-center__summary {
    grid-template-columns: 1fr;
  }

  .alert-card {
    align-items: flex-start;
  }

  .alert-card__actions {
    flex-direction: column;
  }
}
</style>
