<script setup lang="ts">
/**
 * RecordingScheduleView.vue - Recording Schedules & Weekly Plan Matrix
 * 集中管理所有摄像头的 24×7 自动录像、时间窗口与分段周计划矩阵
 *
 * 功能对齐 camera-recorder 并融入 UniFi Protect 现代化设计语言：
 * 1. 顶部调度中心看板：调度器运行状态指示、全网录像模式结构统计芯片 (全天 / 周计划 / 仅动检 / 停用)；
 * 2. 批量与多维操作栏：多选批处理计数、按机位与状态即时检索、全局一键刷新与批量应用模态框；
 * 3. 现代化数据矩阵表：机位形态徽标、名称/IP、录像策略徽标、周计划可视化 Pills、存储池/切片配置、实时录制状态与配置入口；
 * 4. 专业级周计划编辑抽屉/模态框 (支持单机位 & 批量应用)：
 *    - 录制策略模式卡片 (全天自动录像 / 自定义周计划 / 仅动检 / 停用)；
 *    - 计划预设模板 (24×7 全天、工作日白天、夜间安防跨午夜、周末特权等)；
 *    - 多时间窗口列表 (生效星期 Pills、起止时间 Picker、跨午夜次日结束检测、持续时长动态换算、添加/删除时段)；
 *    - 高级录像配置 (存储目标池、留存策略、分段切片时长 60s-900s、预录/延录秒数、时区)。
 */

import { computed, onMounted, reactive, ref } from "vue"
import { useRouter } from "vue-router"
import { useI18n } from "vue-i18n"

import {
  listCameras,
  type CameraSummary
} from "../api/cameras"
import { errorMessage } from "../api/client"
import {
  getRecordingPolicy,
  listRecordingPolicies,
  putRecordingPolicy,
  type RecordingPolicy,
  type RecordingPolicyPut,
  type RecordingScheduleWindow
} from "../api/recordings"
import {
  listRetentionPolicies,
  listStorageTargets,
  type RetentionPolicy,
  type StorageTarget
} from "../api/storage"
import CameraDeviceGlyph from "../components/cameras/CameraDeviceGlyph.vue"
import UiIcon from "../components/ui/UiIcon.vue"
import { useAuthStore } from "../stores/auth"

interface WeekdayOption {
  value: number
  label: string
  short: string
}

const ALL_DAYS = [0, 1, 2, 3, 4, 5, 6]
const WORK_DAYS = [0, 1, 2, 3, 4]
const WEEKEND = [5, 6]

const WEEKDAY_OPTIONS: WeekdayOption[] = [
  { value: 0, label: "周一", short: "一" },
  { value: 1, label: "周二", short: "二" },
  { value: 2, label: "周三", short: "三" },
  { value: 3, label: "周四", short: "四" },
  { value: 4, label: "周五", short: "五" },
  { value: 5, label: "周六", short: "六" },
  { value: 6, label: "周日", short: "日" }
]

type PolicyFilterMode = "all" | "continuous" | "schedule" | "events" | "disabled"

const router = useRouter()
const auth = useAuthStore()
const { t } = useI18n({ useScope: "global" })

// State: Cameras & Policies
const cameras = ref<CameraSummary[]>([])
const policiesMap = ref<Map<string, RecordingPolicy>>(new Map())
const storageTargets = ref<StorageTarget[]>([])
const retentionPolicies = ref<RetentionPolicy[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const toastMessage = ref<string | null>(null)

// Selection & Filter State
const selectedCameraIds = ref<string[]>([])
const searchQuery = ref("")
const filterMode = ref<PolicyFilterMode>("all")

// Dialog / Drawer State
const dialogVisible = ref(false)
const dialogMode = ref<"single" | "batch">("single")
const editingCamera = ref<CameraSummary | null>(null)
const saving = ref(false)
const dialogError = ref<string | null>(null)

// Form State for Dialog
const editForm = reactive({
  name: "",
  mode: "continuous" as "continuous" | "schedule" | "events" | "disabled",
  windows: [] as RecordingScheduleWindow[],
  timezone: "UTC",
  segmentSeconds: 300,
  preRoll: 10,
  postRoll: 10,
  storageTargetId: "",
  retentionPolicyId: "",
  showAdvanced: false
})

function showToast(msg: string): void {
  toastMessage.value = msg
  setTimeout(() => {
    if (toastMessage.value === msg) toastMessage.value = null
  }, 4000)
}

function normalizedDays(days?: number[]): number[] {
  if (!days?.length) return [...ALL_DAYS]
  return [...new Set(days)].sort((a, b) => a - b)
}

function cloneWindows(windows?: RecordingScheduleWindow[]): RecordingScheduleWindow[] {
  return (windows || []).map((w) => ({
    days: normalizedDays(w.days),
    start: w.start,
    end: w.end
  }))
}

function sameDays(days: number[] | undefined, target: number[]): boolean {
  return normalizedDays(days).join(",") === target.join(",")
}

function dayLabel(days?: number[]): string {
  const norm = normalizedDays(days)
  if (norm.join(",") === ALL_DAYS.join(",")) return "每天"
  if (norm.join(",") === WORK_DAYS.join(",")) return "工作日 (周一至周五)"
  if (norm.join(",") === WEEKEND.join(",")) return "周末 (周六/周日)"
  return norm.map((d) => WEEKDAY_OPTIONS.find((opt) => opt.value === d)?.short || `${d}`).join("、")
}

function crossesMidnight(window: RecordingScheduleWindow): boolean {
  return Boolean(window.start && window.end && window.start > window.end)
}

function windowDurationLabel(window: RecordingScheduleWindow): string {
  const parse = (v: string): number | null => {
    const [h, m] = v.split(":").map(Number)
    return Number.isFinite(h) && Number.isFinite(m) ? h * 60 + m : null
  }
  const start = parse(window.start)
  const end = parse(window.end)
  if (start === null || end === null || start === end) return "—"
  let diff = end - start
  if (diff < 0) diff += 24 * 60
  const hours = Math.floor(diff / 60)
  const minutes = diff % 60
  if (!hours) return `${minutes} 分钟`
  return `${hours} 小时${minutes ? ` ${minutes} 分` : ""}`
}

function getCameraPolicy(cameraId: string): RecordingPolicy | undefined {
  return policiesMap.value.get(cameraId)
}

function getCameraEffectiveMode(camera: CameraSummary): "continuous" | "schedule" | "events" | "disabled" {
  const p = getCameraPolicy(camera.id)
  if (!p || !p.enabled) return "disabled"
  if (p.baseline_mode === "schedule") return "schedule"
  if (p.baseline_mode === "continuous") return "continuous"
  if (p.event_recording_enabled) return "events"
  return "disabled"
}

function getScheduleSummaryText(camera: CameraSummary): string {
  const p = getCameraPolicy(camera.id)
  if (!p || !p.enabled) return "未启用自动录像 (仅手动)"
  if (p.baseline_mode === "continuous") return "24×7 全天录像 (时钟对齐)"
  if (p.baseline_mode === "disabled") {
    return p.event_recording_enabled ? "仅动检与 AI 目标事件触发录像" : "已关闭录像"
  }
  const weekly = p.schedule?.weekly || []
  if (!weekly.length) return "周计划已启用 · 未配置时段"
  return weekly
    .map((w) => `${dayLabel(w.days)} ${w.start}-${w.end}${crossesMidnight(w) ? " (次日)" : ""}`)
    .join("；")
}

function isDayActiveInSchedule(camera: CameraSummary, dayIndex: number): boolean {
  const p = getCameraPolicy(camera.id)
  if (!p || !p.enabled) return false
  if (p.baseline_mode === "continuous") return true
  if (p.baseline_mode !== "schedule") return false
  const weekly = p.schedule?.weekly || []
  return weekly.some((w) => normalizedDays(w.days).includes(dayIndex))
}

function getRuntimeStateInfo(camera: CameraSummary): { label: string; tone: "ok" | "standby" | "off" | "warn" } {
  if (!camera.enabled) return { label: "机位已禁用", tone: "off" }
  if (camera.connectivity_status === "offline") return { label: "机位离线 (等待连接)", tone: "warn" }
  const p = getCameraPolicy(camera.id)
  if (!p || !p.enabled) return { label: "仅手动录像", tone: "off" }

  // 1. Explicitly confirmed recording
  if (p.runtime?.recording) {
    return { label: "正在录制", tone: "ok" }
  }

  // 2. 24x7 Continuous mode
  if (p.baseline_mode === "continuous") {
    if (camera.connectivity_status === "online") {
      return { label: "全天录制中", tone: "ok" }
    }
    return { label: "等待机位上线", tone: "standby" }
  }

  // 3. Weekly Schedule mode (calculate active window)
  if (p.baseline_mode === "schedule") {
    const now = new Date()
    const currentDay = (now.getDay() + 6) % 7 // 0=Mon, ..., 6=Sun
    const currentMinutes = now.getHours() * 60 + now.getMinutes()
    const windows = p.schedule?.weekly || []

    const inWindow = windows.some((w) => {
      if (!normalizedDays(w.days).includes(currentDay)) return false
      const [sh, sm] = w.start.split(":").map(Number)
      const [eh, em] = w.end.split(":").map(Number)
      if (!Number.isFinite(sh) || !Number.isFinite(eh)) return false
      const s = sh * 60 + sm
      const e = eh * 60 + em
      if (s <= e) {
        return currentMinutes >= s && currentMinutes < e
      } else {
        // Crosses midnight
        return currentMinutes >= s || currentMinutes < e
      }
    })

    if (inWindow) {
      if (camera.connectivity_status === "online") {
        return { label: "时段内录制中", tone: "ok" }
      }
      return { label: "时段内等待上线", tone: "standby" }
    }
    return { label: "时段外待机", tone: "standby" }
  }

  // 4. Motion / Event only
  if (p.event_recording_enabled) {
    return { label: "动检监听待命中", tone: "standby" }
  }

  return { label: "未启用", tone: "off" }
}

function getStorageTargetLabel(targetId: string | null | undefined): string {
  if (!targetId) return "默认存储池"
  const found = storageTargets.value.find((t) => t.id === targetId)
  return found ? found.name : "未指定"
}

// Filtered Cameras
const filteredCameras = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()
  return cameras.value.filter((cam) => {
    if (query) {
      const matchName = cam.name.toLowerCase().includes(query)
      const matchIp = (cam.ip || "").toLowerCase().includes(query)
      const matchLoc = (cam.location || "").toLowerCase().includes(query)
      if (!matchName && !matchIp && !matchLoc) return false
    }
    if (filterMode.value !== "all") {
      const eff = getCameraEffectiveMode(cam)
      if (eff !== filterMode.value) return false
    }
    return true
  })
})

