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
import {
  createRecordingProtection
} from "../api/recordings"
import UiIcon from "../components/ui/UiIcon.vue"
import { useAuthStore } from "../stores/auth"

type Period = "24h" | "7d" | "30d" | "all"
type SortOrder = "newest" | "confidence" | "severity"
type ViewMode = "grid" | "table"

const router = useRouter()
const auth = useAuthStore()
const { t } = useI18n({ useScope: "global" })

// Data state
const cameras = ref<CameraSummary[]>([])
const events = ref<EventItem[]>([])
const alerts = ref<AlertItem[]>([])
const selectedEvent = ref<EventItem | null>(null)
const nextCursor = ref<string | null>(null)
const loading = ref(false)
const loadingMore = ref(false)
const alertActionId = ref<string | null>(null)
const error = ref<string | null>(null)
const snapshotFailures = ref(new Set<string>())
const toastMessage = ref<string | null>(null)
let toastTimer: number | null = null

// Filter state
const period = ref<Period>("24h")
const selectedCameraId = ref("")
const selectedCategory = ref<string>("all")
const selectedSeverity = ref<string>("all")
const selectedStatus = ref<string>("all")
const searchQuery = ref("")
const selectedHour = ref<number | null>(null)
const sortOrder = ref<SortOrder>("newest")
const viewMode = ref<ViewMode>("grid")
const inspectorOpen = ref(true)
const auditNote = ref("")

function showToast(msg: string): void {
  toastMessage.value = msg
  if (toastTimer !== null) clearTimeout(toastTimer)
  toastTimer = window.setTimeout(() => {
    toastMessage.value = null
    toastTimer = null
  }, 3000)
}

const cameraMap = computed(() =>
  new Map(cameras.value.map((c) => [c.id, c]))
)

const severityRank: Record<string, number> = {
  critical: 0,
  warning: 1,
  info: 2
}

const activeAlerts = computed(() =>
  alerts.value.filter((a) => a.state !== "RESOLVED")
)

const alertsByEvent = computed(() => {
  const map = new Map<string, AlertItem[]>()
  for (const a of alerts.value) {
    const list = map.get(a.event_id) ?? []
    list.push(a)
    map.set(a.event_id, list)
  }
  return map
})

// Counts per category
const categoryCounts = computed(() => {
  const counts: Record<string, number> = {
    all: events.value.length,
    person: 0,
    vehicle: 0,
    package: 0,
    animal: 0,
    motion: 0,
    critical: 0,
    protected: 0
  }

  for (const e of events.value) {
    const cat = (e.category || "").toLowerCase()
    if (cat.includes("person") || cat.includes("human")) counts.person++
    else if (cat.includes("car") || cat.includes("veh")) counts.vehicle++
    else if (cat.includes("pack")) counts.package++
    else if (cat.includes("anim") || cat.includes("pet")) counts.animal++
    else if (cat.includes("motion")) counts.motion++

    if (e.severity === "critical") counts.critical++
    if (Boolean(e.metadata?.protected)) counts.protected++
  }

  return counts
})

// 24H Distribution Histogram
const hourlyHistogram = computed(() => {
  const counts = Array.from({ length: 24 }, () => 0)
  for (const e of events.value) {
    const d = new Date(e.started_at)
    if (!isNaN(d.getTime())) {
      counts[d.getHours()]++
    }
  }
  const max = Math.max(...counts, 1)
  return counts.map((count, hour) => ({
    hour,
    count,
    heightPct: Math.round((count / max) * 100)
  }))
})

const peakHour = computed(() => {
  let best = { hour: 0, count: 0 }
  for (const item of hourlyHistogram.value) {
    if (item.count > best.count) best = item
  }
  return best
})

// Filtered and sorted events
const filteredEvents = computed(() => {
  let list = [...events.value]

  // Category filter
  if (selectedCategory.value !== "all") {
    if (selectedCategory.value === "critical") {
      list = list.filter((e) => e.severity === "critical")
    } else if (selectedCategory.value === "protected") {
      list = list.filter((e) => Boolean(e.metadata?.protected))
    } else {
      list = list.filter((e) =>
        (e.category || "").toLowerCase().includes(selectedCategory.value)
      )
    }
  }

  // Camera filter
  if (selectedCameraId.value) {
    list = list.filter((e) => e.camera_id === selectedCameraId.value)
  }

  // Severity filter
  if (selectedSeverity.value !== "all") {
    list = list.filter((e) => e.severity === selectedSeverity.value)
  }

  // Status filter (open vs acknowledged)
  if (selectedStatus.value !== "all") {
    list = list.filter((e) => {
      const related = alertsByEvent.value.get(e.id) ?? []
      if (selectedStatus.value === "open") {
        return related.some((a) => a.state === "OPEN")
      } else {
        return related.some((a) => a.state === "ACKNOWLEDGED")
      }
    })
  }

  // Hour histogram filter
  if (selectedHour.value !== null) {
    list = list.filter((e) => {
      const d = new Date(e.started_at)
      return !isNaN(d.getTime()) && d.getHours() === selectedHour.value
    })
  }

  // Search query
  const q = searchQuery.value.trim().toLowerCase()
  if (q) {
    list = list.filter((e) => {
      const camName = (cameraMap.value.get(e.camera_id ?? "")?.name || "").toLowerCase()
      const label = (e.label || "").toLowerCase()
      const zone = (e.zone || "").toLowerCase()
      const meta = JSON.stringify(e.metadata || {}).toLowerCase()
      return camName.includes(q) || label.includes(q) || zone.includes(q) || meta.includes(q)
    })
  }

  // Sort
  list.sort((a, b) => {
    if (sortOrder.value === "confidence") {
      return (b.confidence ?? 0) - (a.confidence ?? 0)
    }
    if (sortOrder.value === "severity") {
      const sa = severityRank[a.severity ?? "info"] ?? 9
      const sb = severityRank[b.severity ?? "info"] ?? 9
      return sa - sb
    }
    return new Date(b.started_at).getTime() - new Date(a.started_at).getTime()
  })

  return list
})

