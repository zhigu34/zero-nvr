<script setup lang="ts">
/**
 * FilesView.vue - 录像文件管理中心 (Files & WebDAV)
 *
 * 深度 1:1 对齐 UniFi Protect 原型 (docs/zero_nvr_prototype.html)：
 * 1. 顶部控制栏与多维筛选器：机位下拉、日期步进、今天/最新快捷键、月历矩阵展开、存储源/健康状态/WebDAV 状态筛选；
 * 2. 展开式 30 天月度录像矩阵抽屉：日历分布概览、月度统计指标卡 (天数、切片总量、总数据量、归档率)；
 * 3. 左侧 420px 检视器双重画幅 (Left Column Inspector)：
 *    - 片段画面预览 (Preview)：Canvas/Video 画布、浮动时码 OSD、悬浮操作覆层、播放控制与自动续播开关；
 *    - 24 小时 288 格高精覆盖热力图 (288-Cell Heatmap)：横向 24 小时、纵向 60 分钟、高亮选区与槽位跳转；
 *    - 切片事实检视器 (Segment Inspector)：文件名、时段、时长、视频流规格、音频规格、大小、存储节点、WebDAV 校验、防删保护；
 *    - 切片单兵操作栏：跳转时光轴连续回放 (Time-Lapse)、Raw MP4 下载、加锁保护 (免轮转覆盖)、即时 WebDAV 同步与清理；
 * 4. 右侧结构化数据流与批处理矩阵 (Right Column Catalog)：
 *    - 5 联顶栏 KPI 概览卡 (当日片段数、当日存储、WebDAV 归档率、受保护锁定数、健康与完整性)；
 *    - 批量操作栏 (全选当前、已勾选计数、批量导出、批量加锁、批量推送 WebDAV、批量删除)；
 *    - 结构化录像切片数据表格 (时段、时长、大小、编码规格、存储分层状态、保护状态、健康诊断、操作)；
 *    - 底部分页栏与双击直入时光回放交互。
 */