// Statistics Metrics
const stats = computed(() => {
  const total = cameras.value.length
  let continuous = 0
  let scheduled = 0
  let events = 0
  let disabled = 0

  for (const c of cameras.value) {
    const mode = getCameraEffectiveMode(c)
    if (mode === "continuous") continuous++
    else if (mode === "schedule") scheduled++
    else if (mode === "events") events++
    else disabled++
  }

  return { total, continuous, scheduled, events, disabled }
})

// Selection
const allSelected = computed(() => {
  return (
    filteredCameras.value.length > 0 &&
    filteredCameras.value.every((c) => selectedCameraIds.value.includes(c.id))
  )
})

function toggleSelectAll(): void {
  if (allSelected.value) {
    selectedCameraIds.value = []
  } else {
    selectedCameraIds.value = filteredCameras.value.map((c) => c.id)
  }
}

function toggleSelectCamera(cameraId: string): void {
  const idx = selectedCameraIds.value.indexOf(cameraId)
  if (idx >= 0) {
    selectedCameraIds.value.splice(idx, 1)
  } else {
    selectedCameraIds.value.push(cameraId)
  }
}

// Data loading
async function loadData(force = false): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const [cams, targets, retentions, policies] = await Promise.all([
      listCameras(),
      listStorageTargets().catch(() => [] as StorageTarget[]),
      listRetentionPolicies().catch(() => [] as RetentionPolicy[]),
      listRecordingPolicies().catch(() => [] as RecordingPolicy[])
    ])
    cameras.value = cams
    storageTargets.value = targets
    retentionPolicies.value = retentions

    const nextMap = new Map<string, RecordingPolicy>()
    for (const p of policies) {
      nextMap.set(p.camera_id, p)
    }
    policiesMap.value = nextMap

    // If any policy was missing from list endpoint, fetch individually
    const missing = cams.filter((c) => !nextMap.has(c.id))
    if (missing.length > 0 && missing.length <= 16) {
      await Promise.allSettled(
        missing.map(async (c) => {
          try {
            const p = await getRecordingPolicy(c.id)
            nextMap.set(c.id, p)
          } catch {
            // not configured yet
          }
        })
      )
      policiesMap.value = new Map(nextMap)
    }

    if (force) {
      showToast("机位录制计划数据已更新")
    }
  } catch (caught) {
    error.value = `加载计划失败: ${errorMessage(caught)}`
  } finally {
    loading.value = false
  }
}

// Dialog Handlers
function openSingleDialog(camera: CameraSummary): void {
  dialogMode.value = "single"
  editingCamera.value = camera
  dialogError.value = null

  const p = getCameraPolicy(camera.id)
  editForm.name = camera.name
  if (!p || !p.enabled) {
    editForm.mode = "continuous"
    editForm.windows = [{ days: [...WORK_DAYS], start: "08:00", end: "18:00" }]
    editForm.timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"
    editForm.segmentSeconds = 300
    editForm.preRoll = 10
    editForm.postRoll = 10
    editForm.storageTargetId = ""
    editForm.retentionPolicyId = ""
  } else {
    if (p.baseline_mode === "schedule") editForm.mode = "schedule"
    else if (p.baseline_mode === "continuous") editForm.mode = "continuous"
    else if (p.event_recording_enabled) editForm.mode = "events"
    else editForm.mode = "disabled"

    editForm.windows = p.schedule?.weekly?.length
      ? cloneWindows(p.schedule.weekly)
      : [{ days: [...WORK_DAYS], start: "08:00", end: "18:00" }]
    editForm.timezone = p.schedule_timezone || Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"
    editForm.segmentSeconds = p.segment_target_seconds || 300
    editForm.preRoll = p.pre_roll_seconds || 10
    editForm.postRoll = p.post_roll_seconds || 10
    editForm.storageTargetId = p.storage_target_id || ""
    editForm.retentionPolicyId = p.retention_policy_id || ""
  }

  editForm.showAdvanced = false
  dialogVisible.value = true
}

