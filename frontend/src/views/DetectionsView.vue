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

const viewMode = ref<"grid" | "table">("grid")
const sortBy = ref<"newest" | "confidence" | "severity">("newest")
const histogramActiveHour = ref<number | null>(null)

function setViewMode(mode: "grid" | "table") {
  viewMode.value = mode
}

function setSort(val: "newest" | "confidence" | "severity") {
  sortBy.value = val
  // You would typically sort events here or trigger a refresh
}

function filterEventCategory(cat: string) {
  category.value = cat === "all" ? "" : cat
  void refresh()
}

function resetEventFilters() {
  resetFilters()
}

function toggleEventDrawer() {
  selectedEvent.value = null
}

function jumpFromEventToTimeLapse() {
  if (selectedEvent.value) {
    viewRecording(selectedEvent.value)
  }
}

// Generate fake histogram data
const histogramBars = computed(() => {
  return Array.from({ length: 24 }, (_, i) => ({
    hour: i,
    count: Math.floor(Math.random() * 150)
  }))
})

function toggleHistogramHour(hour: number) {
  if (histogramActiveHour.value === hour) {
    histogramActiveHour.value = null
  } else {
    histogramActiveHour.value = hour
  }
}

</script>

<template>
  <div class="detections-view">
    <!-- Header -->
    <header class="detections-header">
      <div class="header-left">
        <div class="header-icon">
          <svg class="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
        </div>
        <div>
          <h1 class="header-title">{{ t('events.title', '事件与告警处理中心') }}</h1>
          <p class="header-desc">{{ t('events.description', '高通量 AI 识别事件排查工作台 (Detections Center)') }}</p>
        </div>
      </div>
      
      <div class="header-right">
        <div class="stats-group">
          <span class="stat-pill">
            <span class="stat-dot dot-emerald"></span>
            <span id="stat-total-events">今日事件: {{ events.length }}</span>
          </span>
          <span class="stat-pill stat-pill-red" v-if="activeAlerts.length > 0">
            <span class="stat-dot dot-red pulse"></span>
            <span id="stat-critical-events">待处理告警: {{ activeAlerts.length }}</span>
          </span>
        </div>

        <div class="batch-actions">
          <button class="btn-ghost" @click="refresh">
            <UiIcon name="refresh" :size="14" />
            <span>刷新</span>
          </button>
        </div>
      </div>
    </header>

    <!-- Filters Bar -->
    <div class="filters-bar">
      <!-- Row 1: Categories & Search -->
      <div class="filters-row-1">
        <div class="category-chips">
          <button class="chip" :class="{ active: category === '' }" @click="filterEventCategory('all')">全部</button>
          <button class="chip" :class="{ active: category === 'person' }" @click="filterEventCategory('person')">👤 人员</button>
          <button class="chip" :class="{ active: category === 'vehicle' }" @click="filterEventCategory('vehicle')">🚗 车辆</button>
          <button class="chip" :class="{ active: category === 'package' }" @click="filterEventCategory('package')">📦 包裹</button>
          <button class="chip" :class="{ active: category === 'animal' }" @click="filterEventCategory('animal')">🐾 动物</button>
          <button class="chip" :class="{ active: category === 'motion' }" @click="filterEventCategory('motion')">⚡ 动检</button>
        </div>
        
        <div class="search-box">
          <UiIcon name="search" :size="14" class="search-icon" />
          <input type="text" v-model="label" placeholder="搜索车牌 / 属性 / 机位 / 标签..." @keydown.enter="refresh" />
        </div>
      </div>

      <!-- Row 2: Camera, Time, View mode -->
      <div class="filters-row-2">
        <div class="dropdowns">
          <div class="dropdown-group">
            <span class="dropdown-label">机位:</span>
            <select v-model="cameraId" @change="refresh">
              <option value="">全部机位 (All)</option>
              <option v-for="cam in cameras" :key="cam.id" :value="cam.id">{{ cam.name }}</option>
            </select>
          </div>
          
          <div class="dropdown-group">
            <span class="dropdown-label">时段:</span>
            <select v-model="period" @change="refresh">
              <option value="24h">过去 24 小时</option>
              <option value="7d">近 7 天</option>
              <option value="30d">近 30 天</option>
              <option value="all">所有时间</option>
            </select>
          </div>
          
          <div class="dropdown-group">
            <span class="dropdown-label">排序:</span>
            <select v-model="sortBy" @change="setSort(sortBy)">
              <option value="newest">🕒 时间最新优先</option>
              <option value="confidence">🎯 置信度最高</option>
              <option value="severity">🚨 严重级别最高</option>
            </select>
          </div>
        </div>

        <div class="view-toggles">
          <button class="toggle-btn" :class="{ active: viewMode === 'grid' }" @click="setViewMode('grid')">
            <UiIcon name="dashboard" :size="14" />
          </button>
          <button class="toggle-btn" :class="{ active: viewMode === 'table' }" @click="setViewMode('table')">
            <UiIcon name="list" :size="14" />
          </button>
        </div>
      </div>

      <!-- Row 3: Histogram -->
      <div class="histogram-row">
        <div class="histogram-label">
          <span>24H 分布直方图:</span>
          <span v-if="histogramActiveHour !== null" class="histogram-active-text" @click="histogramActiveHour = null">
            已选 {{ histogramActiveHour }}:00 (✕ 取消)
          </span>
        </div>
        <div class="histogram-bars">
          <div 
            v-for="bar in histogramBars" 
            :key="bar.hour" 
            class="hist-bar"
            :class="{ active: histogramActiveHour === bar.hour }"
            :style="{ height: Math.max(10, (bar.count / 150) * 100) + '%' }"
            @click="toggleHistogramHour(bar.hour)"
            :title="`${bar.hour}:00 - ${bar.count} 次`"
          ></div>
        </div>
      </div>
    </div>

    <!-- Main Content -->
    <div class="detections-content">
      <!-- Left: Stream Container -->
      <div class="stream-container">
        
        <div v-if="loading && !events.length" class="empty-state">
          <UiIcon name="events" :size="30" />
          <strong>{{ t("events.loadingEvents") }}</strong>
        </div>

        <div v-else-if="!events.length" class="empty-state">
          <UiIcon name="events" :size="30" />
          <strong>{{ t("events.noEvents") }}</strong>
          <span>{{ t("events.noEventsHint") }}</span>
          <button class="btn-primary mt-3" @click="resetFilters">重置所有筛选</button>
        </div>
        
        <!-- Grid View -->
        <div v-else-if="viewMode === 'grid'" class="grid-view">
          <div 
            v-for="item in events" 
            :key="item.id" 
            class="event-card"
            :class="{ selected: selectedEvent?.id === item.id }"
            @click="selectEvent(item)"
          >
            <div class="event-card-preview">
              <img
                v-if="canShowSnapshot(item)"
                :src="eventSnapshotUrl(item.id)"
                :alt="t('events.eventAlt', { name: item.label || pretty(item.category) })"
                loading="lazy"
                @error="snapshotFailed(item.id)"
              />
              <div v-else class="placeholder">
                <UiIcon name="events" :size="24" />
              </div>
              <span class="time-badge">{{ formatTime(item.started_at) }}</span>
              <span v-if="confidenceLabel(item.confidence)" class="confidence-badge">
                {{ confidenceLabel(item.confidence) }}
              </span>
            </div>
            <div class="event-card-info">
              <div class="title-row">
                <strong>{{ item.label || pretty(item.category) }}</strong>
                <span>{{ formatDate(item.started_at) }}</span>
              </div>
              <div class="meta-row">
                <span><UiIcon name="cameras" :size="12" /> {{ cameraName(item) }}</span>
              </div>
            </div>
          </div>
          
          <button v-if="nextCursor" class="btn-load-more" :disabled="loadingMore" @click="loadMore">
            {{ loadingMore ? t("events.loading") : t("events.loadMore") }}
          </button>
        </div>

        <!-- Table View -->
        <div v-else-if="viewMode === 'table'" class="table-view">
          <table class="events-table">
            <thead>
              <tr>
                <th>发生时间</th>
                <th>机位名称</th>
                <th>实体类型</th>
                <th>置信度</th>
                <th>时长</th>
              </tr>
            </thead>
            <tbody>
              <tr 
                v-for="item in events" 
                :key="item.id"
                :class="{ selected: selectedEvent?.id === item.id }"
                @click="selectEvent(item)"
              >
                <td>{{ formatDate(item.started_at) }} {{ formatTime(item.started_at) }}</td>
                <td>{{ cameraName(item) }}</td>
                <td>{{ item.label || pretty(item.category) }}</td>
                <td>{{ confidenceLabel(item.confidence) || '-' }}</td>
                <td>{{ formatDuration(item) || '-' }}</td>
              </tr>
            </tbody>
          </table>
          
          <button v-if="nextCursor" class="btn-load-more" :disabled="loadingMore" @click="loadMore">
            {{ loadingMore ? t("events.loading") : t("events.loadMore") }}
          </button>
        </div>
      </div>

      <!-- Right: Inspector Drawer -->
      <aside v-if="selectedEvent" class="inspector-drawer">
        <div class="inspector-header">
          <div class="drawer-title">
            <span class="dot-blue"></span>
            <span>事件物证详情 (Forensics)</span>
          </div>
          <button class="btn-icon" @click="toggleEventDrawer"><UiIcon name="close" :size="14"/></button>
        </div>
        
        <div class="inspector-body">
          <div class="preview-box">
            <img
              v-if="canShowSnapshot(selectedEvent)"
              :src="eventSnapshotUrl(selectedEvent.id)"
              :alt="t('events.snapshotAlt')"
              @error="snapshotFailed(selectedEvent.id)"
            />
            <div v-else class="placeholder">
              <UiIcon name="events" :size="30" />
            </div>
            
            <div class="badge-type">
              {{ selectedEvent.label || pretty(selectedEvent.category) }} {{ confidenceLabel(selectedEvent.confidence) }}
            </div>
          </div>

          <button class="btn-jump" @click="jumpFromEventToTimeLapse">
            <UiIcon name="playback" :size="16" />
            <span>跳转时光轴精准回放</span>
          </button>

          <div class="facts-section">
            <div class="fact-row">
              <span class="fact-label">时间</span>
              <span class="fact-value">{{ formatDate(selectedEvent.started_at) }} {{ formatTime(selectedEvent.started_at) }}</span>
            </div>
            <div class="fact-row">
              <span class="fact-label">机位</span>
              <span class="fact-value">{{ cameraName(selectedEvent) }}</span>
            </div>
            <div class="fact-row">
              <span class="fact-label">来源</span>
              <span class="fact-value">{{ pretty(selectedEvent.source) }}</span>
            </div>
            <div v-if="selectedEvent.zone" class="fact-row">
              <span class="fact-label">区域</span>
              <span class="fact-value">{{ selectedEvent.zone }}</span>
            </div>
          </div>
          
          <div v-if="metadataRows(selectedEvent).length" class="facts-section mt-4">
            <div class="section-title">提取特征</div>
            <div class="fact-row" v-for="[key, value] in metadataRows(selectedEvent)" :key="key">
              <span class="fact-label">{{ key }}</span>
              <span class="fact-value">{{ value }}</span>
            </div>
          </div>
        </div>
      </aside>
    </div>
  </div>