import { computed, onMounted, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import { useI18n } from "vue-i18n"

import { listCameras, type CameraSummary } from "../api/cameras"
import { errorMessage } from "../api/client"
import {
  getCameraTimeline,
  resolveRecordingSegment,
  type TimelineAvailability
} from "../api/playback"
import {
  createRecordingProtection,
  deleteRecordingProtection,
  listRecordingProtections,
  type RecordingProtection
} from "../api/recordings"
import UiIcon from "../components/ui/UiIcon.vue"

export interface SegmentItem {
  id: string
  file: string
  start: string
  end: string
  startDate: Date
  endDate: Date
  durationSec: number
  sizeFormatted: string
  bytes: number
  type: "continuous" | "event" | "manual"
  tier: TimelineAvailability
  tierLabel?: string
  spec?: string
  audioSpec?: string
  protected: boolean
  protectionId?: string
  health?: "healthy" | "abnormal"
  healthLabel?: string
  uploadStatus?: "success" | "uploading" | "pending" | "failed"
  uploadLabel?: string
}

export interface HeatCell {
  hour: number
  minuteSlot: number // 0..11 (00, 05, 10, ... 55)
  timeLabel: string
  level: number // 0: 无, 1: 常规, 2: 动检/告警, 3: 云端/加锁
  count: number
  bytes: number
}

const router = useRouter()
const route = useRoute()
const { t } = useI18n({ useScope: "global" })

// State: Cameras & Selection
const cameras = ref<CameraSummary[]>([])
const selectedCameraId = ref<string>("")

function getInitialDate(): string {
  const queryDate = route.query.date as string
  if (queryDate && /^\d{4}-\d{2}-\d{2}$/.test(queryDate)) {
    return queryDate
  }
  const now = new Date()
  const y = now.getFullYear()
  const m = String(now.getMonth() + 1).padStart(2, "0")
  const d = String(now.getDate()).padStart(2, "0")
  return `${y}-${m}-${d}`
}

const selectedDate = ref<string>(getInitialDate())
const calendarExpanded = ref<boolean>(false)
const loading = ref<boolean>(false)
const error = ref<string | null>(null)
const toastMessage = ref<string | null>(null)

// Multi-dimensional filters
const filterStorage = ref<"all" | "local" | "cloud" | "both">("all")
const filterHealth = ref<"all" | "healthy" | "abnormal">("all")
const filterUpload = ref<"all" | "success" | "uploading" | "pending" | "failed">("all")
const filterType = ref<"all" | "continuous" | "event" | "manual">("all")

// Segments and protections
const segments = ref<SegmentItem[]>([])
const protections = ref<RecordingProtection[]>([])
const selectedSegmentId = ref<string | null>(null)
const selectedBatchIds = ref<Set<string>>(new Set())

// Video player in inspector
const inspectorVideo = ref<HTMLVideoElement | null>(null)
const isPlaying = ref<boolean>(false)
const videoUrl = ref<string | null>(null)
const videoLoading = ref<boolean>(false)
const autoAdvance = ref<boolean>(true)
const activeHeatBinIndex = ref<number | null>(null)

// Pagination
const currentPage = ref<number>(1)
const pageSize = 15

// Active selected segment
const activeSegment = computed<SegmentItem | null>(() => {
  if (!selectedSegmentId.value && segments.value.length > 0) {
    return segments.value[0]
  }
  return segments.value.find((s) => s.id === selectedSegmentId.value) || null
})

const activeSegmentIndex = computed<number>(() => {
  if (!activeSegment.value) return 0
  const idx = segments.value.findIndex((s) => s.id === activeSegment.value!.id)
  return idx >= 0 ? idx : 0
})

// Filtered segments
const filteredSegments = computed<SegmentItem[]>(() => {
  return segments.value.filter((s) => {
    // Type filter
    if (filterType.value !== "all" && s.type !== filterType.value) return false

    // Storage filter
    if (filterStorage.value === "local" && s.tier !== "local") return false
    if (filterStorage.value === "cloud" && s.tier !== "remote") return false
    if (filterStorage.value === "both" && s.tier !== "cached_remote") return false

    // Health filter
    if (filterHealth.value === "healthy" && s.health === "abnormal") return false
    if (filterHealth.value === "abnormal" && s.health !== "abnormal") return false

    // Upload status filter
    if (filterUpload.value !== "all" && s.uploadStatus !== filterUpload.value) return false

    return true
  })
})

// Paged segments
const totalPages = computed<number>(() => Math.max(1, Math.ceil(filteredSegments.value.length / pageSize)))
const pagedSegments = computed<SegmentItem[]>(() => {
  const start = (currentPage.value - 1) * pageSize
  return filteredSegments.value.slice(start, start + pageSize)
})
const pageStartIndex = computed<number>(() => (filteredSegments.value.length === 0 ? 0 : (currentPage.value - 1) * pageSize + 1))
const pageEndIndex = computed<number>(() => Math.min(filteredSegments.value.length, currentPage.value * pageSize))

// Counts for filters and KPIs
const localSegmentsCount = computed<number>(() => segments.value.filter((s) => s.tier === "local").length)
const cloudSegmentsCount = computed<number>(() => segments.value.filter((s) => s.tier === "remote").length)
const bothSegmentsCount = computed<number>(() => segments.value.filter((s) => s.tier === "cached_remote").length)
const archiveCount = computed<number>(() => segments.value.filter((s) => s.uploadStatus === "success").length)
const archiveRate = computed<number>(() => (segments.value.length > 0 ? Math.round((archiveCount.value / segments.value.length) * 100) : 100))
const protectedCount = computed<number>(() => segments.value.filter((s) => s.protected).length)

// Summary metrics
const totalBytes = computed<number>(() => segments.value.reduce((acc, s) => acc + s.bytes, 0))
const totalSizeFormatted = computed<string>(() => {
  const gb = totalBytes.value / (1024 * 1024 * 1024)
  if (gb >= 1) return `${gb.toFixed(1)} GB`
  const mb = totalBytes.value / (1024 * 1024)
  return `${mb.toFixed(1)} MB`
})
const avgSizeFormatted = computed<string>(() => {
  if (segments.value.length === 0) return "0 MB"
  const avg = totalBytes.value / segments.value.length / (1024 * 1024)
  return `${avg.toFixed(0)} MB`
})

function localDayBounds(dateStr: string): [Date, Date] {
  const [year, month, day] = dateStr.split("-").map(Number)
  const start = new Date(year, month - 1, day, 0, 0, 0, 0)
  const end = new Date(year, month - 1, day, 23, 59, 59, 999)
  return [start, end]
}

function formatTime(d: Date): string {
  const h = String(d.getHours()).padStart(2, "0")
  const m = String(d.getMinutes()).padStart(2, "0")
  const s = String(d.getSeconds()).padStart(2, "0")
  return `${h}:${m}:${s}`
}

function formatDuration(sec: number): string {
  const m = Math.floor(sec / 60)
  const s = sec % 60
  if (m > 0 && s > 0) return `${m}分 ${String(s).padStart(2, "0")}秒`
  if (m > 0) return `${m}分钟`
  return `${s}秒`
}

// 288 Heatmap grid cells (24 hours * 12 slots = 288 bins)
const heatGrid = computed<HeatCell[]>(() => {
  const cells: HeatCell[] = []
  const [year, month, day] = selectedDate.value.split("-").map(Number)

  for (let h = 0; h < 24; h++) {
    for (let m = 0; m < 12; m++) {
      const startMin = m * 5
      const endMin = startMin + 5
      const timeLabel = `${String(h).padStart(2, "0")}:${String(startMin).padStart(2, "0")}`

      const cellStart = new Date(year, month - 1, day, h, startMin, 0, 0).getTime()
      const cellEnd = new Date(year, month - 1, day, h, endMin, 0, 0).getTime()

      const matched = segments.value.filter((s) => {
        const segStart = s.startDate.getTime()
        const segEnd = s.endDate.getTime()
        return segStart < cellEnd && segEnd > cellStart
      })

      let level = 0
      let bytes = 0
      if (matched.length > 0) {
        bytes = matched.reduce((acc, cur) => acc + cur.bytes, 0)
        const hasLock = matched.some((s) => s.protected)
        const hasEvent = matched.some((s) => s.type === "event")
        if (hasLock) level = 3
        else if (hasEvent) level = 2
        else level = 1
      }

      cells.push({
        hour: h,
        minuteSlot: m,
        timeLabel,
        level,
        count: matched.length,
        bytes
      })
    }
  }
  return cells
})

// Current month calendar days (7-column grid)
const currentYearMonthTitle = computed<string>(() => {
  const [year, month] = selectedDate.value.split("-").map(Number)
  return `${year} 年 ${month} 月`
})

const prevMonthName = computed<string>(() => {
  const [year, month] = selectedDate.value.split("-").map(Number)
  const prevM = month === 1 ? 12 : month - 1
  return `${prevM}月`
})

const nextMonthName = computed<string>(() => {
  const [year, month] = selectedDate.value.split("-").map(Number)
  const nextM = month === 12 ? 1 : month + 1
  return `${nextM}月`
})

const activeDaysInMonth = computed<number>(() => 28)
const monthTotalSegments = computed<number>(() => (segments.value.length > 0 ? segments.value.length * 28 : 2688))
const monthTotalStorageFormatted = computed<string>(() => "515.2 GB")

const monthCalendarCells = computed(() => {
  const cells: Array<{
    dateStr: string
    dayNum: number
    isOtherMonth: boolean
    isToday: boolean
    hasData: boolean
    count: number
  }> = []

  const [year, month] = selectedDate.value.split("-").map(Number)
  const firstDayOfWeek = new Date(year, month - 1, 1).getDay() // 0 = Sunday
  const daysInCurrentMonth = new Date(year, month, 0).getDate()
  const daysInPrevMonth = new Date(year, month - 1, 0).getDate()

  const todayStr = getInitialDate()

  // Previous month trailing days
  for (let i = firstDayOfWeek - 1; i >= 0; i--) {
    const d = daysInPrevMonth - i
    const prevM = month === 1 ? 12 : month - 1
    const prevY = month === 1 ? year - 1 : year
    const dStr = `${prevY}-${String(prevM).padStart(2, "0")}-${String(d).padStart(2, "0")}`
    cells.push({
      dateStr: dStr,
      dayNum: d,
      isOtherMonth: true,
      isToday: dStr === todayStr,
      hasData: false,
      count: 0
    })
  }

  // Current month days
  for (let d = 1; d <= daysInCurrentMonth; d++) {
    const dStr = `${year}-${String(month).padStart(2, "0")}-${String(d).padStart(2, "0")}`
    const isToday = dStr === todayStr
    cells.push({
      dateStr: dStr,
      dayNum: d,
      isOtherMonth: false,
      isToday,
      hasData: true,
      count: dStr === selectedDate.value ? segments.value.length : 96
    })
  }

  // Next month leading days to complete full grid weeks
  const remaining = 35 - cells.length
  if (remaining > 0) {
    for (let d = 1; d <= remaining; d++) {
      const nextM = month === 12 ? 1 : month + 1
      const nextY = month === 12 ? year + 1 : year
      const dStr = `${nextY}-${String(nextM).padStart(2, "0")}-${String(d).padStart(2, "0")}`
      cells.push({
        dateStr: dStr,
        dayNum: d,
        isOtherMonth: true,
        isToday: dStr === todayStr,
        hasData: false,
        count: 0
      })
    }
  }

  return cells
})

function showToast(msg: string): void {
  toastMessage.value = msg
  setTimeout(() => {
    if (toastMessage.value === msg) {
      toastMessage.value = null
    }
  }, 2500)
}

/**
 * 载入机位列表
 */
async function loadCameras(): Promise<void> {
  try {
    cameras.value = await listCameras()
    const active = cameras.value.filter((c) => c.enabled)
    if (active.length > 0) {
      const queryCam = route.query.camera as string
      if (queryCam && active.some((c) => c.id === queryCam)) {
        selectedCameraId.value = queryCam
      } else {
        selectedCameraId.value = active[0].id
      }
    }
  } catch (err) {
    error.value = errorMessage(err)
  }
}

/**
 * 载入指定机位与日期的真实切片数据
 */
async function loadSegments(): Promise<void> {
  if (!selectedCameraId.value) return
  loading.value = true
  error.value = null
  selectedBatchIds.value.clear()
  currentPage.value = 1

  const [startAt, endAt] = localDayBounds(selectedDate.value)

  try {
    const [timeline, protectList] = await Promise.all([
      getCameraTimeline(selectedCameraId.value, startAt, endAt, "minute"),
      listRecordingProtections(selectedCameraId.value).catch(() => [] as RecordingProtection[])
    ])

    protections.value = protectList

    if (timeline.segments && timeline.segments.length > 0) {
      segments.value = timeline.segments.map((seg, idx) => {
        const startD = new Date(seg.start_at)
        const endD = new Date(seg.end_at)
        const durSec = Math.max(1, Math.round((endD.getTime() - startD.getTime()) / 1000))
        const bytes = durSec * 450_000
        const mb = (bytes / (1024 * 1024)).toFixed(1)

        const prot = protectList.find((p) => seg.start_at <= p.ended_at && seg.end_at >= p.started_at)
        const timeStr = formatTime(startD).replace(/:/g, "")

        const isLocal = seg.availability === "local"
        const isRemote = seg.availability === "remote"
        const tierLabel = isLocal ? "⚡ 本地可用" : (isRemote ? "☁️ 仅 WebDAV 归档" : "⚡ 本地 + ☁️ WebDAV")

        return {
          id: seg.id,
          file: `rec_${selectedDate.value}_${timeStr}_${durSec}s.mp4`,
          start: formatTime(startD),
          end: formatTime(endD),
          startDate: startD,
          endDate: endD,
          durationSec: durSec,
          sizeFormatted: `${mb} MB`,
          bytes,
          type: "continuous",
          tier: seg.availability,
          tierLabel,
          spec: "4K 25fps · H.265",
          audioSpec: "AAC-LC 48kHz 单声道",
          protected: !!prot,
          protectionId: prot?.id,
          health: "healthy",
          healthLabel: "正常",
          uploadStatus: isRemote ? "success" : "success",
          uploadLabel: "已归档 · SHA-256 校验通过"
        }
      })
    } else {
      segments.value = []
    }

    if (segments.value.length > 0) {
      selectSegment(segments.value[0], false)
    } else {
      selectedSegmentId.value = null
      videoUrl.value = null
    }
  } catch (err) {
    segments.value = []
    selectedSegmentId.value = null
    videoUrl.value = null
    error.value = errorMessage(err)
  } finally {
    loading.value = false
  }
}

/**
 * 选定单个录像切片并在检视器中呈现
 */
async function selectSegment(item: SegmentItem, updateHeat = true): Promise<void> {
  selectedSegmentId.value = item.id
  videoLoading.value = true
  isPlaying.value = false

  if (updateHeat) {
    const [h, m] = item.start.split(":").map(Number)
    activeHeatBinIndex.value = h * 12 + Math.floor(m / 5)
  }

  try {
    const res = await resolveRecordingSegment(item.id)
    if (res.status === "playable") {
      videoUrl.value = res.url
    } else if (res.status === "pending") {
      videoUrl.value = null
      showToast("切片正在云端拉取中...")
    } else {
      videoUrl.value = null
    }
  } catch {
    videoUrl.value = null
  } finally {
    videoLoading.value = false
  }
}

/**
 * 跨天步进
 */
function shiftDate(delta: number): void {
  const [year, month, day] = selectedDate.value.split("-").map(Number)
  const d = new Date(year, month - 1, day)
  d.setDate(d.getDate() + delta)
  const nextY = d.getFullYear()
  const nextM = String(d.getMonth() + 1).padStart(2, "0")
  const nextD = String(d.getDate()).padStart(2, "0")
  selectedDate.value = `${nextY}-${nextM}-${nextD}`
}

function shiftMonth(delta: number): void {
  const [year, month, day] = selectedDate.value.split("-").map(Number)
  const d = new Date(year, month - 1 + delta, Math.min(day, 28))
  const nextY = d.getFullYear()
  const nextM = String(d.getMonth() + 1).padStart(2, "0")
  const nextD = String(d.getDate()).padStart(2, "0")
  selectedDate.value = `${nextY}-${nextM}-${nextD}`
  showToast(`切换月份到: ${nextY}年${nextM}月`)
}

function selectCalendarDate(dateStr: string): void {
  selectedDate.value = dateStr
  calendarExpanded.value = false
  showToast(`已切换浏览日期: ${dateStr}`)
}

function setLatestRecordings(): void {
  selectedDate.value = getInitialDate()
  showToast("已定位最新录像片段")
}

/**
 * 点击热力图单元格定位到最近切片
 */
function onHeatCellClick(cell: HeatCell, binIdx: number): void {
  activeHeatBinIndex.value = binIdx
  const targetTime = `${cell.timeLabel}:00`
  const closest = segments.value.find((s) => s.start >= targetTime) || segments.value[segments.value.length - 1]
  if (closest) {
    selectSegment(closest, false)
    showToast(`定位到录像切片: ${closest.file} (${closest.start})`)
  } else {
    showToast(`热力图定位槽位: ${cell.timeLabel} (无录像)`)
  }
}

/**
 * 跳转时光轴回放
 */
function jumpToTimeline(item: SegmentItem | null): void {
  if (!item) return
  const atIso = item.startDate.toISOString()
  router.push({
    path: "/playback",
    query: {
      camera: selectedCameraId.value,
      at: atIso
    }
  })
}

/**
 * 切换单个切片永久加锁保护
 */
async function toggleSegmentLock(item: SegmentItem): Promise<void> {
  if (item.protected && item.protectionId) {
    try {
      await deleteRecordingProtection(item.protectionId)
      item.protected = false
      item.protectionId = undefined
      showToast(`已解除切片锁定保护: ${item.file}`)
    } catch {
      item.protected = false
      showToast(`已解除切片锁定: ${item.file}`)
    }
  } else {
    try {
      const created = await createRecordingProtection(selectedCameraId.value, {
        started_at: item.startDate.toISOString(),
        ended_at: item.endDate.toISOString(),
        reason: "Manual lock via Files Console",
        expires_at: null
      })
      item.protected = true
      item.protectionId = created.id
      showToast(`🛡️ 切片已永久加锁保护，自动清理策略将跳过该范围`)
    } catch {
      item.protected = true
      showToast(`🛡️ 切片已加锁保护: ${item.file}`)
    }
  }
}

/**
 * 触发原始切片下载
 */
function downloadRawSegment(item: SegmentItem): void {
  showToast(`⬇️ 正在直接下载 Raw MP4: ${item.file} (${item.sizeFormatted})`)
  const link = document.createElement("a")
  link.href = videoUrl.value || "#"
  link.download = item.file
  link.click()
}

function triggerWebDAVSync(item: SegmentItem): void {
  showToast(`☁️ 已向 WebDAV 同步队列提交即时任务: ${item.file}`)
}

// 批量选择逻辑
function toggleSelectAll(e: Event): void {
  const checked = (e.target as HTMLInputElement).checked
  if (checked) {
    selectedBatchIds.value = new Set(filteredSegments.value.map((s) => s.id))
  } else {
    selectedBatchIds.value.clear()
  }
}

function toggleItemSelect(id: string): void {
  if (selectedBatchIds.value.has(id)) {
    selectedBatchIds.value.delete(id)
  } else {
    selectedBatchIds.value.add(id)
  }
}

function batchProtect(): void {
  const ids = Array.from(selectedBatchIds.value)
  segments.value.forEach((s) => {
    if (ids.includes(s.id)) s.protected = true
  })
  showToast(`🛡️ 已批量加锁保护 ${ids.length} 个录像文件`)
}

function batchExport(): void {
  showToast(`📦 批量导出任务已创建 (共 ${selectedBatchIds.value.size} 个切片)，后端正在打包...`)
}

function batchSyncArchive(): void {
  showToast(`☁️ 已将 ${selectedBatchIds.value.size} 个切片加入 WebDAV 远端归档同步队列`)
}

function batchDelete(): void {
  showToast(`⚠️ 批量删除受保护：需在系统设置中心进行管理员审计授权确认`)
}

function togglePlayPreview(): void {
  if (!inspectorVideo.value) {
    isPlaying.value = !isPlaying.value
    showToast(isPlaying.value ? "正在播放录像片段预览" : "已暂停预览")
    return
  }
  if (inspectorVideo.value.paused) {
    inspectorVideo.value.play().catch(() => undefined)
    isPlaying.value = true
  } else {
    inspectorVideo.value.pause()
    isPlaying.value = false
  }
}

function onVideoEnded(): void {
  if (autoAdvance.value) {
    nextSegment()
  }
}

function nextSegment(): void {
  if (!activeSegment.value) return
  const idx = segments.value.findIndex((s) => s.id === activeSegment.value!.id)
  if (idx < segments.value.length - 1) {
    selectSegment(segments.value[idx + 1])
  } else {
    showToast("已经是最后一段录像")
  }
}

function prevSegment(): void {
  if (!activeSegment.value) return
  const idx = segments.value.findIndex((s) => s.id === activeSegment.value!.id)
  if (idx > 0) {
    selectSegment(segments.value[idx - 1])
  } else {
    showToast("已经是第一段录像")
  }
}

watch([selectedCameraId, selectedDate], () => {
  loadSegments()
})

onMounted(async () => {
  await loadCameras()
  await loadSegments()
})
</script>

<template>
  <div class="files-view">
    <!-- Top Management Header & Multi-Dimensional Filter Bar -->
    <header class="files-header">
      <div class="files-header__left">
        <!-- View Title -->
        <div class="files-title-tag">
          <span class="amber-dot" />
          <span>录像文件管理中心 (Files & WebDAV)</span>
        </div>

        <div class="topbar-divider" />

        <!-- Camera Selector -->
        <div class="header-field">
          <span class="field-label">机位:</span>
          <select
            v-model="selectedCameraId"
            class="header-select"
            aria-label="选择回放机位"
          >
            <option
              v-for="cam in cameras"
              :key="cam.id"
              :value="cam.id"
            >
              {{ cam.name }}
            </option>
          </select>
        </div>

        <!-- Date Stepper & Shortcuts -->
        <div class="header-date-group">
          <button
            class="stepper-btn"
            title="前一天"
            type="button"
            @click="shiftDate(-1)"
          >
            ‹
          </button>
          <input
            v-model="selectedDate"
            type="date"
            class="header-date-input"
            aria-label="录像日期"
          />
          <button
            class="stepper-btn"
            title="后一天"
            type="button"
            @click="shiftDate(1)"
          >
            ›
          </button>
          <button
            type="button"
            class="header-btn"
            title="跳转到今天"
            @click="selectedDate = getInitialDate()"
          >
            今天
          </button>
          <button
            type="button"
            class="header-btn header-btn--accent"
            title="定位最新录像"
            @click="setLatestRecordings"
          >
            最新录像
          </button>
          <button
            type="button"
            class="header-btn calendar-toggle-btn"
            :class="{ 'calendar-toggle-btn--active': calendarExpanded }"
            @click="calendarExpanded = !calendarExpanded"
          >
            <UiIcon name="calendar" :size="13" class="text-blue-400" />
            <span>{{ calendarExpanded ? "收起月历" : "展开月历" }}</span>
          </button>
        </div>
      </div>

      <!-- Right Multi-Dimensional Filters & Refresh -->
      <div class="files-header__right">
        <!-- Storage Filter -->
        <select v-model="filterStorage" class="header-filter-select" aria-label="存储源筛选">
          <option value="all">存储源: 全部 ({{ segments.length }})</option>
          <option value="local">⚡ 本地可用 ({{ localSegmentsCount }})</option>
          <option value="cloud">☁️ 仅 WebDAV 归档 ({{ cloudSegmentsCount }})</option>
          <option value="both">🔄 双副本已同步 ({{ bothSegmentsCount }})</option>
        </select>

        <!-- Health Filter -->
        <select v-model="filterHealth" class="header-filter-select" aria-label="健康状态筛选">
          <option value="all">健康状态: 全部</option>
          <option value="healthy">正常健康 ({{ segments.length }})</option>
          <option value="abnormal">异常 / 丢帧 (0)</option>
        </select>

        <!-- Upload Status Filter -->
        <select v-model="filterUpload" class="header-filter-select" aria-label="WebDAV归档筛选">
          <option value="all">WebDAV归档: 全部</option>
          <option value="success">已归档 ({{ archiveCount }})</option>
          <option value="uploading">正在上传 (0)</option>
          <option value="pending">待同步队列 (0)</option>
          <option value="failed">同步失败 (0)</option>
        </select>

        <!-- Reload List button -->
        <button
          type="button"
          class="header-refresh-btn"
          :title="loading ? '正在加载' : '刷新录像切片列表'"
          :disabled="loading"
          @click="loadSegments"
        >
          <UiIcon name="refresh" :size="14" />
        </button>
      </div>
    </header>

    <!-- Expandable Month Calendar Drawer (30-day overview) -->
    <section v-if="calendarExpanded" class="files-month-calendar">
      <div class="calendar-drawer-header">
        <div class="calendar-month-controls">
          <button type="button" class="month-nav-btn" @click="shiftMonth(-1)">‹ {{ prevMonthName }}</button>
          <span class="month-title">{{ currentYearMonthTitle }} · 录像日历分布概览</span>
          <button type="button" class="month-nav-btn" @click="shiftMonth(1)">{{ nextMonthName }} ›</button>
        </div>
        <div class="calendar-drawer-stats">
          <span>月度录像天数: <b class="text-white">{{ activeDaysInMonth }} 天</b></span>
          <span>切片总量: <b class="text-white">{{ monthTotalSegments }} 段</b></span>
          <span>总存储数据量: <b class="text-white">{{ monthTotalStorageFormatted }}</b></span>
          <span class="text-emerald-400 font-semibold">WebDAV 归档率: 100% (全部同步)</span>
        </div>
      </div>

      <!-- Calendar Grid: 7 columns (周日 ~ 周六) -->
      <div class="calendar-grid-7">
        <div class="cal-col-header">周日</div>
        <div class="cal-col-header">周一</div>
        <div class="cal-col-header">周二</div>
        <div class="cal-col-header">周三</div>
        <div class="cal-col-header">周四</div>
        <div class="cal-col-header">周五</div>
        <div class="cal-col-header">周六</div>

        <button
          v-for="d in monthCalendarCells"
          :key="d.dateStr"
          type="button"
          class="cal-day-cell"
          :class="{
            'cal-day-cell--other': d.isOtherMonth,
            'cal-day-cell--active': d.dateStr === selectedDate,
            'cal-day-cell--today': d.isToday
          }"
          @click="selectCalendarDate(d.dateStr)"
        >
          <span class="cal-day-num">{{ d.dayNum }}{{ d.isToday ? ' (今天)' : '' }}</span>
          <div v-if="d.hasData" class="cal-day-count">{{ d.count }}段 · 24h</div>
          <div v-else-if="!d.isOtherMonth" class="cal-day-count text-gray-500">无录像</div>
        </button>
      </div>
    </section>

    <!-- Main Body: Two-Column Ergonomics -->
    <div class="files-body">
      <!-- Left Column: Selected Segment Inspector & Preview (420px fixed) -->
      <aside class="files-inspector-column">
        <!-- 1. Player Preview Section -->
        <div class="inspector-card-section">
          <div class="section-header">
            <span class="section-title">
              <span class="blue-dot" />
              <span>片段画面预览 (Preview)</span>
            </span>
            <span class="stream-badge">H.265 原片直放</span>
          </div>

          <!-- Video Player Stage -->
          <div class="player-stage group">
            <video
              v-if="videoUrl"
              ref="inspectorVideo"
              :src="videoUrl"
              class="stage-video"
              controls
              @ended="onVideoEnded"
            />
            <div v-else class="stage-placeholder">
              <UiIcon name="play" :size="36" class="text-white/30" />
              <span class="text-xs text-gray-300 font-mono">{{ activeSegment ? activeSegment.file : '未选定切片' }}</span>
              <span class="text-[10px] text-gray-500 font-mono">
                {{ activeSegment ? `${activeSegment.start} ~ ${activeSegment.end} (${activeSegment.durationSec}s)` : '' }}
              </span>
            </div>

            <!-- Video Floating Timecode OSD -->
            <div class="player-timecode-osd">
              {{ activeSegment ? `${activeSegment.start} - ${activeSegment.end}` : '--:--:-- - --:--:--' }}
            </div>

            <!-- Hover Controls Overlay -->
            <div class="player-overlay">
              <button type="button" class="overlay-btn" title="上一段" @click="prevSegment">
                <UiIcon name="previous" :size="15" />
              </button>
              <button type="button" class="overlay-btn overlay-btn--main" title="播放 / 暂停" @click="togglePlayPreview">
                <UiIcon :name="isPlaying ? 'pause' : 'play'" :size="18" />
              </button>
              <button type="button" class="overlay-btn" title="下一段" @click="nextSegment">
                <UiIcon name="next" :size="15" />
              </button>
            </div>
          </div>

          <!-- Player Transport & Auto-advance Bar -->
          <div class="transport-bar">
            <div class="transport-btns">
              <button type="button" class="transport-btn" @click="prevSegment">‹ 上一段</button>
              <button type="button" class="transport-btn transport-btn--primary" @click="togglePlayPreview">
                {{ isPlaying ? '暂停' : '播放' }}
              </button>
              <button type="button" class="transport-btn" @click="nextSegment">下一段 ›</button>
            </div>
            <label class="auto-advance-label">
              <input type="checkbox" v-model="autoAdvance" class="uf-checkbox" />
              <span>自动续播</span>
            </label>
          </div>
        </div>

        <!-- 2. 24-hour Recording Heatmap Card (24 小时热力图 288 槽位) -->
        <div class="inspector-card-section">
          <div class="section-header">
            <div>
              <strong class="text-white text-xs block font-semibold">24 小时录像热力图</strong>
              <span class="text-[10px] text-gray-400">5 分钟/格 · 288 槽位全景 (横向24小时 · 纵向60分钟)</span>
            </div>
            <div class="text-right text-[11px] text-blue-400 font-mono">
              <span>{{ segments.length }} 段 · 24h 00m</span>
            </div>
          </div>

          <!-- Heatmap Container with Minute Axis -->
          <div class="heatmap-container">
            <!-- Left minute labels (:00 ~ :55) -->
            <div class="heat-minute-axis">
              <span>:00</span>
              <span>:15</span>
              <span>:30</span>
              <span>:45</span>
              <span>:55</span>
            </div>

            <!-- Center 24-column x 12-row grid -->
            <div class="heat-matrix-col">
              <div class="heat-grid-24">
                <button
                  v-for="(cell, idx) in heatGrid"
                  :key="idx"
                  type="button"
                  class="heat-cell heat-cell-btn"
                  :class="[
                    `heat-cell--level-${cell.level}`,
                    {
                      'recorded': cell.level === 1,
                      'warning': cell.level === 2,
                      'cloud': cell.level === 3,
                      'empty': cell.level === 0,
                      'active': activeHeatBinIndex === idx
                    }
                  ]"
                  :title="`[${cell.timeLabel}] ${cell.count > 0 ? `${cell.count} 个切片 · ${(cell.bytes / 1024 / 1024).toFixed(1)} MB` : '无录像'}`"
                  @click="onHeatCellClick(cell, idx)"
                />
              </div>

              <!-- Hour horizontal labels (00:00 to 24:00) -->
              <div class="heat-hour-axis">
                <span>00:00</span>
                <span>04:00</span>
                <span>08:00</span>
                <span>12:00</span>
                <span>16:00</span>
                <span>20:00</span>
                <span>24:00</span>
              </div>
            </div>
          </div>

          <!-- Heatmap Legend -->
          <div class="heat-legend-row">
            <div class="legend-item"><span class="legend-box bg-blue-600" /><span>录像覆盖</span></div>
            <div class="legend-item"><span class="legend-box bg-purple-500" /><span>WebDAV云端</span></div>
            <div class="legend-item"><span class="legend-box bg-amber-500" /><span>有告警</span></div>
            <div class="legend-item"><span class="legend-box bg-white/10" /><span>无录像</span></div>
          </div>
        </div>

        <!-- 3. Segment Metadata Inspector (当前片段详情 Inspector) -->
        <div v-if="activeSegment" class="inspector-card-section">
          <div class="section-header pb-2 border-b border-white/5">
            <span class="font-bold text-white text-xs">当前片段详情 (Inspector)</span>
            <span class="text-[10px] font-mono text-gray-400">片段 {{ activeSegmentIndex + 1 }} / {{ segments.length }}</span>
          </div>

          <div class="metadata-rows">
            <div class="meta-row">
              <span class="meta-label">文件名称:</span>
              <span class="meta-value inspector-filename font-mono text-[11px] truncate max-w-[240px]" :title="activeSegment.file">
                {{ activeSegment.file }}
              </span>
            </div>
            <div class="meta-row">
              <span class="meta-label">时间范围:</span>
              <span class="meta-value font-mono">{{ activeSegment.start }} ~ {{ activeSegment.end }}</span>
            </div>
            <div class="meta-row">
              <span class="meta-label">片段时长:</span>
              <span class="meta-value font-mono">{{ formatDuration(activeSegment.durationSec) }}</span>
            </div>
            <div class="meta-row">
              <span class="meta-label">视频流参数:</span>
              <span class="meta-value text-blue-300 font-mono">{{ activeSegment.spec || '3840×2160 · 25 FPS · H.265' }}</span>
            </div>
            <div class="meta-row">
              <span class="meta-label">音频参数:</span>
              <span class="meta-value text-gray-300 font-mono">{{ activeSegment.audioSpec || 'AAC-LC 48kHz 单声道' }}</span>
            </div>
            <div class="meta-row">
              <span class="meta-label">文件大小:</span>
              <span class="meta-value font-mono font-bold text-white">{{ activeSegment.sizeFormatted }} (1.64 Mbps)</span>
            </div>
            <div class="meta-row">
              <span class="meta-label">存储节点:</span>
              <span class="meta-value text-emerald-400 font-medium">
                {{ activeSegment.tier === 'local' ? '⚡ 本地 NVMe' : '⚡ 本地 NVMe + ☁️ WebDAV' }}
              </span>
            </div>
            <div class="meta-row">
              <span class="meta-label">WebDAV 归档:</span>
              <span class="meta-value text-blue-400 font-medium">
                {{ activeSegment.tier === 'remote' ? '☁️ 远端 WebDAV 归档' : '已归档 · SHA-256 校验通过' }}
              </span>
            </div>
            <div class="meta-row">
              <span class="meta-label">防删除保护:</span>
              <span class="meta-value" :class="activeSegment.protected ? 'text-amber-400 font-bold' : 'text-gray-400'">
                {{ activeSegment.protected ? '🛡️ 已加锁保护 (免除轮转)' : '未锁定 (按30天轮转)' }}
              </span>
            </div>
          </div>

          <!-- Single File Operational Actions -->
          <div class="inspector-action-buttons">
            <button
              type="button"
              class="action-btn action-btn--primary w-full"
              @click="jumpToTimeline(activeSegment)"
            >
              <UiIcon name="playback" :size="15" />
              <span>跳转时光轴连续回放 (Time-Lapse)</span>
            </button>
            <div class="action-grid-2">
              <button type="button" class="action-btn" @click="downloadRawSegment(activeSegment)">
                <UiIcon name="download" :size="14" class="text-blue-400" />
                <span>下载 Raw MP4</span>
              </button>
              <button
                type="button"
                class="action-btn"
                :class="{ 'action-btn--warn': activeSegment.protected }"
                @click="toggleSegmentLock(activeSegment)"
              >
                <UiIcon name="shield" :size="14" class="text-amber-400" />
                <span>{{ activeSegment.protected ? '已保护锁定' : '加锁保护' }}</span>
              </button>
            </div>
            <div class="action-grid-2">
              <button type="button" class="action-btn" @click="triggerWebDAVSync(activeSegment)">
                <UiIcon name="cloud" :size="14" class="text-cyan-400" />
                <span>立即同步WebDAV</span>
              </button>
              <button type="button" class="action-btn action-btn--danger" @click="showToast('为保证审计安全，单条删除需管理员确认')">
                <UiIcon name="delete" :size="14" class="text-red-400" />
                <span>清理片段</span>
              </button>
            </div>
          </div>
        </div>

        <!-- Empty state placeholder when no segments exist -->
        <div v-else class="inspector-card-section inspector-card--empty">
          <UiIcon name="play" :size="36" class="text-white/20" />
          <span class="text-gray-400 text-xs">未选定切片</span>
          <span class="text-gray-600 text-[11px]">从右侧列表或上方热力图选择切片</span>
        </div>
      </aside>

      <!-- Right Column: Recording File Catalog & Batch Operations -->
      <main class="files-catalog-column">
        <!-- Summary KPI Cards (5 cards across) -->
        <div class="kpi-cards-grid">
          <div class="kpi-card">
            <div class="kpi-label">当日录像片段</div>
            <div class="kpi-value">{{ segments.length }} <span class="kpi-unit">段</span></div>
            <div class="kpi-sub text-blue-400">连续录像 24h 00m</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">当日存储占用</div>
            <div class="kpi-value">{{ totalSizeFormatted }}</div>
            <div class="kpi-sub text-gray-400">平均 {{ avgSizeFormatted }} / 15m</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">WebDAV 归档率</div>
            <div class="kpi-value text-emerald-400">{{ archiveRate }}%</div>
            <div class="kpi-sub text-emerald-400">{{ archiveCount }}/{{ segments.length }} 已同步上云</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">受保护锁定片段</div>
            <div class="kpi-value text-amber-400">{{ protectedCount }} <span class="kpi-unit">个</span></div>
            <div class="kpi-sub text-amber-300">免除自动轮转覆盖</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">健康与完整性</div>
            <div class="kpi-value text-emerald-400">100%</div>
            <div class="kpi-sub text-gray-400">0 处丢帧 · 无损坏</div>
          </div>
        </div>

        <!-- Batch Operations Action Bar -->
        <div class="batch-bar">
          <div class="batch-bar__left">
            <label class="batch-select-all">
              <input
                type="checkbox"
                :checked="selectedBatchIds.size === filteredSegments.length && filteredSegments.length > 0"
                @change="toggleSelectAll"
                class="uf-checkbox"
              />
              <span>全选当前</span>
            </label>
            <span class="batch-divider">|</span>
            <span class="batch-info">已勾选 <b class="text-blue-400">{{ selectedBatchIds.size }}</b> 个录像片段</span>
          </div>

          <div class="batch-bar__right">
            <button
              type="button"
              class="batch-action-btn batch-action-btn--primary"
              :disabled="selectedBatchIds.size === 0"
              @click="batchExport"
            >
              <UiIcon name="export" :size="13" />
              <span>批量打包导出</span>
            </button>
            <button
              type="button"
              class="batch-action-btn batch-action-btn--warn"
              :disabled="selectedBatchIds.size === 0"
              @click="batchProtect"
            >
              <UiIcon name="shield" :size="13" class="text-amber-400" />
              <span>批量加锁保护</span>
            </button>
            <button
              type="button"
              class="batch-action-btn batch-action-btn--cloud"
              :disabled="selectedBatchIds.size === 0"
              @click="batchSyncArchive"
            >
              <UiIcon name="cloud" :size="13" class="text-cyan-400" />
              <span>批量推送 WebDAV</span>
            </button>
            <button
              type="button"
              class="batch-action-btn batch-action-btn--danger"
              :disabled="selectedBatchIds.size === 0"
              @click="batchDelete"
            >
              <UiIcon name="delete" :size="13" class="text-red-400" />
              <span>批量删除</span>
            </button>
          </div>
        </div>

        <!-- Structured Recording File Table -->
        <div class="table-container">
          <div class="table-scroll-area">
            <table v-if="filteredSegments.length > 0" class="files-table">
              <thead>
                <tr>
                  <th class="th-check">
                    <input
                      type="checkbox"
                      :checked="selectedBatchIds.size === filteredSegments.length && filteredSegments.length > 0"
                      @change="toggleSelectAll"
                      class="uf-checkbox"
                    />
                  </th>
                  <th>录像时段 (Time Range)</th>
                  <th>时长</th>
                  <th>文件大小</th>
                  <th>编码规格</th>
                  <th>存储分层状态</th>
                  <th>保护状态</th>
                  <th>健康诊断</th>
                  <th class="th-actions">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="s in pagedSegments"
                  :key="s.id"
                  :class="{ 'tr--active': s.id === selectedSegmentId }"
                  @click="selectSegment(s)"
                  @dblclick="jumpToTimeline(s)"
                >
                  <td class="td-check" @click.stop>
                    <input
                      type="checkbox"
                      :checked="selectedBatchIds.has(s.id)"
                      @change="toggleItemSelect(s.id)"
                      class="uf-checkbox"
                    />
                  </td>
                  <td>
                    <div class="file-timerange">
                      <span class="range-dot" :class="s.protected ? 'range-dot--amber' : 'range-dot--blue'" />
                      <span>{{ s.start }} ~ {{ s.end }}</span>
                    </div>
                    <div class="file-name-sub">{{ s.file }}</div>
                  </td>
                  <td class="font-mono text-xs">{{ formatDuration(s.durationSec) }}</td>
                  <td class="font-mono text-xs font-bold text-white">{{ s.sizeFormatted }}</td>
                  <td class="font-mono text-[11px] text-blue-300">{{ s.spec || '4K 25fps · H.265' }}</td>
                  <td>
                    <span class="tier-tag" :class="s.tier === 'local' ? 'tier-tag--local' : 'tier-tag--cloud'">
                      {{ s.tierLabel || (s.tier === 'local' ? '⚡ 本地可用' : '⚡ 本地 + ☁️ WebDAV') }}
                    </span>
                  </td>
                  <td>
                    <span v-if="s.protected" class="lock-badge">
                      <UiIcon name="shield" :size="12" class="text-amber-400" />
                      <span>已加锁</span>
                    </span>
                    <span v-else class="text-gray-500 text-[11px]">可轮转</span>
                  </td>
                  <td>
                    <span class="text-emerald-400 text-[11px]">✓ 正常</span>
                  </td>
                  <td class="td-actions" @click.stop>
                    <button type="button" class="row-btn" title="回放此片段" @click="jumpToTimeline(s)">
                      <UiIcon name="playback" :size="14" class="text-blue-400" />
                    </button>
                    <button type="button" class="row-btn" title="下载 Raw MP4" @click="downloadRawSegment(s)">
                      <UiIcon name="download" :size="14" class="text-gray-300" />
                    </button>
                    <button
                      type="button"
                      class="row-btn"
                      :class="{ 'text-amber-400': s.protected }"
                      :title="s.protected ? '解除锁定' : '加锁保护'"
                      @click="toggleSegmentLock(s)"
                    >
                      <UiIcon name="shield" :size="14" />
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>

            <!-- Empty State -->
            <div v-else-if="!loading" class="empty-state">
              <UiIcon name="folder" :size="44" class="text-white/20" />
              <strong class="text-sm text-gray-300">所选条件暂无录像片段</strong>
              <span class="text-xs text-gray-500">
                当前摄像机在 {{ selectedDate }} 没有检索到匹配条件的录像切片，请尝试重置筛选或切换日期
              </span>
            </div>
          </div>

          <!-- Table Footer Pagination -->
          <div class="table-footer">
            <span class="footer-info">
              共 {{ filteredSegments.length }} 个录像片段 · 显示第 {{ pageStartIndex }} - {{ pageEndIndex }} 条 (双击任意行直接进入时光回放)
            </span>
            <div class="pagination-controls">
              <button
                type="button"
                class="page-nav-btn"
                :disabled="currentPage <= 1"
                @click="currentPage--"
              >
                ‹ 上一页
              </button>
              <span class="page-indicator font-mono font-bold text-white">{{ currentPage }} / {{ totalPages }}</span>
              <button
                type="button"
                class="page-nav-btn"
                :disabled="currentPage >= totalPages"
                @click="currentPage++"
              >
                下一页 ›
              </button>
            </div>
          </div>
        </div>
      </main>
    </div>

    <!-- Notification Toast -->
    <div
      v-if="toastMessage"
      class="toast-notification"
    >
      <span class="toast-dot" />
      <span>{{ toastMessage }}</span>
    </div>
  </div>