function openBatchDialog(): void {
  if (!selectedCameraIds.value.length) {
    showToast("请先在列表中勾选要批量配置的机位")
    return
  }
  dialogMode.value = "batch"
  editingCamera.value = null
  dialogError.value = null

  // Use the first selected camera's policy as reference if present
  const firstId = selectedCameraIds.value[0]
  const p = getCameraPolicy(firstId)
  if (p && p.enabled) {
    if (p.baseline_mode === "schedule") editForm.mode = "schedule"
    else if (p.baseline_mode === "continuous") editForm.mode = "continuous"
    else if (p.event_recording_enabled) editForm.mode = "events"
    else editForm.mode = "disabled"

    editForm.windows = p.schedule?.weekly?.length
      ? cloneWindows(p.schedule.weekly)
      : [{ days: [...WORK_DAYS], start: "08:00", end: "18:00" }]
    editForm.timezone = p.schedule_timezone || Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"
    editForm.segmentSeconds = p.segment_target_seconds || 300
    editForm.preRoll = p.pre_roll_seconds || 10
    editForm.postRoll = p.post_roll_seconds || 10
    editForm.storageTargetId = p.storage_target_id || ""
    editForm.retentionPolicyId = p.retention_policy_id || ""
  } else {
    editForm.mode = "continuous"
    editForm.windows = [{ days: [...WORK_DAYS], start: "08:00", end: "18:00" }]
    editForm.timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"
    editForm.segmentSeconds = 300
    editForm.preRoll = 10
    editForm.postRoll = 10
    editForm.storageTargetId = ""
    editForm.retentionPolicyId = ""
  }

  editForm.showAdvanced = false
  dialogVisible.value = true
}

// Window Operations
function addWindow(): void {
  editForm.windows.push({
    days: [...ALL_DAYS],
    start: "08:00",
    end: "18:00"
  })
}

function removeWindow(index: number): void {
  editForm.windows.splice(index, 1)
}

function setWindowPresetDays(index: number, days: number[]): void {
  editForm.windows[index].days = [...days]
}

function toggleWindowDay(index: number, day: number): void {
  const current = editForm.windows[index].days
  editForm.windows[index].days = current.includes(day)
    ? current.filter((d) => d !== day)
    : [...current, day].sort((a, b) => a - b)
}

// Presets
function applySchedulePreset(preset: "all_day" | "workdays" | "night" | "weekend_plus"): void {
  if (preset === "all_day") {
    editForm.windows = [{ days: [...ALL_DAYS], start: "00:00", end: "23:59" }]
  } else if (preset === "workdays") {
    editForm.windows = [{ days: [...WORK_DAYS], start: "08:00", end: "18:00" }]
  } else if (preset === "night") {
    editForm.windows = [{ days: [...ALL_DAYS], start: "20:00", end: "08:00" }]
  } else if (preset === "weekend_plus") {
    editForm.windows = [
      { days: [...WORK_DAYS], start: "18:00", end: "08:00" },
      { days: [...WEEKEND], start: "00:00", end: "23:59" }
    ]
  }
}

function validateWindows(): boolean {
  if (editForm.mode !== "schedule") return true
  if (!editForm.windows.length) {
    dialogError.value = "自定义周计划模式下至少需要添加一个时间段"
    return false
  }
  for (let i = 0; i < editForm.windows.length; i++) {
    const w = editForm.windows[i]
    if (!w.days.length) {
      dialogError.value = `时间段 ${i + 1} 至少需要选择一个星期`
      return false
    }
    if (!w.start || !w.end) {
      dialogError.value = `请完整填写时间段 ${i + 1} 的开始与结束时间`
      return false
    }
    if (w.start === w.end) {
      dialogError.value = `时间段 ${i + 1} 的开始与结束时间不能相同（如需全天录制请选择“全天自动录像”）`
      return false
    }
  }
  return true
}

function buildPolicyPayload(): RecordingPolicyPut {
  const mode = editForm.mode
  const isEnabled = mode !== "disabled"
  const isContinuous = mode === "continuous"
  const isSchedule = mode === "schedule"
  const isEvents = mode === "events"

  const baselineMode: "continuous" | "schedule" | "disabled" = isContinuous
    ? "continuous"
    : isSchedule
      ? "schedule"
      : "disabled"

  return {
    baseline_mode: baselineMode,
    enabled: isEnabled,
    event_recording_enabled: isEvents,
    schedule: isSchedule ? { weekly: cloneWindows(editForm.windows) } : {},
    schedule_timezone: isSchedule ? editForm.timezone : null,
    segment_target_seconds: editForm.segmentSeconds,
    pre_roll_seconds: editForm.preRoll,
    post_roll_seconds: editForm.postRoll,
    storage_target_id: editForm.storageTargetId || null,
    retention_policy_id: editForm.retentionPolicyId || null,
    event_filter: {
      labels: [],
      zones: [],
      min_confidence: 0.6
    }
  }
}

async function savePlan(): Promise<void> {
  dialogError.value = null
  if (!validateWindows()) return

  saving.value = true
  const payload = buildPolicyPayload()

  try {
    if (dialogMode.value === "single" && editingCamera.value) {
      const res = await putRecordingPolicy(editingCamera.value.id, payload)
      policiesMap.value.set(editingCamera.value.id, res)
      showToast(`机位 [${editingCamera.value.name}] 录制计划已生效`)
    } else if (dialogMode.value === "batch" && selectedCameraIds.value.length) {
      const targets = [...selectedCameraIds.value]
      let succeedCount = 0
      const errors: string[] = []

      await Promise.allSettled(
        targets.map(async (camId) => {
          try {
            const res = await putRecordingPolicy(camId, payload)
            policiesMap.value.set(camId, res)
            succeedCount++
          } catch (caught) {
            const name = cameras.value.find((c) => c.id === camId)?.name || camId
            errors.push(`${name}: ${errorMessage(caught)}`)
          }
        })
      )

      if (errors.length === 0) {
        showToast(`已成功将录制计划批量应用到全部 ${succeedCount} 路机位`)
      } else {
        showToast(`已应用 ${succeedCount} 路机位，${errors.length} 路保存失败`)
      }
    }

    dialogVisible.value = false
    await loadData(false)
  } catch (caught) {
    dialogError.value = `保存失败: ${errorMessage(caught)}`
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  void loadData(false)
})
</script>