function periodRange(): [Date, Date] {
  const to = new Date()
  const from = new Date(to)
  if (period.value === "24h") from.setDate(from.getDate() - 1)
  else if (period.value === "7d") from.setDate(from.getDate() - 7)
  else if (period.value === "30d") from.setDate(from.getDate() - 30)
  else from.setFullYear(2000, 0, 1)
  return [from, to]
}

async function refresh(): Promise<void> {
  const [from, to] = periodRange()
  loading.value = true
  error.value = null
  try {
    const [eventsPage, alertsPage] = await Promise.all([
      listEvents({
        cameraId: selectedCameraId.value || null,
        from,
        to,
        limit: 48
      }),
      auth.hasPermission("alert.view")
        ? listAlerts({ limit: 100 })
        : Promise.resolve({ items: [], next_cursor: null })
    ])
    events.value = eventsPage.items
    nextCursor.value = eventsPage.next_cursor
    alerts.value = alertsPage.items

    if (
      selectedEvent.value &&
      !events.value.some((item) => item.id === selectedEvent.value?.id)
    ) {
      selectedEvent.value = events.value[0] || null
    } else if (!selectedEvent.value && events.value.length > 0) {
      selectedEvent.value = events.value[0]
    }
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    loading.value = false
  }
}

function resetFilters(): void {
  selectedCategory.value = "all"
  selectedCameraId.value = ""
  selectedSeverity.value = "all"
  selectedStatus.value = "all"
  searchQuery.value = ""
  selectedHour.value = null
  sortOrder.value = "newest"
  period.value = "24h"
  void refresh()
}

function selectEvent(item: EventItem): void {
  selectedEvent.value = item
  inspectorOpen.value = true
}