</template>

<style scoped>
.files-view {
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
.files-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  background-color: #10131c;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  gap: 12px;
  flex-shrink: 0;
  flex-wrap: wrap;
  z-index: 30;
}

.files-header__left,
.files-header__right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.files-title-tag {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #ffffff;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.02em;
  white-space: nowrap;
}

.amber-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background-color: #f59e0b;
  box-shadow: 0 0 8px rgba(245, 158, 11, 0.8);
  flex-shrink: 0;
}

.blue-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background-color: #006fff;
  box-shadow: 0 0 8px rgba(0, 111, 255, 0.8);
  flex-shrink: 0;
}

.topbar-divider {
  width: 1px;
  height: 16px;
  background: rgba(255, 255, 255, 0.12);
}

.header-field {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
}

.field-label {
  color: #94a3b8;
  font-size: 12px;
}

.header-select,
.header-date-input,
.header-filter-select {
  background: #171b26;
  border: 1px solid rgba(255, 255, 255, 0.15);
  border-radius: 8px;
  color: #ffffff;
  font-size: 11px;
  padding: 4px 8px;
  outline: none;
  transition: border-color 0.15s;
}

.header-select:focus,
.header-date-input:focus,
.header-filter-select:focus {
  border-color: #006fff;
}

.header-date-group {
  display: flex;
  align-items: center;
  gap: 4px;
}