<template>
  <div class="schedule-view">
    <!-- Toast Message -->
    <div v-if="toastMessage" class="schedule-toast">
      <UiIcon name="check" :size="16" />
      <span>{{ toastMessage }}</span>
    </div>

    <!-- Header Block -->
    <header class="schedule-header">
      <div class="schedule-header__info">
        <div class="schedule-header__brand">
          <div class="brand-badge">
            <svg width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24">
              <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
              <line x1="16" y1="2" x2="16" y2="6" />
              <line x1="8" y1="2" x2="8" y2="6" />
              <line x1="3" y1="10" x2="21" y2="10" />
              <path d="M8 14h.01M12 14h.01M16 14h.01M8 18h.01M12 18h.01M16 18h.01" />
            </svg>
          </div>
          <div>
            <h1 class="schedule-title">录像录制计划 (Recording Schedules)</h1>
            <p class="schedule-subtitle">集中管理全网机位 24×7 自动录像、跨午夜分段周计划与动检策略</p>
          </div>
        </div>
      </div>

      <div class="schedule-header__actions">
        <div class="scheduler-pill" title="自动调度引擎正常工作">
          <span class="status-indicator-dot ok"></span>
          <span>调度器运行中</span>
        </div>

        <button
          type="button"
          class="btn-action btn-action--ghost"
          :disabled="loading"
          title="刷新录像计划列表"
          @click="loadData(true)"
        >
          <UiIcon name="refresh" :size="14" :class="{ 'animate-spin': loading }" />
          <span>{{ loading ? '刷新中...' : '刷新' }}</span>
        </button>

        <button
          v-if="auth.hasPermission('camera.configure')"
          type="button"
          class="btn-action btn-action--primary"
          :disabled="!selectedCameraIds.length"
          :title="selectedCameraIds.length ? `批量应用计划到已选中的 ${selectedCameraIds.length} 路机位` : '请先勾选下方机位'"
          @click="openBatchDialog"
        >
          <UiIcon name="sliders" :size="14" />
          <span>批量应用周计划 {{ selectedCameraIds.length ? `(${selectedCameraIds.length})` : '' }}</span>
        </button>
      </div>
    </header>

    <!-- Error Alert Banner -->
    <div v-if="error" class="alert-banner alert-banner--error">
      <UiIcon name="warning" :size="16" />
      <span>{{ error }}</span>
    </div>

    <!-- Quick Stats Cards (Overview) -->
    <section class="stats-row">
      <div class="stat-card" :class="{ active: filterMode === 'all' }" @click="filterMode = 'all'">
        <div class="stat-card__val">{{ stats.total }}</div>
        <div class="stat-card__lbl">全部机位</div>
      </div>
      <div class="stat-card" :class="{ active: filterMode === 'continuous' }" @click="filterMode = 'continuous'">
        <div class="stat-card__val text-continuous">{{ stats.continuous }}</div>
        <div class="stat-card__lbl">全天自动录像 (24×7)</div>
      </div>
      <div class="stat-card" :class="{ active: filterMode === 'schedule' }" @click="filterMode = 'schedule'">
        <div class="stat-card__val text-schedule">{{ stats.scheduled }}</div>
        <div class="stat-card__lbl">自定义周计划</div>
      </div>
      <div class="stat-card" :class="{ active: filterMode === 'events' }" @click="filterMode = 'events'">
        <div class="stat-card__val text-events">{{ stats.events }}</div>
        <div class="stat-card__lbl">动检事件录像</div>
      </div>
      <div class="stat-card" :class="{ active: filterMode === 'disabled' }" @click="filterMode = 'disabled'">
        <div class="stat-card__val text-disabled">{{ stats.disabled }}</div>
        <div class="stat-card__lbl">停用 / 仅手动</div>
      </div>
    </section>

    <!-- Filter & Search Toolbar -->
    <div class="toolbar">
      <div class="toolbar__search">
        <UiIcon name="search" :size="15" class="search-icon" />
        <input
          v-model="searchQuery"
          type="text"
          class="search-input"
          placeholder="搜索机位名称、IP 地址或安装位置..."
        />
        <button
          v-if="searchQuery"
          type="button"
          class="search-clear"
          @click="searchQuery = ''"
        >
          <UiIcon name="x" :size="13" />
        </button>
      </div>

      <div class="toolbar__selection-info">
        <span v-if="selectedCameraIds.length">
          已选择 <strong>{{ selectedCameraIds.length }}</strong> / {{ filteredCameras.length }} 路机位
        </span>
        <span v-else class="text-muted">
          共 {{ filteredCameras.length }} 路机位
        </span>
      </div>
    </div>

    <!-- Cameras Schedule Table -->
    <div class="table-container">
      <table class="schedule-table">
        <thead>
          <tr>
            <th class="col-checkbox">
              <input
                type="checkbox"
                :checked="allSelected"
                @change="toggleSelectAll"
              />
            </th>
            <th class="col-camera">机位设备</th>
            <th class="col-mode">录像模式</th>
            <th class="col-schedule">周计划 / 生效时段</th>
            <th class="col-storage">存储与切片</th>
            <th class="col-status">调度状态</th>
            <th class="col-actions">操作</th>
          </tr>
        </thead>

        <tbody>
          <tr v-if="loading && !filteredCameras.length">
            <td colspan="7" class="empty-state">
              <div class="empty-state__inner">
                <UiIcon name="refresh" :size="20" class="animate-spin" />
                <span>正在加载机位录制计划...</span>
              </div>
            </td>
          </tr>

          <tr v-else-if="!filteredCameras.length">
            <td colspan="7" class="empty-state">
              <div class="empty-state__inner">
                <UiIcon name="folder" :size="24" />
                <span>没有符合条件的机位录制计划</span>
              </div>
            </td>
          </tr>

          <tr
            v-for="camera in filteredCameras"
            :key="camera.id"
            class="schedule-row"
            :class="{ selected: selectedCameraIds.includes(camera.id) }"
          >
            <!-- Multi-select checkbox -->
            <td class="col-checkbox">
              <input
                type="checkbox"
                :checked="selectedCameraIds.includes(camera.id)"
                @change="toggleSelectCamera(camera.id)"
              />
            </td>

            <!-- Camera Info -->
            <td class="col-camera">
              <div class="camera-info-cell">
                <CameraDeviceGlyph
                  :form-factor="camera.form_factor || 'unknown'"
                  :size="30"
                  class="camera-icon-glyph"
                />
                <div class="camera-texts">
                  <div class="camera-name font-medium">
                    {{ camera.name }}
                  </div>
                  <div class="camera-meta font-mono">
                    <span>{{ camera.ip || "IP未分配" }}</span>
                    <span v-if="camera.location" class="location-tag">· {{ camera.location }}</span>
                  </div>
                </div>
              </div>
            </td>

            <!-- Mode Tag -->
            <td class="col-mode">
              <span
                class="mode-badge"
                :class="`mode-badge--${getCameraEffectiveMode(camera)}`"
              >
                <template v-if="getCameraEffectiveMode(camera) === 'continuous'">
                  🟢 全天自动录像
                </template>
                <template v-else-if="getCameraEffectiveMode(camera) === 'schedule'">
                  ⏱️ 自定义周计划
                </template>
                <template v-else-if="getCameraEffectiveMode(camera) === 'events'">
                  🔔 动检事件录像
                </template>
                <template v-else>
                  ⚪ 停用 / 仅手动
                </template>
              </span>
            </td>

            <!-- Schedule Rule & 7-day visualization -->
            <td class="col-schedule">
              <div class="schedule-cell">
                <!-- 7-day pill indicator -->
                <div class="week-pill-strip">
                  <span
                    v-for="day in WEEKDAY_OPTIONS"
                    :key="day.value"
                    class="day-dot"
                    :class="{ active: isDayActiveInSchedule(camera, day.value) }"
                    :title="`${day.label}: ${isDayActiveInSchedule(camera, day.value) ? '计划生效中' : '未开启'}`"
                  >
                    {{ day.short }}
                  </span>
                </div>
                <div class="schedule-summary-text text-secondary">
                  {{ getScheduleSummaryText(camera) }}
                </div>
              </div>
            </td>

            <!-- Storage & Retention -->
            <td class="col-storage">
              <div class="storage-cell">
                <span class="storage-pool-pill font-mono">
                  {{ getStorageTargetLabel(getCameraPolicy(camera.id)?.storage_target_id) }}
                </span>
                <span class="segment-text text-muted">
                  {{ getCameraPolicy(camera.id)?.segment_target_seconds || 300 }}s 切片
                </span>
              </div>
            </td>

            <!-- Runtime Status -->
            <td class="col-status">
              <div class="runtime-status-cell">
                <span
                  class="status-indicator-dot"
                  :class="getRuntimeStateInfo(camera).tone"
                ></span>
                <span class="runtime-status-label">{{ getRuntimeStateInfo(camera).label }}</span>
              </div>
            </td>

            <!-- Action button -->
            <td class="col-actions">
              <button
                v-if="auth.hasPermission('camera.configure')"
                type="button"
                class="btn-row-action"
                title="修改机位录像周计划"
                @click="openSingleDialog(camera)"
              >
                <span>配置计划</span>
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- ================= PLAN CONFIGURATION MODAL / DRAWER ================= -->
    <div
      v-if="dialogVisible"
      class="dialog-backdrop"
      @click.self="dialogVisible = false"
    >
      <div class="dialog-card">
        <!-- Dialog Header -->
        <header class="dialog-header">
          <div class="dialog-header__title">
            <span class="dialog-icon">
              <UiIcon name="sliders" :size="18" />
            </span>
            <div>
              <h3>
                {{
                  dialogMode === 'batch'
                    ? `批量应用周计划 · ${selectedCameraIds.length} 路机位`
                    : `${editForm.name} · 录像计划配置`
                }}
              </h3>
              <p>
                {{
                  dialogMode === 'batch'
                    ? '保存后将统一覆盖所选机位的录像模式、周计划时间段与高级切片参数'
                    : '配置该机位的 24×7 自动录像模式或自定义分段周计划矩阵'
                }}
              </p>
            </div>
          </div>
          <button
            type="button"
            class="dialog-close"
            title="关闭 (Esc)"
            @click="dialogVisible = false"
          >
            <UiIcon name="x" :size="18" />
          </button>
        </header>

        <!-- Dialog Error Alert -->
        <div v-if="dialogError" class="alert-banner alert-banner--error dialog-alert">
          <UiIcon name="warning" :size="15" />
          <span>{{ dialogError }}</span>
        </div>

        <div class="dialog-body">
          <!-- Step 1: Mode Segmented Cards -->
          <div class="form-section">
            <label class="section-label">录像运行模式</label>
            <div class="mode-cards-grid">
              <!-- Mode 1: Continuous -->
              <div
                class="mode-card"
                :class="{ active: editForm.mode === 'continuous' }"
                @click="editForm.mode = 'continuous'"
              >
                <div class="mode-card__radio">
                  <div class="radio-circle"></div>
                </div>
                <div class="mode-card__content">
                  <div class="mode-card__title">全天自动录像 (24×7)</div>
                  <div class="mode-card__desc">每周 7 天 24 小时不间断录像，自动按目标时长连续切片</div>
                </div>
              </div>

              <!-- Mode 2: Weekly Schedule -->
              <div
                class="mode-card"
                :class="{ active: editForm.mode === 'schedule' }"
                @click="editForm.mode = 'schedule'"
              >
                <div class="mode-card__radio">
                  <div class="radio-circle"></div>
                </div>
                <div class="mode-card__content">
                  <div class="mode-card__title">自定义周计划 (Schedule)</div>
                  <div class="mode-card__desc">仅在指定星期和时间段内自动录像，支持跨午夜分段执行</div>
                </div>
              </div>

              <!-- Mode 3: Events Only -->
              <div
                class="mode-card"
                :class="{ active: editForm.mode === 'events' }"
                @click="editForm.mode = 'events'"
              >
                <div class="mode-card__radio">
                  <div class="radio-circle"></div>
                </div>
                <div class="mode-card__content">
                  <div class="mode-card__title">仅动检事件录像</div>
                  <div class="mode-card__desc">平时保持预录缓冲，检测到人体/车辆事件时自动记录事件片段</div>
                </div>
              </div>

              <!-- Mode 4: Disabled -->
              <div
                class="mode-card"
                :class="{ active: editForm.mode === 'disabled' }"
                @click="editForm.mode = 'disabled'"
              >
                <div class="mode-card__radio">
                  <div class="radio-circle"></div>
                </div>
                <div class="mode-card__content">
                  <div class="mode-card__title">停用自动录像</div>
                  <div class="mode-card__desc">不自动录像；保留机位接入，仅允许在控制台按需手动开启录像</div>
                </div>
              </div>
            </div>
          </div>

          <!-- Step 2: Weekly Windows Editor (Only when Schedule mode) -->
          <div v-if="editForm.mode === 'schedule'" class="form-section schedule-editor-box">
            <div class="schedule-editor-header">
              <div>
                <label class="section-label">录制时间窗口 (Time Windows)</label>
                <p class="section-sub">每个时段可自由挑选星期与起止时间，支持跨午夜至次日早晨</p>
              </div>

              <!-- Presets -->
              <div class="preset-buttons">
                <span class="preset-label">快速模板:</span>
                <button type="button" class="btn-preset" @click="applySchedulePreset('all_day')">全周 24×7</button>
                <button type="button" class="btn-preset" @click="applySchedulePreset('workdays')">工作日白天</button>
                <button type="button" class="btn-preset" @click="applySchedulePreset('night')">夜间安防 (跨午夜)</button>
                <button type="button" class="btn-preset" @click="applySchedulePreset('weekend_plus')">周末+夜间</button>
              </div>
            </div>

            <!-- Windows List -->
            <div class="window-cards-list">
              <article
                v-for="(win, idx) in editForm.windows"
                :key="idx"
                class="window-card"
                :class="{ overnight: crossesMidnight(win) }"
              >
                <!-- Window Header -->
                <div class="window-card__header">
                  <div class="window-title">
                    <span class="window-badge">{{ String(idx + 1).padStart(2, '0') }}</span>
                    <div>
                      <strong>时间段 {{ idx + 1 }}</strong>
                      <span class="window-summary text-muted">
                        {{ dayLabel(win.days) }} · {{ win.start }} → {{ win.end }}
                      </span>
                    </div>
                  </div>

                  <div class="window-actions">
                    <span v-if="crossesMidnight(win)" class="badge-overnight">
                      跨午夜 (次日结束)
                    </span>
                    <button
                      type="button"
                      class="btn-delete-window"
                      title="删除此时间段"
                      @click="removeWindow(idx)"
                    >
                      <UiIcon name="x" :size="13" />
                      <span>删除</span>
                    </button>
                  </div>
                </div>

                <!-- Window Days Selection -->
                <div class="window-section">
                  <div class="section-sub-row">
                    <span class="sub-label">生效日期</span>
                    <div class="day-presets">
                      <button
                        type="button"
                        class="btn-day-preset"
                        :class="{ active: sameDays(win.days, ALL_DAYS) }"
                        @click="setWindowPresetDays(idx, ALL_DAYS)"
                      >
                        每天
                      </button>
                      <button
                        type="button"
                        class="btn-day-preset"
                        :class="{ active: sameDays(win.days, WORK_DAYS) }"
                        @click="setWindowPresetDays(idx, WORK_DAYS)"
                      >
                        工作日
                      </button>
                      <button
                        type="button"
                        class="btn-day-preset"
                        :class="{ active: sameDays(win.days, WEEKEND) }"
                        @click="setWindowPresetDays(idx, WEEKEND)"
                      >
                        周末
                      </button>
                    </div>
                  </div>

                  <div class="weekdays-grid">
                    <button
                      v-for="d in WEEKDAY_OPTIONS"
                      :key="d.value"
                      type="button"
                      class="weekday-btn"
                      :class="{ active: win.days.includes(d.value) }"
                      @click="toggleWindowDay(idx, d.value)"
                    >
                      <span class="day-short">{{ d.short }}</span>
                      <small class="day-name">{{ d.label }}</small>
                    </button>
                  </div>
                </div>

                <!-- Time Interval Pickers -->
                <div class="window-time-band">
                  <div class="time-field">
                    <span class="time-label">开始时间</span>
                    <input
                      v-model="win.start"
                      type="time"
                      class="time-input font-mono"
                      required
                    />
                  </div>

                  <div class="time-separator">
                    <span>→</span>
                    <small>{{ crossesMidnight(win) ? '次日结束' : '当日结束' }}</small>
                  </div>

                  <div class="time-field">
                    <span class="time-label">结束时间</span>
                    <input
                      v-model="win.end"
                      type="time"
                      class="time-input font-mono"
                      required
                    />
                  </div>

                  <div class="duration-box">
                    <span class="duration-title">{{ windowDurationLabel(win) }}</span>
                    <small>有效时长</small>
                  </div>
                </div>

                <!-- Window Hint Note -->
                <div class="window-footer-note" :class="{ overnight: crossesMidnight(win) }">
                  <span class="dot"></span>
                  <span v-if="crossesMidnight(win)">
                    从 {{ win.start }} 开始录制并跨越午夜至次日 {{ win.end }} 结束；该窗口归属于起始日。
                  </span>
                  <span v-else>
                    {{ win.start }} 至 {{ win.end }} 在所选日期当日内执行。
                  </span>
                </div>
              </article>
            </div>

            <!-- Add Window Button -->
            <button
              type="button"
              class="btn-add-window-tile"
              @click="addWindow"
            >
              <UiIcon name="plus" :size="16" />
              <span>添加另一个录制时间窗口 (例如周末使用不同时段)</span>
            </button>
          </div>

          <!-- Step 3: Storage & Advanced Parameters (Collapsible) -->
          <div class="form-section advanced-section">
            <button
              type="button"
              class="advanced-toggle"
              @click="editForm.showAdvanced = !editForm.showAdvanced"
            >
              <UiIcon
                name="chevron-right"
                :size="14"
                :class="{ rotated: editForm.showAdvanced }"
              />
              <strong>存储与录制高级参数 (切片、预录、存储池)</strong>
            </button>

            <div v-if="editForm.showAdvanced" class="advanced-grid">
              <label class="form-field">
                <span class="field-label">目标存储池</span>
                <select v-model="editForm.storageTargetId" class="form-select">
                  <option value="">默认存储池 (系统推断)</option>
                  <option
                    v-for="target in storageTargets"
                    :key="target.id"
                    :value="target.id"
                  >
                    {{ target.name }} ({{ target.type }})
                  </option>
                </select>
              </label>

              <label class="form-field">
                <span class="field-label">留存策略 (Retention)</span>
                <select v-model="editForm.retentionPolicyId" class="form-select">
                  <option value="">跟随存储池默认规则</option>
                  <option
                    v-for="ret in retentionPolicies"
                    :key="ret.id"
                    :value="ret.id"
                  >
                    {{ ret.name }}
                  </option>
                </select>
              </label>

              <label class="form-field">
                <span class="field-label">切片目标时长 (Segment)</span>
                <select v-model.number="editForm.segmentSeconds" class="form-select">
                  <option :value="60">60 秒 (快速入库)</option>
                  <option :value="300">300 秒 (5 分钟 - 推荐)</option>
                  <option :value="600">600 秒 (10 分钟)</option>
                  <option :value="900">900 秒 (15 分钟)</option>
                </select>
              </label>

              <label class="form-field">
                <span class="field-label">预录时长 (Pre-roll)</span>
                <select v-model.number="editForm.preRoll" class="form-select">
                  <option :value="0">0 秒</option>
                  <option :value="5">5 秒</option>
                  <option :value="10">10 秒 (推荐)</option>
                  <option :value="15">15 秒</option>
                </select>
              </label>

              <label class="form-field">
                <span class="field-label">延录时长 (Post-roll)</span>
                <select v-model.number="editForm.postRoll" class="form-select">
                  <option :value="5">5 秒</option>
                  <option :value="10">10 秒 (推荐)</option>
                  <option :value="30">30 秒</option>
                  <option :value="60">60 秒</option>
                </select>
              </label>

              <label class="form-field">
                <span class="field-label">调度时区</span>
                <input
                  v-model="editForm.timezone"
                  type="text"
                  class="form-input font-mono"
                  placeholder="UTC 或 Asia/Shanghai"
                />
              </label>
            </div>
          </div>
        </div>

        <!-- Dialog Footer -->
        <footer class="dialog-footer">
          <button
            type="button"
            class="btn-footer btn-footer--cancel"
            :disabled="saving"
            @click="dialogVisible = false"
          >
            取消
          </button>

          <button
            type="button"
            class="btn-footer btn-footer--save"
            :disabled="saving"
            @click="savePlan"
          >
            <UiIcon v-if="saving" name="refresh" :size="14" class="animate-spin" />
            <span>
              {{
                saving
                  ? '正在应用计划...'
                  : dialogMode === 'batch'
                    ? `批量应用到 ${selectedCameraIds.length} 路机位`
                    : '保存并立即生效'
              }}
            </span>
          </button>
        </footer>
      </div>
    </div>
  </div>