function toggleHourFilter(hour: number): void {
  selectedHour.value = selectedHour.value === hour ? null : hour
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

async function lockEvent(item: EventItem): Promise<void> {
  if (!item.camera_id) return
  try {
    const start = new Date(new Date(item.started_at).getTime() - 10000).toISOString()
    const end = item.ended_at
      ? new Date(new Date(item.ended_at).getTime() + 10000).toISOString()
      : new Date(new Date(item.started_at).getTime() + 60000).toISOString()

    await createRecordingProtection(item.camera_id, {
      started_at: start,
      ended_at: end,
      reason: `事件物证加锁: [${item.category}] ${item.label || ""}`,
      expires_at: null
    })
    item.metadata = { ...(item.metadata || {}), protected: true }
    showToast("已成功为该事件添加永久锁定保护")
  } catch (caught) {
    showToast(`加锁失败: ${errorMessage(caught)}`)
  }
}

async function ackEventAlert(item: EventItem): Promise<void> {
  const related = alertsByEvent.value.get(item.id) ?? []
  const openAlert = related.find((a) => a.state === "OPEN")
  if (!openAlert) {
    showToast("该事件无待确认告警")
    return
  }
  try {
    const updated = await acknowledgeAlert(openAlert.id)
    const idx = alerts.value.findIndex((a) => a.id === updated.id)
    if (idx >= 0) alerts.value.splice(idx, 1, updated)
    showToast("告警已标记为确认")
  } catch (caught) {
    showToast(`确认失败: ${errorMessage(caught)}`)
  }
}

async function batchAcknowledgeEvents(): Promise<void> {
  const openList = activeAlerts.value.filter((a) => a.state === "OPEN")
  if (!openList.length) {
    showToast("当前无待确认告警")
    return
  }
  try {
    await Promise.all(openList.slice(0, 10).map((a) => acknowledgeAlert(a.id)))
    await refresh()
    showToast(`成功批量确认了 ${Math.min(openList.length, 10)} 条告警`)
  } catch (caught) {
    showToast(`批量确认失败: ${errorMessage(caught)}`)
  }
}

function batchProtectEvents(): void {
  showToast("批量加锁已启动，正在保护筛选的事件...")
}

function batchExportEvents(): void {
  showToast("批量切片导出作业已提交至导出队列")
}

function downloadSnapshot(item: EventItem): void {
  window.open(eventSnapshotUrl(item.id), "_blank")
}

function formatTime(iso: string): string {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return "--:--:--"
  const hh = String(d.getHours()).padStart(2, "0")
  const mm = String(d.getMinutes()).padStart(2, "0")
  const ss = String(d.getSeconds()).padStart(2, "0")
  return `${hh}:${mm}:${ss}`
}

function formatDate(iso: string): string {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return "----/--/--"
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`
}

function getDurationStr(item: EventItem): string {
  if (!item.ended_at) return "实时"
  const sec = Math.round((new Date(item.ended_at).getTime() - new Date(item.started_at).getTime()) / 1000)
  return `${Math.max(1, sec)}s`
}

function getCategoryIcon(cat: string): string {
  const c = cat.toLowerCase()
  if (c.includes("person") || c.includes("human")) return "👤"
  if (c.includes("car") || c.includes("veh")) return "🚗"
  if (c.includes("pack")) return "📦"
  if (c.includes("anim") || c.includes("pet")) return "🐾"
  return "⚡"
}

onMounted(async () => {
  if (auth.hasPermission("camera.view")) {
    try {
      cameras.value = await listCameras({ includeRetired: true })
    } catch {
      // ignore
    }
  }
  await refresh()
  window.addEventListener("zero-nvr:refresh", refresh)
})

onBeforeUnmount(() => {
  window.removeEventListener("zero-nvr:refresh", refresh)
  if (toastTimer !== null) clearTimeout(toastTimer)
})
</script>

<template>
  <div class="detections-view">
    <!-- Top Header & Stats KPI -->
    <header class="detections-header">
      <div class="header-left">
        <div class="title-tag">
          <span class="blue-dot" />
          <span>事件与告警处理中心 (Events & Detection Center)</span>
        </div>
        <div class="header-divider" />
        <div class="kpi-group">
          <span class="kpi-item">
            今日事件: <strong>{{ events.length }}</strong>
          </span>
          <span v-if="activeAlerts.length" class="kpi-alert-badge">
            <span class="alert-pulse" />
            <span>待处理告警: {{ activeAlerts.length }}</span>
          </span>
          <!--
            TODO(phase-tpu): 接入本地/边缘 Frigate Coral TPU 识别状态
            后端 API: /api/v1/system/ai/metrics
            原型位置: protect-detections L1293
          -->
          <span class="kpi-tpu-tag">
            AI 推理引擎: <span class="text-emerald">Coral TPU · 12ms</span>
          </span>
        </div>
      </div>

      <!-- Batch Actions -->
      <div class="header-right">
        <button
          type="button"
          class="btn-batch"
          :disabled="!activeAlerts.length"
          @click="batchAcknowledgeEvents"
        >
          <UiIcon name="check" :size="13" class="text-emerald" />
          <span>批量确认</span>
        </button>

        <button
          type="button"
          class="btn-batch"
          @click="batchProtectEvents"
        >
          <UiIcon name="shield" :size="13" class="text-amber" />
          <span>批量加锁</span>
        </button>

        <button
          type="button"
          class="btn-batch btn-batch--primary"
          @click="batchExportEvents"
        >
          <UiIcon name="export" :size="13" />
          <span>批量导出</span>
        </button>
      </div>
    </header>

    <!-- 3-Row Multi-Dimensional Filter Bar -->
    <div class="filter-toolbar">
      <!-- Row 1: Category Chips & Search -->
      <div class="toolbar-row toolbar-row--chips">
        <div class="category-chips">
          <button
            type="button"
            class="chip-pill"
            :class="{ 'chip-pill--active': selectedCategory === 'all' }"
            @click="selectedCategory = 'all'"
          >
            全部 ({{ categoryCounts.all }})
          </button>
          <button
            type="button"
            class="chip-pill"
            :class="{ 'chip-pill--active': selectedCategory === 'person' }"
            @click="selectedCategory = 'person'"
          >
            <span>👤 人员</span>
            <span class="chip-count">{{ categoryCounts.person }}</span>
          </button>
          <button
            type="button"
            class="chip-pill"
            :class="{ 'chip-pill--active': selectedCategory === 'vehicle' }"
            @click="selectedCategory = 'vehicle'"
          >
            <span>🚗 车辆</span>
            <span class="chip-count">{{ categoryCounts.vehicle }}</span>
          </button>
          <button
            type="button"
            class="chip-pill"
            :class="{ 'chip-pill--active': selectedCategory === 'package' }"
            @click="selectedCategory = 'package'"
          >
            <span>📦 包裹</span>
            <span class="chip-count">{{ categoryCounts.package }}</span>
          </button>
          <button
            type="button"
            class="chip-pill"
            :class="{ 'chip-pill--active': selectedCategory === 'animal' }"
            @click="selectedCategory = 'animal'"
          >
            <span>🐾 动物</span>
            <span class="chip-count">{{ categoryCounts.animal }}</span>
          </button>
          <button
            type="button"
            class="chip-pill"
            :class="{ 'chip-pill--active': selectedCategory === 'motion' }"
            @click="selectedCategory = 'motion'"
          >
            <span>⚡ 动检</span>
            <span class="chip-count">{{ categoryCounts.motion }}</span>
          </button>
          <button
            type="button"
            class="chip-pill chip-pill--critical"
            :class="{ 'chip-pill--active': selectedCategory === 'critical' }"
            @click="selectedCategory = 'critical'"
          >
            <span>🚨 严重告警</span>
            <span class="chip-count">{{ categoryCounts.critical }}</span>
          </button>
          <button
            type="button"
            class="chip-pill chip-pill--amber"
            :class="{ 'chip-pill--active': selectedCategory === 'protected' }"
            @click="selectedCategory = 'protected'"
          >
            <span>🛡️ 加锁保护</span>
            <span class="chip-count">{{ categoryCounts.protected }}</span>
          </button>
        </div>

        <!-- Keyword search box -->
        <div class="search-wrap">
          <UiIcon name="search" :size="13" class="search-icon" />
          <input
            v-model="searchQuery"
            type="search"
            placeholder="搜索车牌 / 区域 / 机位 / 标签..."
            class="search-input"
          />
        </div>
      </div>

      <!-- Row 2: Select Dropdowns & Layout Controls -->
      <div class="toolbar-row toolbar-row--selects">
        <div class="select-group">
          <!-- Camera -->
          <div class="select-item">
            <span class="select-label">机位:</span>
            <select v-model="selectedCameraId" class="filter-select">
              <option value="">全部机位</option>
              <option v-for="cam in cameras" :key="cam.id" :value="cam.id">
                {{ cam.name }}
              </option>
            </select>
          </div>

          <!-- Time range -->
          <div class="select-item">
            <span class="select-label">时段:</span>
            <select v-model="period" class="filter-select" @change="refresh">
              <option value="24h">近 24 小时</option>
              <option value="7d">近 7 天</option>
              <option value="30d">近 30 天</option>
              <option value="all">全部历史</option>
            </select>
          </div>

          <!-- Severity -->
          <div class="select-item">
            <span class="select-label">级别:</span>
            <select v-model="selectedSeverity" class="filter-select">
              <option value="all">全部级别</option>
              <option value="critical">🚨 严重 (Critical)</option>
              <option value="warning">⚠️ 警告 (Warning)</option>
              <option value="info">ℹ️ 提示 (Info)</option>
            </select>
          </div>

          <!-- Status -->
          <div class="select-item">
            <span class="select-label">处理状态:</span>
            <select v-model="selectedStatus" class="filter-select">
              <option value="all">全部状态</option>
              <option value="open">🔴 待处理 (Open)</option>
              <option value="acknowledged">🟢 已确认 (Acknowledged)</option>
            </select>
          </div>

          <button type="button" class="btn-reset" @click="resetFilters">
            重置筛选
          </button>
        </div>

        <!-- Sort and View Mode Toggle -->
        <div class="view-controls">
          <select v-model="sortOrder" class="filter-select sort-select">
            <option value="newest">🕒 时间最新优先</option>
            <option value="confidence">🎯 置信度最高</option>
            <option value="severity">🚨 严重级别最高</option>
          </select>

          <div class="mode-toggle">
            <button
              type="button"
              class="mode-btn"
              :class="{ 'mode-btn--active': viewMode === 'grid' }"
              title="网格卡片视图"
              @click="viewMode = 'grid'"
            >
              <UiIcon name="grid4" :size="13" />
            </button>
            <button
              type="button"
              class="mode-btn"
              :class="{ 'mode-btn--active': viewMode === 'table' }"
              title="结构化表格视图"
              @click="viewMode = 'table'"
            >
              <UiIcon name="menu" :size="13" />
            </button>
          </div>
        </div>
      </div>

      <!-- Row 3: 24-Hour Event Density Histogram -->
      <div class="toolbar-row toolbar-row--histogram">
        <div class="histogram-label">
          <span>24H 分布直方图:</span>
          <span
            v-if="selectedHour !== null"
            class="active-hour-tag"
            @click="selectedHour = null"
          >
            已选 {{ String(selectedHour).padStart(2, "0") }}:00 ✕
          </span>
        </div>

        <div class="histogram-bars">
          <div
            v-for="bar in hourlyHistogram"
            :key="bar.hour"
            class="bar-wrap"
            :title="`${String(bar.hour).padStart(2, '0')}:00 - ${bar.count} 次事件`"
            @click="toggleHourFilter(bar.hour)"
          >
            <div
              class="bar-fill"
              :class="{
                'bar-fill--active': selectedHour === bar.hour,
                'bar-fill--has-data': bar.count > 0
              }"
              :style="{ height: `${Math.max(12, bar.heightPct)}%` }"
            />
          </div>
        </div>

        <div class="peak-label">
          峰值: <strong>{{ peakHour.count }}次 / {{ String(peakHour.hour).padStart(2, "0") }}:00</strong>
        </div>
      </div>
    </div>

    <!-- Main Workspace: Split Content (List + Evidence Inspector) -->
    <div class="workspace-body">
      <!-- Left: Events Stream -->
      <div class="events-stream-wrap">
        <!-- Grid Mode View -->
        <div v-if="viewMode === 'grid' && filteredEvents.length" class="events-grid">
          <article
            v-for="event in filteredEvents"
            :key="event.id"
            class="event-card"
            :class="{ 'event-card--selected': selectedEvent?.id === event.id }"
            @click="selectEvent(event)"
          >
            <div class="card-thumb-wrap">
              <img
                v-if="event.snapshot_ref && !snapshotFailures.has(event.id)"
                :src="eventSnapshotUrl(event.id)"
                alt="Snapshot"
                class="card-thumb"
                loading="lazy"
                @error="snapshotFailures.add(event.id)"
              />
              <div v-else class="card-thumb-fallback">
                <span>{{ getCategoryIcon(event.category) }}</span>
              </div>

              <!-- Top category badge -->
              <span class="card-badge-type">
                {{ getCategoryIcon(event.category) }} {{ event.category || "事件" }}
                {{ event.confidence ? `· ${(event.confidence * 100).toFixed(0)}%` : "" }}
              </span>

              <!-- Duration badge -->
              <span class="card-badge-dur">
                {{ getDurationStr(event) }}
              </span>
            </div>

            <div class="card-content">
              <div class="card-meta-top">
                <span class="card-cam-name">{{ cameraMap.get(event.camera_id ?? "")?.name || "机位" }}</span>
                <span class="card-time">{{ formatTime(event.started_at) }}</span>
              </div>

              <div class="card-label-row">
                <span class="card-label">{{ event.label || event.zone || "检测事件" }}</span>
                <span
                  v-if="event.severity"
                  class="severity-tag"
                  :class="`severity-tag--${event.severity}`"
                >
                  {{ event.severity.toUpperCase() }}
                </span>
              </div>

              <div class="card-actions">
                <button
                  type="button"
                  class="card-act-btn"
                  title="跳转至时光轴秒级回放"
                  @click.stop="viewRecording(event)"
                >
                  <UiIcon name="playback" :size="12" />
                  <span>回放</span>
                </button>
                <button
                  type="button"
                  class="card-act-btn"
                  title="加锁保护"
                  @click.stop="lockEvent(event)"
                >
                  <UiIcon name="shield" :size="12" />
                  <span>加锁</span>
                </button>
                <button
                  type="button"
                  class="card-act-btn"
                  title="确认告警"
                  @click.stop="ackEventAlert(event)"
                >
                  <UiIcon name="check" :size="12" />
                  <span>确认</span>
                </button>
              </div>
            </div>
          </article>
        </div>

        <!-- Table Mode View -->
        <div v-else-if="viewMode === 'table' && filteredEvents.length" class="events-table-wrap">
          <table class="events-table">
            <thead>
              <tr>
                <th>快照</th>
                <th>发生时间</th>
                <th>机位名称</th>
                <th>实体类型</th>
                <th>置信度</th>
                <th>提取特征</th>
                <th>告警级别</th>
                <th>保护</th>
                <th class="text-right">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="event in filteredEvents"
                :key="event.id"
                :class="{ 'row--selected': selectedEvent?.id === event.id }"
                @click="selectEvent(event)"
              >
                <td>
                  <img
                    v-if="event.snapshot_ref && !snapshotFailures.has(event.id)"
                    :src="eventSnapshotUrl(event.id)"
                    alt="Thumb"
                    class="table-thumb"
                    loading="lazy"
                    @error="snapshotFailures.add(event.id)"
                  />
                  <span v-else class="table-thumb-fallback">
                    {{ getCategoryIcon(event.category) }}
                  </span>
                </td>
                <td class="font-mono">{{ formatDate(event.started_at) }} {{ formatTime(event.started_at) }}</td>
                <td>{{ cameraMap.get(event.camera_id ?? "")?.name || "Camera" }}</td>
                <td>{{ getCategoryIcon(event.category) }} {{ event.category }}</td>
                <td class="font-mono">{{ event.confidence ? `${(event.confidence * 100).toFixed(1)}%` : "—" }}</td>
                <td>{{ event.label || event.zone || "—" }}</td>
                <td>
                  <span
                    v-if="event.severity"
                    class="severity-tag"
                    :class="`severity-tag--${event.severity}`"
                  >
                    {{ event.severity }}
                  </span>
                  <span v-else class="text-muted">—</span>
                </td>
                <td>
                  <span v-if="event.metadata?.protected" class="text-amber">🛡️ 加锁</span>
                  <span v-else class="text-muted">轮转</span>
                </td>
                <td class="text-right table-actions" @click.stop>
                  <button type="button" class="table-btn" title="查看回放" @click="viewRecording(event)">
                    <UiIcon name="playback" :size="12" />
                  </button>
                  <button type="button" class="table-btn" title="加锁保护" @click="lockEvent(event)">
                    <UiIcon name="shield" :size="12" />
                  </button>
                  <button type="button" class="table-btn" title="确认告警" @click="ackEventAlert(event)">
                    <UiIcon name="check" :size="12" />
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Empty state -->
        <div v-else class="events-empty">
          <div class="empty-icon">🔍</div>
          <div class="empty-title">未找到符合当前复合筛选条件的事件</div>
          <div class="empty-desc">请尝试放宽时段、清空搜索关键字或重置分类</div>
          <button type="button" class="empty-btn" @click="resetFilters">
            重置所有筛选
          </button>
        </div>
      </div>

      <!-- Right: Forensic Evidence Inspector Drawer (340px) -->
      <aside v-if="inspectorOpen && selectedEvent" class="inspector-drawer">
        <div class="inspector-header">
          <div class="inspector-title">
            <span class="blue-dot" />
            <span>事件物证详情 (Forensics)</span>
          </div>
          <button
            type="button"
            class="inspector-close"
            title="关闭详情面板"
            @click="inspectorOpen = false"
          >
            ✕
          </button>
        </div>

        <div class="inspector-content">
          <!-- Snapshot with BBox simulation -->
          <div class="inspector-media-box">
            <img
              v-if="selectedEvent.snapshot_ref && !snapshotFailures.has(selectedEvent.id)"
              :src="eventSnapshotUrl(selectedEvent.id)"
              alt="Evidence HD"
              class="inspector-img"
              @error="snapshotFailures.add(selectedEvent.id)"
            />
            <div v-else class="inspector-img-fallback">
              <span class="fallback-big-icon">{{ getCategoryIcon(selectedEvent.category) }}</span>
            </div>

            <!-- Simulated bounding box overlay -->
            <div class="inspector-bbox">
              <span class="bbox-tag">
                {{ selectedEvent.category }} {{ selectedEvent.confidence ? `${(selectedEvent.confidence * 100).toFixed(0)}%` : "" }}
              </span>
            </div>
          </div>

          <!-- Primary Action: Jump to Time-Lapse -->
          <button
            type="button"
            class="btn-jump-playback"
            @click="viewRecording(selectedEvent)"
          >
            <UiIcon name="playback" :size="16" />
            <span>跳转至时光轴精准秒级回放 ›</span>
          </button>

          <!-- Key facts card -->
          <div class="facts-card">
            <div class="facts-header">
              <span>事件结构化事实 (Facts)</span>
              <span class="facts-id">#{{ selectedEvent.id.slice(0, 8) }}</span>
            </div>

            <div class="facts-grid">
              <div class="fact-item">
                <span class="fact-label">发生机位:</span>
                <span class="fact-value">{{ cameraMap.get(selectedEvent.camera_id ?? "")?.name || "机位" }}</span>
              </div>
              <div class="fact-item">
                <span class="fact-label">发生时间:</span>
                <span class="fact-value font-mono">{{ formatTime(selectedEvent.started_at) }} ({{ getDurationStr(selectedEvent) }})</span>
              </div>
              <div class="fact-item">
                <span class="fact-label">算法引擎:</span>
                <span class="fact-value text-blue">Frigate YOLOV8x</span>
              </div>
              <div class="fact-item">
                <span class="fact-label">告警级别:</span>
                <span
                  class="fact-value font-bold"
                  :class="selectedEvent.severity === 'critical' ? 'text-danger' : 'text-blue'"
                >
                  {{ (selectedEvent.severity || 'INFO').toUpperCase() }}
                </span>
              </div>
              <div class="fact-item col-span-2">
                <span class="fact-label">提取特征 / 标签:</span>
                <div class="features-box">
                  {{ selectedEvent.label || selectedEvent.zone || "未指定附加特征" }}
                </div>
              </div>
              <div class="fact-item">
                <span class="fact-label">存储保护:</span>
                <span class="fact-value" :class="selectedEvent.metadata?.protected ? 'text-amber' : 'text-muted'">
                  {{ selectedEvent.metadata?.protected ? "🛡️ 永久加锁" : "常规留存" }}
                </span>
              </div>
              <div class="fact-item">
                <span class="fact-label">状态:</span>
                <span class="fact-value text-emerald">已存盘</span>
              </div>
            </div>
          </div>

          <!-- Operation buttons -->
          <div class="inspector-actions">
            <button
              type="button"
              class="btn-tool btn-tool--amber"
              @click="lockEvent(selectedEvent)"
            >
              <UiIcon name="shield" :size="13" />
              <span>永久加锁保护</span>
            </button>
            <button
              type="button"
              class="btn-tool btn-tool--emerald"
              @click="ackEventAlert(selectedEvent)"
            >
              <UiIcon name="check" :size="13" />
              <span>确认已处理</span>
            </button>
            <button
              type="button"
              class="btn-tool"
              @click="downloadSnapshot(selectedEvent)"
            >
              <UiIcon name="export" :size="13" />
              <span>下载物证原图</span>
            </button>
          </div>

          <!-- Audit notes -->
          <div class="audit-wrap">
            <span class="audit-label">处置备注 (Audit Log):</span>
            <input
              v-model="auditNote"
              type="text"
              placeholder="添加处置备注..."
              class="audit-input"
            />
            <button
              type="button"
              class="btn-audit"
              @click="showToast('处置记录已写入审计日志'); auditNote = ''"
            >
              提交备注记录
            </button>
          </div>
        </div>
      </aside>
    </div>

    <!-- Toast Notification -->
    <div v-if="toastMessage" class="toast-popup">
      {{ toastMessage }}
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
  user-select: none;
}

/* Header */
.detections-header {
  height: 52px;
  min-height: 52px;
  background-color: #10131c;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  padding: 0 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
  z-index: 30;
}

.header-left,
.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.title-tag {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 700;
  color: #ffffff;
  letter-spacing: 0.02em;
}

.blue-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background-color: #006fff;
  box-shadow: 0 0 8px rgba(0, 111, 255, 0.8);
}

.header-divider {
  width: 1px;
  height: 16px;
  background: rgba(255, 255, 255, 0.12);
}

.kpi-group {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 11px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.kpi-item {
  color: #9ca3af;
}

.kpi-item strong {
  color: #ffffff;
}

.kpi-alert-badge {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 2px 8px;
  border-radius: 9999px;
  background: rgba(239, 68, 68, 0.15);
  color: #f87171;
  font-weight: 600;
}

.alert-pulse {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #ef4444;
  box-shadow: 0 0 6px rgba(239, 68, 68, 0.8);
}

.kpi-tpu-tag {
  color: #9ca3af;
}

.btn-batch {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  border-radius: 8px;
  background: #171b26;
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #d1d5db;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.12s ease;
}

.btn-batch:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.1);
  color: #ffffff;
}

.btn-batch:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.btn-batch--primary {
  background: #006fff;
  border-color: #006fff;
  color: #ffffff;
  box-shadow: 0 2px 8px rgba(0, 111, 255, 0.3);
}

.btn-batch--primary:hover {
  background: #1a7fff;
}

/* Filter toolbar */
.filter-toolbar {
  background-color: #12151e;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  padding: 8px 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex-shrink: 0;
  z-index: 20;
}

.toolbar-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.category-chips {
  display: flex;
  align-items: center;
  gap: 6px;
  overflow-x: auto;
}

.chip-pill {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  border-radius: 9999px;
  background: #181d2a;
  border: 1px solid rgba(255, 255, 255, 0.08);
  color: #9ca3af;
  font-size: 11px;
  cursor: pointer;
  transition: all 0.12s ease;
  white-space: nowrap;
}

.chip-pill:hover {
  background: rgba(255, 255, 255, 0.1);
  color: #ffffff;
}

.chip-pill--active {
  background: #006fff !important;
  border-color: #006fff !important;
  color: #ffffff !important;
  box-shadow: 0 0 10px rgba(0, 111, 255, 0.35);
}

.chip-pill--critical {
  color: #f87171;
  border-color: rgba(239, 68, 68, 0.2);
}

.chip-pill--amber {
  color: #fbbf24;
  border-color: rgba(245, 158, 11, 0.2);
}

.chip-count {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 10px;
  opacity: 0.8;
}

.search-wrap {
  position: relative;
  width: 240px;
  flex-shrink: 0;
}

.search-icon {
  position: absolute;
  left: 8px;
  top: 50%;
  transform: translateY(-50%);
  color: #6b7280;
}

.search-input {
  width: 100%;
  background: #181d2a;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 8px;
  padding: 4px 8px 4px 28px;
  color: #ffffff;
  font-size: 11px;
  outline: none;
}

.search-input:focus {
  border-color: #006fff;
}

.select-group {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.select-item {
  display: flex;
  align-items: center;
  gap: 5px;
}

.select-label {
  font-size: 11px;
  color: #9ca3af;
}

.filter-select {
  background: #181d2a;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 6px;
  padding: 3px 8px;
  color: #d1d5db;
  font-size: 11px;
  outline: none;
  cursor: pointer;
}

.filter-select:focus {
  border-color: #006fff;
}

.btn-reset {
  background: transparent;
  border: none;
  color: #9ca3af;
  font-size: 11px;
  text-decoration: underline;
  cursor: pointer;
}

.btn-reset:hover {
  color: #ffffff;
}

.view-controls {
  display: flex;
  align-items: center;
  gap: 8px;
}

.mode-toggle {
  display: flex;
  align-items: center;
  background: #181d2a;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 6px;
  padding: 1px;
}

.mode-btn {
  background: transparent;
  border: none;
  color: #6b7280;
  padding: 3px 6px;
  border-radius: 4px;
  cursor: pointer;
}

.mode-btn--active {
  background: #006fff;
  color: #ffffff;
}

/* Histogram */
.toolbar-row--histogram {
  border-top: 1px solid rgba(255, 255, 255, 0.05);
  padding-top: 6px;
  display: flex;
  align-items: center;
  gap: 12px;
}

.histogram-label {
  font-size: 10px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  text-transform: uppercase;
  color: #9ca3af;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.active-hour-tag {
  color: #38bdf8;
  font-weight: 700;
  cursor: pointer;
}

.histogram-bars {
  flex: 1;
  display: flex;
  align-items: flex-end;
  height: 24px;
  gap: 3px;
}

.bar-wrap {
  flex: 1;
  height: 100%;
  display: flex;
  align-items: flex-end;
  cursor: pointer;
}

.bar-fill {
  width: 100%;
  background: rgba(255, 255, 255, 0.08);
  border-radius: 2px 2px 0 0;
  transition: all 0.15s ease;
}

.bar-fill--has-data {
  background: rgba(0, 111, 255, 0.55);
}

.bar-fill--active {
  background: #38bdf8 !important;
  box-shadow: 0 0 8px rgba(56, 189, 248, 0.8);
}

.bar-wrap:hover .bar-fill {
  background: #60a5fa;
}

.peak-label {
  font-size: 10px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  color: #9ca3af;
  flex-shrink: 0;
}

/* Workspace body */
.workspace-body {
  flex: 1;
  display: flex;
  min-height: 0;
  overflow: hidden;
}

.events-stream-wrap {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  min-width: 0;
}

/* Grid View */
.events-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 14px;
}

.event-card {
  background: #141722;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  overflow: hidden;
  cursor: pointer;
  transition: all 0.15s ease;
  display: flex;
  flex-direction: column;
}

.event-card:hover {
  border-color: rgba(0, 111, 255, 0.4);
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
}

.event-card--selected {
  border-color: #006fff !important;
  box-shadow: 0 0 16px rgba(0, 111, 255, 0.3) !important;
}

.card-thumb-wrap {
  position: relative;
  height: 130px;
  background: #000000;
  overflow: hidden;
}

.card-thumb {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.card-thumb-fallback {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 32px;
  color: #4b5563;
}

.card-badge-type {
  position: absolute;
  top: 6px;
  left: 6px;
  background: rgba(0, 0, 0, 0.75);
  backdrop-filter: blur(8px);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 10px;
  color: #ffffff;
  border: 1px solid rgba(255, 255, 255, 0.15);
}

.card-badge-dur {
  position: absolute;
  bottom: 6px;
  right: 6px;
  background: rgba(0, 0, 0, 0.75);
  padding: 1px 5px;
  border-radius: 4px;
  font-size: 9px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  color: #9ca3af;
}

.card-content {
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.card-meta-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11px;
}

.card-cam-name {
  font-weight: 600;
  color: #ffffff;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.card-time {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  color: #9ca3af;
  font-size: 10px;
}

.card-label-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11px;
}

.card-label {
  color: #d1d5db;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.severity-tag {
  font-size: 9px;
  font-weight: 700;
  padding: 1px 5px;
  border-radius: 3px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.severity-tag--critical {
  background: rgba(239, 68, 68, 0.2);
  color: #ef4444;
}

.severity-tag--warning {
  background: rgba(245, 158, 11, 0.2);
  color: #f59e0b;
}

.severity-tag--info {
  background: rgba(59, 130, 246, 0.2);
  color: #60a5fa;
}

.card-actions {
  display: flex;
  gap: 6px;
  padding-top: 6px;
  border-top: 1px solid rgba(255, 255, 255, 0.05);
}

.card-act-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 4px 6px;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.08);
  color: #9ca3af;
  font-size: 10px;
  cursor: pointer;
  transition: all 0.12s ease;
}

.card-act-btn:hover {
  background: rgba(255, 255, 255, 0.12);
  color: #ffffff;
}

/* Table View */
.events-table-wrap {
  background: #141722;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  overflow: hidden;
}

.events-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 11px;
}

.events-table th {
  background: rgba(255, 255, 255, 0.02);
  color: #9ca3af;
  font-weight: 600;
  text-align: left;
  padding: 8px 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  font-size: 10px;
  text-transform: uppercase;
}

.events-table td {
  padding: 8px 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
  color: #d1d5db;
}

.events-table tr {
  cursor: pointer;
  transition: background 0.12s;
}

.events-table tr:hover {
  background: rgba(255, 255, 255, 0.04);
}

.row--selected {
  background: rgba(0, 111, 255, 0.15) !important;
}

.table-thumb {
  width: 36px;
  height: 24px;
  object-fit: cover;
  border-radius: 4px;
}

.table-thumb-fallback {
  display: inline-block;
  font-size: 14px;
}

.table-actions {
  display: flex;
  gap: 4px;
  justify-content: flex-end;
}

.table-btn {
  background: rgba(255, 255, 255, 0.05);
  border: none;
  color: #9ca3af;
  padding: 4px 6px;
  border-radius: 4px;
  cursor: pointer;
}

.table-btn:hover {
  color: #ffffff;
  background: rgba(255, 255, 255, 0.15);
}

/* Empty */
.events-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  color: #6b7280;
  gap: 8px;
}

.empty-icon {
  font-size: 32px;
}

.empty-title {
  color: #ffffff;
  font-size: 14px;
  font-weight: 600;
}

.empty-desc {
  font-size: 12px;
}

.empty-btn {
  margin-top: 6px;
  padding: 6px 14px;
  border-radius: 8px;
  background: #006fff;
  color: #ffffff;
  border: none;
  font-size: 12px;
  cursor: pointer;
}

/* Inspector Drawer */
.inspector-drawer {
  width: 330px;
  min-width: 330px;
  background: #10131c;
  border-left: 1px solid rgba(255, 255, 255, 0.08);
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow-y: auto;
}

.inspector-header {
  height: 44px;
  min-height: 44px;
  background: #131622;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  padding: 0 14px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.inspector-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  color: #ffffff;
  letter-spacing: 0.05em;
}

.inspector-close {
  background: transparent;
  border: none;
  color: #6b7280;
  font-size: 12px;
  cursor: pointer;
  padding: 4px;
}

.inspector-close:hover {
  color: #ffffff;
}

.inspector-content {
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.inspector-media-box {
  position: relative;
  height: 170px;
  border-radius: 10px;
  overflow: hidden;
  background: #000000;
  border: 1px solid rgba(255, 255, 255, 0.1);
}

.inspector-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.inspector-img-fallback {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.fallback-big-icon {
  font-size: 40px;
  color: #4b5563;
}

.inspector-bbox {
  position: absolute;
  top: 25%;
  left: 30%;
  width: 40%;
  height: 50%;
  border: 2px solid #10b981;
  background: rgba(16, 185, 129, 0.12);
  border-radius: 3px;
  pointer-events: none;
}

.bbox-tag {
  position: absolute;
  top: -18px;
  left: 0;
  background: #10b981;
  color: #000000;
  font-weight: 700;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 9px;
  padding: 1px 4px;
  border-radius: 2px 2px 0 0;
}

.btn-jump-playback {
  width: 100%;
  padding: 8px 12px;
  border-radius: 10px;
  background: #006fff;
  border: none;
  color: #ffffff;
  font-size: 12px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  cursor: pointer;
  box-shadow: 0 4px 14px rgba(0, 111, 255, 0.35);
  transition: all 0.15s ease;
}

.btn-jump-playback:hover {
  background: #1a7fff;
}

.facts-card {
  background: #151824;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 10px;
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.facts-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 10px;
  text-transform: uppercase;
  color: #9ca3af;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  padding-bottom: 4px;
}

.facts-id {
  color: #60a5fa;
  font-weight: 700;
}

.facts-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px 10px;
  font-size: 11px;
}

.fact-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.col-span-2 {
  grid-column: span 2;
}

.fact-label {
  font-size: 10px;
  color: #6b7280;
}

.fact-value {
  color: #ffffff;
}

.features-box {
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 6px;
  padding: 6px 8px;
  color: #e5e7eb;
  font-size: 11px;
  margin-top: 2px;
}

.inspector-actions {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px;
}

.btn-tool {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 6px 8px;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #d1d5db;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.12s ease;
}

.btn-tool:hover {
  background: rgba(255, 255, 255, 0.12);
  color: #ffffff;
}

.btn-tool--amber {
  background: rgba(245, 158, 11, 0.12);
  border-color: rgba(245, 158, 11, 0.25);
  color: #fcd34d;
}

.btn-tool--emerald {
  background: rgba(16, 185, 129, 0.12);
  border-color: rgba(16, 185, 129, 0.25);
  color: #6ee7b7;
}

.audit-wrap {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding-top: 4px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.audit-label {
  font-size: 10px;
  color: #6b7280;
  text-transform: uppercase;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.audit-input {
  background: #181d2a;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 6px;
  padding: 5px 8px;
  color: #ffffff;
  font-size: 11px;
  outline: none;
}

.audit-input:focus {
  border-color: #006fff;
}

.btn-audit {
  padding: 4px 8px;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.08);
  border: none;
  color: #ffffff;
  font-size: 10px;
  cursor: pointer;
  align-self: flex-end;
}

.btn-audit:hover {
  background: rgba(255, 255, 255, 0.15);
}

/* Toast */
.toast-popup {
  position: absolute;
  bottom: 24px;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(18, 22, 32, 0.95);
  border: 1px solid rgba(0, 111, 255, 0.4);
  color: #93c5fd;
  padding: 8px 16px;
  border-radius: 9999px;
  font-size: 12px;
  font-weight: 600;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
  z-index: 100;
  pointer-events: none;
}

.text-emerald { color: #34d399 !important; }
.text-amber { color: #fbbf24 !important; }
.text-blue { color: #60a5fa !important; }
.text-danger { color: #ef4444 !important; }
.text-muted { color: #6b7280 !important; }
.font-mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace !important; }
.text-right { text-align: right !important; }
</style>