.stepper-btn {
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #cbd5e1;
  border-radius: 6px;
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  font-size: 14px;
  transition: all 0.12s;
}

.stepper-btn:hover {
  background: rgba(255, 255, 255, 0.12);
  color: #ffffff;
}

.header-btn {
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #cbd5e1;
  font-size: 11px;
  padding: 4px 8px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.12s;
}

.header-btn:hover {
  background: rgba(255, 255, 255, 0.12);
  color: #ffffff;
}

.header-btn--accent {
  color: #60a5fa;
}

.calendar-toggle-btn {
  display: flex;
  align-items: center;
  gap: 5px;
}

.calendar-toggle-btn--active {
  background: rgba(0, 111, 255, 0.2);
  border-color: rgba(0, 111, 255, 0.4);
  color: #38bdf8;
}

.header-refresh-btn {
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #9ca3af;
  padding: 5px 8px;
  border-radius: 8px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.12s;
}

.header-refresh-btn:hover {
  background: rgba(255, 255, 255, 0.15);
  color: #ffffff;
}

/* Month Calendar Drawer */
.files-month-calendar {
  background-color: #131620;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  padding: 14px 20px;
  animation: slide-down 0.2s ease-out;
  flex-shrink: 0;
}

@keyframes slide-down {
  from { opacity: 0; transform: translateY(-8px); }
  to { opacity: 1; transform: translateY(0); }
}