</template>

<style scoped>
.schedule-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 24px 32px;
  overflow-y: auto;
  background-color: var(--uf-bg-canvas);
  color: var(--uf-text-primary);
  box-sizing: border-box;
}

/* Toast */
.schedule-toast {
  position: fixed;
  top: 24px;
  right: 32px;
  z-index: 1000;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 18px;
  border-radius: var(--radius-sm, 6px);
  background: rgba(16, 185, 129, 0.92);
  color: #ffffff;
  font-size: 13px;
  font-weight: 500;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2);
  backdrop-filter: blur(8px);
}

/* Header */
.schedule-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
  gap: 16px;
}

.schedule-header__brand {
  display: flex;
  align-items: center;
  gap: 12px;
}

.brand-badge {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  border-radius: 10px;
  background: var(--uf-accent-soft);
  color: var(--uf-accent);
}

.schedule-title {
  margin: 0;
  font-size: 20px;
  font-weight: 700;
  letter-spacing: -0.01em;
}

.schedule-subtitle {
  margin: 4px 0 0 0;
  font-size: 13px;
  color: var(--uf-text-muted);
}

.schedule-header__actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.scheduler-pill {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: 20px;
  background: var(--uf-bg-card);
  border: 1px solid var(--uf-border);
  font-size: 12px;
  color: var(--uf-text-secondary);
  font-weight: 500;
}