</template>


<style scoped>
.detections-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  width: 100%;
  background-color: #0c0e14;
  color: #f1f3f7;
  overflow: hidden;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}

/* Header */
.detections-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  background-color: #12151e;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  height: 52px;
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.header-icon {
  width: 32px;
  height: 32px;
  background: linear-gradient(135deg, #3b82f6, #1d4ed8);
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.header-icon svg {
  width: 20px;
  height: 20px;
  color: white;
}

.header-title {
  font-size: 14px;
  font-weight: 700;
  margin: 0;
  color: white;
  line-height: 1.2;
}

.header-desc {
  font-size: 10px;
  color: #9ca3af;
  margin: 0;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.stats-group {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 11px;
  color: #9ca3af;
}

.stat-pill {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 2px 8px;
  border-radius: 999px;
  background-color: rgba(255, 255, 255, 0.05);
}

.stat-pill-red {
  background-color: rgba(239, 68, 68, 0.2);
  color: #f87171;
  font-weight: 700;
}

.stat-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}
.dot-emerald { background-color: #34d399; }
.dot-red { background-color: #f87171; }
.dot-blue { background-color: #60a5fa; }

.pulse {
  animation: pulse-ring 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
}
@keyframes pulse-ring {
  0% { box-shadow: 0 0 0 0 rgba(248, 113, 113, 0.7); }
  70% { box-shadow: 0 0 0 4px rgba(248, 113, 113, 0); }
  100% { box-shadow: 0 0 0 0 rgba(248, 113, 113, 0); }
}

.batch-actions {
  display: flex;
  gap: 8px;
}

.btn-ghost {
  background: #171b26;
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #d1d5db;
  padding: 6px 10px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
  transition: all 0.2s;
}
.btn-ghost:hover {
  background: rgba(255, 255, 255, 0.1);
  color: white;
}

.btn-primary {
  background: #2563eb;
  color: white;
  border: none;
  padding: 6px 12px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}
.btn-primary:hover {
  background: #1d4ed8;
}

/* Filters */
.filters-bar {
  background-color: #12151e;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  padding: 10px 20px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex-shrink: 0;
}

.filters-row-1, .filters-row-2 {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.category-chips {
  display: flex;
  gap: 6px;
  overflow-x: auto;
}

.chip {
  background: #181d2a;
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #d1d5db;
  padding: 4px 12px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 500;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.2s;
}
.chip:hover {
  background: rgba(255, 255, 255, 0.1);
  color: white;
}
.chip.active {
  background: #2563eb;
  border-color: #2563eb;
  color: white;
  font-weight: 600;
}

.search-box {
  position: relative;
  width: 250px;
}
.search-icon {
  position: absolute;
  left: 10px;
  top: 50%;
  transform: translateY(-50%);
  color: #9ca3af;
}
.search-box input {
  width: 100%;
  background: #181d2a;
  border: 1px solid rgba(255, 255, 255, 0.15);
  border-radius: 6px;
  padding: 6px 10px 6px 30px;
  color: white;
  font-size: 11px;
  outline: none;
}
.search-box input:focus {
  border-color: #3b82f6;
}

.dropdowns {
  display: flex;
  gap: 16px;
}

.dropdown-group {
  display: flex;
  align-items: center;
  gap: 6px;
}

.dropdown-label {
  font-size: 11px;
  color: #9ca3af;
}

.dropdown-group select {
  background: #181d2a;
  border: 1px solid rgba(255, 255, 255, 0.15);
  border-radius: 4px;
  padding: 4px 8px;
  color: white;
  font-size: 11px;
  outline: none;
  cursor: pointer;
}

.view-toggles {
  display: flex;
  background: #181d2a;
  padding: 2px;
  border-radius: 6px;
  border: 1px solid rgba(255, 255, 255, 0.1);
}

.toggle-btn {
  background: transparent;
  border: none;
  padding: 4px;
  border-radius: 4px;
  color: #9ca3af;
  cursor: pointer;
}
.toggle-btn.active {
  background: #2563eb;
  color: white;
}

.histogram-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding-top: 8px;
  border-top: 1px solid rgba(255, 255, 255, 0.05);
}

.histogram-label {
  font-size: 10px;
  color: #9ca3af;
  font-family: monospace;
  display: flex;
  gap: 6px;
}
.histogram-active-text {
  color: #60a5fa;
  font-weight: 700;
  cursor: pointer;
}

.histogram-bars {
  flex: 1;
  display: flex;
  align-items: flex-end;
  height: 28px;
  gap: 2px;
}

.hist-bar {
  flex: 1;
  background-color: #374151;
  border-radius: 2px 2px 0 0;
  cursor: pointer;
  transition: background-color 0.2s;
}
.hist-bar:hover {
  background-color: #60a5fa;
}
.hist-bar.active {
  background-color: #3b82f6;
}

/* Content */
.detections-content {
  flex: 1;
  display: flex;
  overflow: hidden;
}

.stream-container {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
}

.empty-state {
  margin: auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #9ca3af;
  gap: 8px;
}
.empty-state strong {
  color: white;
  font-size: 14px;
}
.empty-state span {
  font-size: 12px;
}

.grid-view {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 14px;
}

.event-card {
  background: #12151e;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 10px;
  overflow: hidden;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  flex-direction: column;
}
.event-card:hover {
  border-color: rgba(255, 255, 255, 0.2);
  transform: translateY(-1px);
}
.event-card.selected {
  border-color: #3b82f6;
  box-shadow: 0 0 0 1px #3b82f6;
}

.event-card-preview {
  position: relative;
  aspect-ratio: 16/9;
  background: #000;
  overflow: hidden;
}
.event-card-preview img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.event-card-preview .placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #4b5563;
}

.time-badge {
  position: absolute;
  bottom: 6px;
  right: 6px;
  background: rgba(0, 0, 0, 0.7);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 10px;
  font-family: monospace;
}
.confidence-badge {
  position: absolute;
  top: 6px;
  left: 6px;
  background: rgba(16, 185, 129, 0.2);
  border: 1px solid rgba(16, 185, 129, 0.3);
  color: #34d399;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 700;
}

.event-card-info {
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
}
.title-row strong {
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.title-row span {
  color: #9ca3af;
  font-size: 10px;
  flex-shrink: 0;
}

.meta-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: #9ca3af;
}
.meta-row span {
  display: flex;
  align-items: center;
  gap: 4px;
}

.table-view {
  background: #12151e;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 10px;
  overflow: hidden;
}
.events-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.events-table th {
  text-align: left;
  padding: 10px 12px;
  color: #9ca3af;
  background: rgba(255, 255, 255, 0.02);
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  font-weight: 600;
}
.events-table td {
  padding: 10px 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}
.events-table tr {
  cursor: pointer;
}
.events-table tr:hover {
  background: rgba(255, 255, 255, 0.03);
}
.events-table tr.selected {
  background: rgba(59, 130, 246, 0.1);
}

.btn-load-more {
  margin-top: 16px;
  align-self: center;
  background: #1f2937;
  color: white;
  border: none;
  padding: 8px 16px;
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
}
.btn-load-more:hover {
  background: #374151;
}

/* Inspector Drawer */
.inspector-drawer {
  width: 340px;
  background: #10131c;
  border-left: 1px solid rgba(255, 255, 255, 0.08);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
}

.inspector-header {
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
  background: #131622;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
.drawer-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.btn-icon {
  background: transparent;
  border: none;
  color: #9ca3af;
  cursor: pointer;
  padding: 4px;
}
.btn-icon:hover { color: white; }

.inspector-body {
  padding: 16px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.preview-box {
  width: 100%;
  aspect-ratio: 16/9;
  background: #000;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 10px;
  overflow: hidden;
  position: relative;
}
.preview-box img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.preview-box .placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #4b5563;
}
.badge-type {
  position: absolute;
  top: 8px;
  left: 8px;
  background: rgba(0, 0, 0, 0.7);
  backdrop-filter: blur(4px);
  border: 1px solid rgba(255, 255, 255, 0.1);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 10px;
  font-family: monospace;
  color: #6ee7b7;
}

.btn-jump {
  width: 100%;
  background: #2563eb;
  color: white;
  border: none;
  padding: 10px;
  border-radius: 10px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  cursor: pointer;
  box-shadow: 0 4px 14px rgba(37, 99, 235, 0.3);
  transition: all 0.2s;
}
.btn-jump:hover {
  background: #1d4ed8;
}

.facts-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 11px;
}
.section-title {
  font-size: 12px;
  font-weight: 600;
  color: white;
  margin-bottom: 4px;
}
.fact-row {
  display: flex;
  justify-content: space-between;
}
.fact-label {
  color: #9ca3af;
}
.fact-value {
  color: white;
  font-weight: 500;
  text-align: right;
  max-width: 70%;
}
.mt-4 { margin-top: 16px; }
</style>