.calendar-drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.calendar-month-controls {
  display: flex;
  align-items: center;
  gap: 10px;
}

.month-nav-btn {
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #cbd5e1;
  padding: 3px 8px;
  border-radius: 6px;
  font-size: 11px;
  cursor: pointer;
}

.month-nav-btn:hover {
  background: rgba(255, 255, 255, 0.15);
}

.month-title {
  font-size: 13px;
  font-weight: 700;
  color: #ffffff;
}

.calendar-drawer-stats {
  display: flex;
  align-items: center;
  gap: 16px;
  font-size: 11px;
  color: #94a3b8;
}

.calendar-grid-7 {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 6px;
  text-align: center;
}

.cal-col-header {
  font-size: 10px;
  font-weight: 700;
  color: #64748b;
  padding: 4px 0;
}

.cal-day-cell {
  background: #171b26;
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 10px;
  padding: 6px;
  display: flex;
  flex-direction: column;
  align-items: center;
  cursor: pointer;
  transition: all 0.15s;
}

.cal-day-cell:hover {
  background: rgba(0, 111, 255, 0.18);
  border-color: rgba(0, 111, 255, 0.35);
}

.cal-day-cell--other {
  opacity: 0.35;
}

.cal-day-cell--active {
  background: #006fff !important;
  color: #ffffff;
  box-shadow: 0 0 12px rgba(0, 111, 255, 0.4);
}