.status-indicator-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}

.status-indicator-dot.ok {
  background-color: #10b981;
  box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.16);
}

.status-indicator-dot.standby {
  background-color: #3b82f6;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.16);
}

.status-indicator-dot.off {
  background-color: #94a3b8;
}

.status-indicator-dot.warn {
  background-color: #f59e0b;
}

/* Action Buttons */
.btn-action {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  border-radius: var(--radius-sm, 6px);
  border: 1px solid var(--uf-border);
  background: var(--uf-bg-card);
  color: var(--uf-text-primary);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
}

.btn-action:hover:not(:disabled) {
  background: var(--uf-bg-hover);
  border-color: var(--uf-border-strong);
}

.btn-action:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-action--primary {
  background: var(--uf-accent);
  border-color: var(--uf-accent);
  color: #ffffff;
}

.btn-action--primary:hover:not(:disabled) {
  background: var(--uf-accent-hover);
  border-color: var(--uf-accent-hover);
}

.btn-action--ghost {
  background: transparent;
}

/* Alert Banner */
.alert-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-radius: var(--radius-sm, 6px);
  margin-bottom: 16px;
  font-size: 13px;
}

.alert-banner--error {
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.25);
  color: #ef4444;
}

/* Stats Row */
.stats-row {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}

.stat-card {
  padding: 14px 16px;
  border-radius: var(--radius-md, 8px);
  background: var(--uf-bg-card);
  border: 1px solid var(--uf-border);
  cursor: pointer;
  transition: all 0.15s ease;
}

.stat-card:hover {
  border-color: var(--uf-border-strong);
  background: var(--uf-bg-card-sub);
}

.stat-card.active {
  border-color: var(--uf-accent);
  box-shadow: 0 0 0 1px var(--uf-accent);
}

.stat-card__val {
  font-size: 24px;
  font-weight: 700;
  font-family: var(--font-mono);
  line-height: 1;
}

.stat-card__lbl {
  margin-top: 6px;
  font-size: 12px;
  color: var(--uf-text-muted);
}

.text-continuous { color: #10b981; }
.text-schedule { color: #3b82f6; }
.text-events { color: #f59e0b; }
.text-disabled { color: #94a3b8; }

/* Toolbar */
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  gap: 12px;
}

.toolbar__search {
  position: relative;
  display: flex;
  align-items: center;
  width: 320px;
}

.search-icon {
  position: absolute;
  left: 10px;
  color: var(--uf-text-muted);
  pointer-events: none;
}

.search-input {
  width: 100%;
  height: 34px;
  padding: 0 28px 0 32px;
  border-radius: var(--radius-sm, 6px);
  border: 1px solid var(--uf-border);
  background: var(--uf-bg-input);
  color: var(--uf-text-primary);
  font-size: 13px;
  outline: none;
  box-sizing: border-box;
}

.search-input:focus {
  border-color: var(--uf-accent);
}

.search-clear {
  position: absolute;
  right: 8px;
  background: none;
  border: none;
  color: var(--uf-text-muted);
  cursor: pointer;
}

.toolbar__selection-info {
  font-size: 13px;
  color: var(--uf-text-secondary);
}

/* Table */
.table-container {
  flex: 1;
  overflow: auto;
  border-radius: var(--radius-md, 8px);
  border: 1px solid var(--uf-border);
  background: var(--uf-bg-card);
}

.schedule-table {
  width: 100%;
  border-collapse: collapse;
  text-align: left;
  font-size: 13px;
}

.schedule-table thead {
  background: var(--uf-bg-card-sub);
  position: sticky;
  top: 0;
  z-index: 10;
}

.schedule-table th {
  padding: 10px 14px;
  font-weight: 600;
  color: var(--uf-text-muted);
  border-bottom: 1px solid var(--uf-border);
  font-size: 12px;
  white-space: nowrap;
}

.schedule-table td {
  padding: 12px 14px;
  border-bottom: 1px solid var(--uf-border);
  vertical-align: middle;
}

.schedule-row:hover {
  background-color: var(--uf-bg-hover);
}

.schedule-row.selected {
  background-color: var(--uf-accent-soft);
}

/* Table Columns */
.col-checkbox {
  width: 40px;
  text-align: center;
}

.col-camera {
  min-width: 220px;
}

.col-mode {
  width: 150px;
}

.col-schedule {
  min-width: 280px;
}

.col-storage {
  width: 170px;
}

.col-status {
  width: 130px;
}

.col-actions {
  width: 100px;
  text-align: right;
}

/* Camera Info Cell */
.camera-info-cell {
  display: flex;
  align-items: center;
  gap: 10px;
}

.camera-texts {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.camera-name {
  color: var(--uf-text-primary);
  font-weight: 600;
}

.camera-meta {
  font-size: 11px;
  color: var(--uf-text-muted);
}

.location-tag {
  color: var(--uf-text-secondary);
}

/* Mode Badges */
.mode-badge {
  display: inline-block;
  padding: 3px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
}

.mode-badge--continuous {
  background: rgba(16, 185, 129, 0.12);
  color: #10b981;
}

.mode-badge--schedule {
  background: rgba(59, 130, 246, 0.12);
  color: #3b82f6;
}

.mode-badge--events {
  background: rgba(245, 158, 11, 0.12);
  color: #d97706;
}

.mode-badge--disabled {
  background: var(--uf-bg-hover);
  color: var(--uf-text-muted);
}

/* Weekday Pills */
.schedule-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.week-pill-strip {
  display: flex;
  gap: 3px;
}

.day-dot {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 19px;
  height: 19px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 600;
  background: var(--uf-bg-hover);
  color: var(--uf-text-muted);
}

.day-dot.active {
  background: var(--uf-accent);
  color: #ffffff;
}

.schedule-summary-text {
  font-size: 12px;
}

/* Storage Cell */
.storage-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.storage-pool-pill {
  font-size: 11px;
  font-weight: 600;
  color: var(--uf-text-secondary);
}

.segment-text {
  font-size: 11px;
}

/* Runtime Status Cell */
.runtime-status-cell {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
}

/* Row Action */
.btn-row-action {
  padding: 4px 10px;
  border-radius: 4px;
  border: 1px solid var(--uf-border);
  background: var(--uf-bg-card);
  color: var(--uf-accent);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
}

.btn-row-action:hover {
  background: var(--uf-accent-soft);
  border-color: var(--uf-accent);
}

.empty-state {
  text-align: center;
  padding: 48px 0;
}

.empty-state__inner {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  color: var(--uf-text-muted);
  font-size: 13px;
}

/* ================= MODAL / DRAWER STYLES ================= */
.dialog-backdrop {
  position: fixed;
  inset: 0;
  z-index: 999;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(4px);
  padding: 20px;
}

.dialog-card {
  display: flex;
  flex-direction: column;
  width: 880px;
  max-width: 95vw;
  max-height: 90vh;
  border-radius: 12px;
  background: var(--uf-bg-card);
  border: 1px solid var(--uf-border);
  box-shadow: var(--uf-shadow-lg);
  overflow: hidden;
}

.dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--uf-border);
  background: var(--uf-bg-card-sub);
}

.dialog-header__title {
  display: flex;
  align-items: center;
  gap: 12px;
}

.dialog-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: 8px;
  background: var(--uf-accent-soft);
  color: var(--uf-accent);
}

.dialog-header h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
}

.dialog-header p {
  margin: 2px 0 0 0;
  font-size: 12px;
  color: var(--uf-text-muted);
}

.dialog-close {
  background: none;
  border: none;
  color: var(--uf-text-muted);
  cursor: pointer;
  padding: 4px;
  border-radius: 4px;
}

.dialog-close:hover {
  color: var(--uf-text-primary);
  background: var(--uf-bg-hover);
}

.dialog-alert {
  margin: 12px 20px 0 20px;
}

.dialog-body {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.form-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.section-label {
  font-size: 13px;
  font-weight: 700;
  color: var(--uf-text-primary);
}

.section-sub {
  margin: 0;
  font-size: 12px;
  color: var(--uf-text-muted);
}

/* Mode Selection Cards */
.mode-cards-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
}

.mode-card {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 12px 14px;
  border-radius: 8px;
  border: 1px solid var(--uf-border);
  background: var(--uf-bg-card-sub);
  cursor: pointer;
  transition: all 0.15s ease;
}