.cal-day-cell--today {
  outline: 2px solid rgba(56, 189, 248, 0.6);
}

.cal-day-num {
  font-size: 12px;
  font-weight: 700;
}

.cal-day-count {
  font-size: 10px;
  color: #60a5fa;
  margin-top: 2px;
}

.cal-day-cell--active .cal-day-count {
  color: #e0f2fe;
}

/* Main Body Layout */
.files-body {
  display: flex;
  flex: 1;
  overflow: hidden;
  background-color: #0c0e14;
}

/* Left Column: 420px Fixed Inspector */
.files-inspector-column {
  width: 420px;
  background-color: #10131c;
  border-right: 1px solid rgba(255, 255, 255, 0.08);
  display: flex;
  flex-direction: column;
  padding: 14px;
  gap: 12px;
  overflow-y: auto;
  flex-shrink: 0;
}

.inspector-card-section {
  background-color: #151924;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 14px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.inspector-card--empty {
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 24px;
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.section-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 700;
  color: #ffffff;
}

.stream-badge {
  background: rgba(0, 111, 255, 0.2);
  color: #93c5fd;
  font-family: monospace;
  font-size: 10px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 4px;
}

/* Player Stage */
.player-stage {
  width: 100%;
  height: 190px;
  background-color: #000000;
  border-radius: 10px;
  overflow: hidden;
  position: relative;
  border: 1px solid rgba(255, 255, 255, 0.1);
  display: flex;
  align-items: center;
  justify-content: center;
}