.mode-card:hover {
  border-color: var(--uf-border-strong);
}

.mode-card.active {
  border-color: var(--uf-accent);
  background: var(--uf-accent-soft);
}

.mode-card__radio {
  margin-top: 2px;
}

.radio-circle {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  border: 2px solid var(--uf-border-strong);
  box-sizing: border-box;
}

.mode-card.active .radio-circle {
  border-color: var(--uf-accent);
  background: var(--uf-accent);
  box-shadow: inset 0 0 0 3px #ffffff;
}

.mode-card__title {
  font-size: 13px;
  font-weight: 600;
  color: var(--uf-text-primary);
}

.mode-card__desc {
  margin-top: 3px;
  font-size: 11px;
  color: var(--uf-text-muted);
  line-height: 1.4;
}

/* Weekly Windows Box */
.schedule-editor-box {
  padding-top: 4px;
}

.schedule-editor-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  margin-bottom: 12px;
  gap: 12px;
}

.preset-buttons {
  display: flex;
  align-items: center;
  gap: 6px;
}

.preset-label {
  font-size: 11px;
  color: var(--uf-text-muted);
}

.btn-preset {
  padding: 4px 8px;
  border-radius: 4px;
  border: 1px solid var(--uf-border);
  background: var(--uf-bg-card);
  color: var(--uf-text-secondary);
  font-size: 11px;
  cursor: pointer;
}

.btn-preset:hover {
  color: var(--uf-accent);
  border-color: var(--uf-accent);
}

/* Window Cards List */
.window-cards-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.window-card {
  border: 1px solid var(--uf-border);
  border-radius: 8px;
  background: var(--uf-bg-card-sub);
  overflow: hidden;
}

.window-card.overnight {
  border-color: rgba(245, 158, 11, 0.4);
}

.window-card__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border-bottom: 1px solid var(--uf-border);
  background: var(--uf-bg-card);
}

.window-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.window-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 6px;
  background: var(--uf-accent-soft);
  color: var(--uf-accent);
  font-size: 11px;
  font-weight: 700;
  font-family: var(--font-mono);
}

.window-summary {
  margin-left: 6px;
  font-size: 11px;
}

.window-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.badge-overnight {
  padding: 2px 6px;
  border-radius: 4px;
  background: rgba(245, 158, 11, 0.15);
  color: #d97706;
  font-size: 10px;
  font-weight: 600;
}

.btn-delete-window {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 6px;
  border: none;
  background: none;
  color: #ef4444;
  font-size: 11px;
  cursor: pointer;
}

.btn-delete-window:hover {
  text-decoration: underline;
}

.window-section {
  padding: 10px 12px;
}

.section-sub-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.sub-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--uf-text-secondary);
}

.day-presets {
  display: flex;
  gap: 4px;
}

.btn-day-preset {
  padding: 2px 6px;
  border-radius: 4px;
  border: 1px solid var(--uf-border);
  background: var(--uf-bg-card);
  font-size: 10px;
  color: var(--uf-text-secondary);
  cursor: pointer;
}

.btn-day-preset.active {
  background: var(--uf-accent-soft);
  border-color: var(--uf-accent);
  color: var(--uf-accent);
  font-weight: 600;
}

.weekdays-grid {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 4px;
}

.weekday-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 6px 2px;
  border-radius: 6px;
  border: 1px solid var(--uf-border);
  background: var(--uf-bg-card);
  color: var(--uf-text-secondary);
  cursor: pointer;
  transition: all 0.12s;
}

.weekday-btn:hover {
  border-color: var(--uf-accent);
}

.weekday-btn.active {
  background: var(--uf-accent);
  border-color: var(--uf-accent);
  color: #ffffff;
}

.day-short {
  font-size: 12px;
  font-weight: 700;
}

.day-name {
  font-size: 9px;
  opacity: 0.8;
}

/* Time Band */
.window-time-band {
  display: grid;
  grid-template-columns: 1fr 40px 1fr 110px;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: var(--uf-bg-card);
  border-top: 1px solid var(--uf-border);
}

.time-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.time-label {
  font-size: 10px;
  color: var(--uf-text-muted);
}

.time-input {
  height: 32px;
  padding: 0 8px;
  border-radius: 4px;
  border: 1px solid var(--uf-border);
  background: var(--uf-bg-input);
  color: var(--uf-text-primary);
  font-size: 13px;
  font-weight: 600;
  outline: none;
}

.time-input:focus {
  border-color: var(--uf-accent);
}

.time-separator {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--uf-text-muted);
  font-size: 14px;
}

.time-separator small {
  font-size: 8px;
  white-space: nowrap;
}

.duration-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 32px;
  border-radius: 4px;
  border: 1px dashed var(--uf-border);
  background: var(--uf-bg-card-sub);
}

.duration-title {
  font-size: 11px;
  font-weight: 700;
  color: var(--uf-text-secondary);
}

.duration-box small {
  font-size: 9px;
  color: var(--uf-text-muted);
}

.window-footer-note {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  font-size: 11px;
  color: var(--uf-text-muted);
  border-top: 1px solid var(--uf-border);
  background: var(--uf-bg-card-sub);
}

.window-footer-note .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #10b981;
}

.window-footer-note.overnight .dot {
  background: #f59e0b;
}

.btn-add-window-tile {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 10px;
  border-radius: 8px;
  border: 1px dashed var(--uf-accent);
  background: var(--uf-accent-soft);
  color: var(--uf-accent);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
}

.btn-add-window-tile:hover {
  background: rgba(37, 99, 235, 0.18);
}

/* Advanced Parameters */
.advanced-section {
  padding-top: 8px;
  border-top: 1px solid var(--uf-border);
}

.advanced-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  background: none;
  border: none;
  color: var(--uf-text-primary);
  font-size: 13px;
  cursor: pointer;
  padding: 4px 0;
}

.advanced-toggle svg {
  transition: transform 0.15s ease;
}

.advanced-toggle svg.rotated {
  transform: rotate(90deg);
}

.advanced-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
  padding-top: 10px;
}

.form-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.field-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--uf-text-muted);
}

.form-select,
.form-input {
  height: 34px;
  padding: 0 10px;
  border-radius: 6px;
  border: 1px solid var(--uf-border);
  background: var(--uf-bg-input);
  color: var(--uf-text-primary);
  font-size: 13px;
  outline: none;
}

.form-select:focus,
.form-input:focus {
  border-color: var(--uf-accent);
}

/* Dialog Footer */
.dialog-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  padding: 14px 20px;
  border-top: 1px solid var(--uf-border);
  background: var(--uf-bg-card-sub);
}

.btn-footer {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}

.btn-footer--cancel {
  border: 1px solid var(--uf-border);
  background: var(--uf-bg-card);
  color: var(--uf-text-primary);
}

.btn-footer--cancel:hover {
  background: var(--uf-bg-hover);
}

.btn-footer--save {
  border: 1px solid var(--uf-accent);
  background: var(--uf-accent);
  color: #ffffff;
}

.btn-footer--save:hover:not(:disabled) {
  background: var(--uf-accent-hover);
}

.btn-footer:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* Responsive */
@media (max-width: 900px) {
  .schedule-view {
    padding: 16px;
  }
  .stats-row {
    grid-template-columns: repeat(2, 1fr);
  }
  .mode-cards-grid {
    grid-template-columns: 1fr;
  }
  .window-time-band {
    grid-template-columns: 1fr;
  }
}
</style>