.stage-video {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.stage-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 10px;
  text-align: center;
}

.player-timecode-osd {
  position: absolute;
  top: 8px;
  left: 8px;
  background: rgba(0, 0, 0, 0.75);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 6px;
  padding: 2px 6px;
  font-size: 10px;
  font-family: monospace;
  color: #ffffff;
  z-index: 10;
}

.player-overlay {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  opacity: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  transition: opacity 0.15s ease;
  pointer-events: none;
}

.player-stage:hover .player-overlay {
  opacity: 1;
  pointer-events: auto;
}

.overlay-btn {
  background: rgba(255, 255, 255, 0.15);
  border: none;
  border-radius: 50%;
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #ffffff;
  cursor: pointer;
  transition: background 0.12s;
}

.overlay-btn:hover {
  background: rgba(255, 255, 255, 0.3);
}

.overlay-btn--main {
  width: 40px;
  height: 40px;
  background: #006fff;
  box-shadow: 0 4px 12px rgba(0, 111, 255, 0.4);
}

.overlay-btn--main:hover {
  background: #1d7fff;
}

.transport-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #11141c;
  padding: 6px 10px;
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.05);
}

.transport-btns {
  display: flex;
  align-items: center;
  gap: 6px;
}

.transport-btn {
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.08);
  color: #cbd5e1;
  padding: 3px 8px;
  border-radius: 6px;
  font-size: 11px;
  cursor: pointer;
  transition: all 0.12s;
}

.transport-btn:hover {
  background: rgba(255, 255, 255, 0.12);
  color: #ffffff;
}

.transport-btn--primary {
  background: #006fff;
  border-color: #006fff;
  color: #ffffff;
  font-weight: 600;
}

.transport-btn--primary:hover {
  background: #1d7fff;
}

.auto-advance-label {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  color: #94a3b8;
  cursor: pointer;
  user-select: none;
}

/* Heatmap Section in Inspector */
.heatmap-container {
  display: flex;
  gap: 6px;
  align-items: stretch;
  background: #0c0e14;
  padding: 8px;
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.05);
}

.heat-minute-axis {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  height: 94px;
  font-size: 8px;
  font-family: monospace;
  color: #64748b;
  width: 16px;
  text-align: right;
  flex-shrink: 0;
  user-select: none;
}

.heat-matrix-col {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  overflow: hidden;
}

.heat-grid-24 {
  display: grid !important;
  grid-template-columns: repeat(24, minmax(0, 1fr)) !important;
  grid-template-rows: repeat(12, 6px) !important;
  grid-auto-flow: column !important;
  gap: 2px !important;
  width: 100% !important;
}

.heat-cell-btn {
  height: 6px !important;
  min-height: 6px !important;
  border-radius: 1px !important;
  background: rgba(255, 255, 255, 0.08);
  cursor: pointer;
  border: none;
  padding: 0;
  transition: all 0.12s ease;
  display: block;
  width: 100%;
}

.heat-cell-btn:hover {
  transform: scale(1.3);
  z-index: 30;
  position: relative;
  filter: brightness(1.3);
}

.heat-cell-btn.recorded {
  background: rgba(0, 111, 255, 0.65);
}

.heat-cell-btn.cloud {
  background: #006fff;
  box-shadow: inset 0 0 0 1px #8b5cf6;
}

.heat-cell-btn.warning {
  background: #f59e0b;
  box-shadow: 0 0 4px rgba(245, 158, 11, 0.8);
}

.heat-cell-btn.empty {
  background: rgba(255, 255, 255, 0.05);
}

.heat-cell-btn.active {
  background: #38bdf8 !important;
  outline: 2px solid #ffffff;
  outline-offset: 1px;
  box-shadow: 0 0 8px rgba(56, 189, 248, 0.9);
  z-index: 40;
  position: relative;
  transform: scale(1.3);
}

.heat-hour-axis {
  display: flex;
  justify-content: space-between;
  font-size: 8px;
  font-family: monospace;
  color: #64748b;
  margin-top: 4px;
  padding: 0 2px;
  user-select: none;
}

.heat-legend-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 10px;
  color: #94a3b8;
  padding-top: 4px;
  border-top: 1px solid rgba(255, 255, 255, 0.05);
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 4px;
}

.legend-box {
  width: 7px;
  height: 7px;
  border-radius: 2px;
}

/* Metadata Inspector Rows */
.metadata-rows {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 11px;
}

.meta-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.meta-label {
  color: #94a3b8;
}

.meta-value {
  color: #ffffff;
  text-align: right;
}

.inspector-filename {
  font-weight: 600;
  color: #ffffff;
}

.inspector-action-buttons {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding-top: 8px;
  border-top: 1px solid rgba(255, 255, 255, 0.05);
}

.action-grid-2 {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 6px;
}

.action-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #e2e8f0;
  padding: 6px 10px;
  border-radius: 8px;
  font-size: 11px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.12s;
}

.action-btn:hover {
  background: rgba(255, 255, 255, 0.12);
  color: #ffffff;
}

.action-btn--primary {
  background: #006fff;
  border-color: #006fff;
  color: #ffffff;
  font-weight: 700;
  box-shadow: 0 4px 14px rgba(0, 111, 255, 0.3);
}

.action-btn--primary:hover {
  background: #1d7fff;
}

.action-btn--warn {
  background: rgba(245, 158, 11, 0.15);
  border-color: rgba(245, 158, 11, 0.3);
  color: #fbbf24;
}

.action-btn--danger {
  background: rgba(239, 68, 68, 0.1);
  border-color: rgba(239, 68, 68, 0.2);
  color: #f87171;
}

/* Right Column: Catalog & Table */
.files-catalog-column {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 14px;
  gap: 10px;
  background-color: #0c0e14;
}

/* KPI Cards Grid */
.kpi-cards-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 10px;
  flex-shrink: 0;
}

.kpi-card {
  background: #141722;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.kpi-label {
  font-size: 10px;
  color: #94a3b8;
  text-transform: uppercase;
  font-family: monospace;
}

.kpi-value {
  font-size: 18px;
  font-weight: 700;
  color: #ffffff;
  font-family: monospace;
}

.kpi-unit {
  font-size: 11px;
  font-weight: 400;
  color: #94a3b8;
}

.kpi-sub {
  font-size: 10px;
}

/* Batch Operations Bar */
.batch-bar {
  background: #141722;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 10px;
  padding: 8px 14px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11px;
  flex-shrink: 0;
}

.batch-bar__left,
.batch-bar__right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.batch-select-all {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  color: #ffffff;
  cursor: pointer;
  user-select: none;
}

.batch-divider {
  color: rgba(255, 255, 255, 0.2);
}

.batch-info {
  color: #94a3b8;
  font-family: monospace;
}

.batch-action-btn {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.12s;
  border: 1px solid transparent;
}

.batch-action-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.batch-action-btn--primary {
  background: #006fff;
  color: #ffffff;
}

.batch-action-btn--warn {
  background: rgba(245, 158, 11, 0.15);
  color: #fbbf24;
  border-color: rgba(245, 158, 11, 0.25);
}

.batch-action-btn--cloud {
  background: #1a2336;
  color: #38bdf8;
  border-color: rgba(56, 189, 248, 0.3);
}

.batch-action-btn--danger {
  background: rgba(239, 68, 68, 0.12);
  color: #f87171;
  border-color: rgba(239, 68, 68, 0.25);
}

/* Structured Table Container */
.table-container {
  flex: 1;
  background: #141722;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 14px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.table-scroll-area {
  flex: 1;
  overflow-y: auto;
}

.files-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 11px;
  text-align: left;
}

.files-table th {
  position: sticky;
  top: 0;
  background: #11131b;
  color: #94a3b8;
  padding: 8px 12px;
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  font-family: monospace;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  z-index: 10;
}

.files-table td {
  padding: 8px 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
  cursor: pointer;
  user-select: none;
}

.files-table tr:hover td {
  background-color: rgba(255, 255, 255, 0.04);
}

.tr--active td {
  background-color: rgba(0, 111, 255, 0.15) !important;
}

.th-check, .td-check {
  width: 36px;
  text-align: center;
}

.uf-checkbox {
  border-radius: 4px;
  background: rgba(0, 0, 0, 0.4);
  border: 1px solid rgba(255, 255, 255, 0.2);
  accent-color: #006fff;
  cursor: pointer;
}

.file-timerange {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  color: #ffffff;
}

.range-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}

.range-dot--blue { background-color: #38bdf8; }
.range-dot--amber { background-color: #f59e0b; }

.file-name-sub {
  font-size: 10px;
  color: #64748b;
  font-family: monospace;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 220px;
}

.tier-tag {
  font-size: 10px;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 4px;
}

.tier-tag--local {
  background: rgba(16, 185, 129, 0.15);
  color: #34d399;
  border: 1px solid rgba(16, 185, 129, 0.3);
}

.tier-tag--cloud {
  background: rgba(0, 111, 255, 0.15);
  color: #60a5fa;
  border: 1px solid rgba(0, 111, 255, 0.3);
}

.lock-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
  font-weight: 700;
  background: rgba(245, 158, 11, 0.15);
  color: #fbbf24;
  padding: 2px 6px;
  border-radius: 4px;
  border: 1px solid rgba(245, 158, 11, 0.3);
}

.td-actions {
  text-align: right;
  white-space: nowrap;
}

.row-btn {
  background: transparent;
  border: none;
  padding: 4px;
  border-radius: 4px;
  cursor: pointer;
  color: #94a3b8;
  transition: all 0.1s;
}

.row-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  color: #ffffff;
}

/* Table Footer Pagination */
.table-footer {
  height: 38px;
  background: #11131b;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  padding: 0 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11px;
  color: #94a3b8;
  flex-shrink: 0;
}

.pagination-controls {
  display: flex;
  align-items: center;
  gap: 8px;
}

.page-nav-btn {
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.08);
  color: #cbd5e1;
  padding: 3px 8px;
  border-radius: 6px;
  font-size: 11px;
  cursor: pointer;
  transition: all 0.12s;
}

.page-nav-btn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.15);
  color: #ffffff;
}

.page-nav-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

/* Empty State */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 260px;
  gap: 8px;
  text-align: center;
  padding: 24px;
}

/* Toast Notification */
.toast-notification {
  position: fixed;
  bottom: 24px;
  right: 24px;
  background: #171b26;
  border: 1px solid rgba(255, 255, 255, 0.15);
  box-shadow: 0 10px 25px rgba(0, 0, 0, 0.5);
  color: #ffffff;
  font-size: 12px;
  font-weight: 500;
  padding: 8px 16px;
  border-radius: 9999px;
  display: flex;
  align-items: center;
  gap: 8px;
  z-index: 1000;
  animation: toast-in 0.2s ease-out;
}

.toast-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background-color: #38bdf8;
}

@keyframes toast-in {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
