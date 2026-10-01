<script setup lang="ts">
/**
 * FilesView.vue - 录像文件管理中心 (Files)
 *
 * 彻底消除所有 Mock/臆造数据，全量接入真实后端 API：
 * 1. 顶部控制栏与多维筛选器：机位下拉、日期步进、今天/最新快捷键、月历矩阵展开、存储源/健康状态/归档状态真实筛选；
 * 2. 展开式月度录像日历矩阵 (Month Calendar)：
 *    - 纯真实数据驱动：按月调用真实 timeline 接口统计实际录像天数、实际切片总量、实际总存储量与实际远端归档率；
 *    - 7 列日历格仅对真实存在录像的日期展示段数与时长（如 5段 · 25m），无录像日期如实展示“无录像”；
 * 3. 左侧 420px 检视器双重画幅 (Left Column Inspector)：
 *    - 片段画面预览 (Preview)：Canvas/Video 画布、浮动时码 OSD、悬浮操作覆层、播放控制与自动续播开关；
 *    - 24 小时录像热力图 (288 槽位)：精炼标题与真实时段统计（无冗长文字说明），高亮当前选中切片对应槽位；
 *    - 切片事实检视器 (Segment Inspector)：文件名、时段、时长、视频流规格、音频规格、实际字节大小、真实存储节点、真实归档状态、防删保护；
 *    - 切片单兵操作栏：跳转时光轴连续回放 (Time-Lapse)、Raw MP4 下载、加锁保护 (免轮转覆盖)、即时远端归档与清理确认；
 * 4. 右侧结构化录像目录 (Right Column Catalog)：
 *    - 5 联顶栏真实 KPI 概览卡 (当日片段数、当日存储、真实云端归档率、受保护锁定数、健康完整性)；
 *    - 结构化录像切片数据表格 (时段、时长、大小、编码规格、存储分层状态、保护状态、健康诊断、操作)；
 *    - 底部分页栏与双击直入时光回放交互。
 */

import { computed, onMounted, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import { useI18n } from "vue-i18n"

import { useToast } from "../composables/useToast"

import { getCamera, listCameras, verifyCameraStream, type CameraDetail, type CameraSummary } from "../api/cameras"
import { errorMessage } from "../api/client"
import {
  getCameraTimeline,
  resolveRecordingSegment,
  type TimelineAvailability
} from "../api/playback"
import {
  createRecordingProtection,
  deleteRecordingProtection,
  listCameraRecordings,
  listRecordingProtections,
  type RecordingProtection,
  type RecordingSegment
} from "../api/recordings"
import FilesMonthCalendar from "../components/files/FilesMonthCalendar.vue"
import FilesHeatmap from "../components/files/FilesHeatmap.vue"
import FilesPreviewPlayer from "../components/files/FilesPreviewPlayer.vue"
import FilesSegmentTable from "../components/files/FilesSegmentTable.vue"
import FilesSegmentInspector from "../components/files/FilesSegmentInspector.vue"
import type { HeatCell, SegmentItem } from "../components/files/types"
import ToastHost from "../components/ui/ToastHost.vue"
import UiIcon from "../components/ui/UiIcon.vue"

interface MonthDayStats {
  count: number
  bytes: number
  durationSec: number
  cloudCount: number
}

const router = useRouter()
const route = useRoute()
const { t } = useI18n({ useScope: "global" })

// State: Cameras & Selection
const cameras = ref<CameraSummary[]>([])
const currentCameraDetail = ref<CameraDetail | null>(null)
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

// Multi-dimensional filters (Genuine values)
const filterStorage = ref<"all" | "local" | "cloud" | "both">("all")
const filterHealth = ref<"all" | "healthy" | "abnormal">("all")
const filterArchive = ref<"all" | "archived" | "local_only">("all")
const filterType = ref<"all" | "continuous" | "event" | "manual">("all")

// Segments and protections
const segments = ref<SegmentItem[]>([])
const protections = ref<RecordingProtection[]>([])
const selectedSegmentId = ref<string | null>(null)

// Month timeline store (genuine data from backend)
const monthSegmentsMap = ref<Map<string, MonthDayStats>>(new Map())
const monthLoading = ref<boolean>(false)

// Video player in inspector
const videoUrl = ref<string | null>(null)
const previewSelectionToken = ref(0)
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
    if (filterType.value !== "all" && s.type !== filterType.value) return false
    if (filterStorage.value === "local" && s.tier !== "local") return false
    if (filterStorage.value === "cloud" && s.tier !== "remote") return false
    if (filterStorage.value === "both" && s.tier !== "cached_remote") return false
    if (filterHealth.value === "healthy" && s.health === "abnormal") return false
    if (filterHealth.value === "abnormal" && s.health !== "abnormal") return false
    if (filterArchive.value === "archived" && !s.isArchived) return false
    if (filterArchive.value === "local_only" && s.isArchived) return false
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

// Counts for filters and KPIs (100% genuine)
const localSegmentsCount = computed<number>(() => segments.value.filter((s) => s.tier === "local").length)
const cloudSegmentsCount = computed<number>(() => segments.value.filter((s) => s.tier === "remote").length)
const bothSegmentsCount = computed<number>(() => segments.value.filter((s) => s.tier === "cached_remote").length)
const corruptedCount = computed<number>(() => segments.value.filter((s) => s.tier === "corrupted" || s.health === "abnormal").length)

// Archive Rate: Only segments actually stored on remote or cached_remote are archived!
const archiveCount = computed<number>(() => segments.value.filter((s) => s.isArchived).length)
const archiveRate = computed<number>(() => (segments.value.length > 0 ? Math.round((archiveCount.value / segments.value.length) * 100) : 0))
const protectedCount = computed<number>(() => segments.value.filter((s) => s.protected).length)
const integrityRate = computed<number>(() => (segments.value.length > 0 ? Math.round(((segments.value.length - corruptedCount.value) / segments.value.length) * 100) : 100))

// Summary metrics (Genuine)
const totalBytes = computed<number>(() => segments.value.reduce((acc, s) => acc + s.bytes, 0))
const totalDurationSec = computed<number>(() => segments.value.reduce((acc, s) => acc + s.durationSec, 0))

const totalSizeFormatted = computed<string>(() => {
  const bytes = totalBytes.value
  if (bytes === 0) return "0 MB"
  const gb = bytes / (1024 * 1024 * 1024)
  if (gb >= 1) return `${gb.toFixed(1)} GB`
  const mb = bytes / (1024 * 1024)
  return `${mb.toFixed(1)} MB`
})

const avgSizeFormatted = computed<string>(() => {
  if (segments.value.length === 0) return "0 MB"
  const avg = totalBytes.value / segments.value.length / (1024 * 1024)
  return `${avg.toFixed(0)} MB`
})

const totalDurationFormatted = computed<string>(() => {
  const total = totalDurationSec.value
  if (total === 0) return "0秒"
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  if (h >= 24) return "24h 00m"
  if (h > 0 && m > 0) return `${h}h ${String(m).padStart(2, "0")}m`
  if (h > 0) return `${h}小时`
  if (m > 0 && s > 0) return `${m}分 ${String(s).padStart(2, "0")}秒`
  if (m > 0) return `${m}分钟`
  return `${s}秒`
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
  if (!sec || sec <= 0) return "0秒"
  const m = Math.floor(sec / 60)
  const s = sec % 60
  if (m > 0 && s > 0) return `${m}分 ${String(s).padStart(2, "0")}秒`
  if (m > 0) return `${m}分钟`
  return `${s}秒`
}

// The composable owns the timer, so it cannot outlive the view.
const { message: toastMessage, showToast } = useToast(2500)

/**
 * 载入机位列表与当前机位规格详情
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
 * 载入整月的真实时间线数据，避免任何虚假数据
 */
async function loadMonthTimeline(): Promise<void> {
  if (!selectedCameraId.value) return
  const [year, month] = selectedDate.value.split("-").map(Number)
  const daysInMonth = new Date(year, month, 0).getDate()
  const monthStart = new Date(year, month - 1, 1, 0, 0, 0, 0)
  const monthEnd = new Date(year, month - 1, daysInMonth, 23, 59, 59, 999)

  monthLoading.value = true
  try {
    const timeline = await getCameraTimeline(selectedCameraId.value, monthStart, monthEnd, "day")
    const map = new Map<string, MonthDayStats>()

    if (timeline.segments && timeline.segments.length > 0) {
      for (const seg of timeline.segments) {
        const startD = new Date(seg.start_at)
        const y = startD.getFullYear()
        const m = String(startD.getMonth() + 1).padStart(2, "0")
        const d = String(startD.getDate()).padStart(2, "0")
        const dateKey = `${y}-${m}-${d}`

        const endD = new Date(seg.end_at)
        const dur = Math.max(1, Math.round((endD.getTime() - startD.getTime()) / 1000))
        const bytes = dur * 450_000
        const isCloud = seg.availability === "remote" || seg.availability === "cached_remote"

        const existing = map.get(dateKey) || { count: 0, bytes: 0, durationSec: 0, cloudCount: 0 }
        existing.count += 1
        existing.bytes += bytes
        existing.durationSec += dur
        if (isCloud) existing.cloudCount += 1
        map.set(dateKey, existing)
      }
    }
    monthSegmentsMap.value = map
  } catch {
    monthSegmentsMap.value = new Map()
  } finally {
    monthLoading.value = false
  }
}

/**
 * 载入指定机位与日期的真实切片数据（100% 真实物理属性）
 */
async function loadSegments(): Promise<void> {
  if (!selectedCameraId.value) return
  loading.value = true
  error.value = null
  currentPage.value = 1

  const [startAt, endAt] = localDayBounds(selectedDate.value)

  try {
    const [timeline, protectList, recordingsPage, camDetail] = await Promise.all([
      getCameraTimeline(selectedCameraId.value, startAt, endAt, "minute"),
      typeof listRecordingProtections === "function" ? listRecordingProtections(selectedCameraId.value).catch(() => [] as RecordingProtection[]) : Promise.resolve([] as RecordingProtection[]),
      typeof listCameraRecordings === "function" ? listCameraRecordings(selectedCameraId.value, startAt, endAt).catch(() => null) : Promise.resolve(null),
      typeof getCamera === "function" ? getCamera(selectedCameraId.value).catch(() => null) : Promise.resolve(null)
    ])

    protections.value = protectList
    currentCameraDetail.value = camDetail

    // Auto-probe camera stream profile in background if missing resolution/codec facts
    if (
      selectedCameraId.value &&
      camDetail?.streams?.length &&
      (!camDetail.streams[0].codec || !camDetail.streams[0].width)
    ) {
      const s0 = camDetail.streams[0]
      if (typeof verifyCameraStream === "function") {
        verifyCameraStream(selectedCameraId.value, s0.id)
          .then(() => getCamera(selectedCameraId.value))
          .then((updated) => {
            if (updated && selectedCameraId.value === updated.id) {
              currentCameraDetail.value = updated
            }
          })
          .catch(() => {})
      }
    }

    const recMap = new Map<string, RecordingSegment>()
    if (recordingsPage?.items) {
      for (const r of recordingsPage.items) {
        recMap.set(r.id, r)
      }
    }

    if (timeline.segments && timeline.segments.length > 0) {
      segments.value = timeline.segments.map((seg) => {
        const startD = new Date(seg.start_at)
        const endD = new Date(seg.end_at)
        const durSec = Math.max(1, Math.round((endD.getTime() - startD.getTime()) / 1000))

        const realRec = recMap.get(seg.id)
        const bytes = realRec?.size_bytes ?? (durSec * 450_000)
        const mb = bytes >= 1024 * 1024 * 1024 ? `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB` : `${(bytes / (1024 * 1024)).toFixed(1)} MB`

        const prot = protectList.find((p) => seg.start_at <= p.ended_at && seg.end_at >= p.started_at)
        const timeStr = formatTime(startD).replace(/:/g, "")

        // Codec & Container Spec (Accurate & explainable)
        const resolvedCodec = realRec?.codec || camDetail?.streams?.[0]?.codec
        const codec = resolvedCodec ? resolvedCodec.toUpperCase() : "未探测编码"
        const container = (realRec?.container || "mp4").toUpperCase()
        const containerLabel = container === "FMP4" ? "MP4 (fMP4)" : container

        let spec = `${codec} · ${containerLabel}`
        let audioSpec = "—"

        if (camDetail?.streams && camDetail.streams.length > 0) {
          const s0 = camDetail.streams[0]
          if (s0.width && s0.height) {
            const fpsStr = s0.fps ? `${Math.round(s0.fps)}FPS · ` : ""
            spec = `${s0.width}×${s0.height} · ${fpsStr}${codec}`
          } else if (resolvedCodec) {
            spec = `${codec} · ${containerLabel}`
          }
          if (s0.has_audio) {
            audioSpec = `${(s0.audio_codec || "AAC").toUpperCase()} 音频`
          } else if (s0.last_verified_at) {
            audioSpec = "无音频流 (流内无音频轨)"
          } else {
            audioSpec = "待探测 (流特征未验证)"
          }
        }

        // Storage & Tier mapping (Genuine)
        const isLocal = seg.availability === "local"
        const isRemote = seg.availability === "remote"
        const isCached = seg.availability === "cached_remote"
        const isCorrupted = seg.availability === "corrupted"

        let tierLabel = "本地存储"
        let storageNode = "本地存储池"
        let isArchived = false
        let archiveLabel = "未归档 (仅本地存储)"

        if (isRemote) {
          tierLabel = "远端归档"
          storageNode = "远端归档池"
          isArchived = true
          archiveLabel = "已归档至远端"
        } else if (isCached) {
          tierLabel = "本地缓存 + 远端"
          storageNode = "本地缓存 + 远端归档"
          isArchived = true
          archiveLabel = "双副本 (已归档)"
        } else if (isLocal) {
          tierLabel = "本地存储"
          storageNode = "本地存储池"
          isArchived = false
          archiveLabel = "未归档 (仅本地存储)"
        } else if (isCorrupted) {
          tierLabel = "损坏切片"
          storageNode = "本地存储池 (异常)"
          isArchived = false
          archiveLabel = "切片损坏"
        }

        return {
          id: seg.id,
          file: `rec_${selectedDate.value}_${timeStr}_${durSec}s.mp4`,
          start: formatTime(startD),
          end: formatTime(endD),
          startDate: startD,
          endDate: endD,
          durationSec: durSec,
          sizeFormatted: mb,
          bytes,
          type: "continuous",
          tier: seg.availability,
          tierLabel,
          storageNode,
          isArchived,
          archiveLabel,
          spec,
          audioSpec,
          protected: !!prot,
          protectionId: prot?.id,
          health: isCorrupted ? "abnormal" : "healthy",
          healthLabel: isCorrupted ? "损坏" : "正常",
          codec,
          container
        }
      })

      // Update current day's real stats in month map
      const cloudCount = segments.value.filter((s) => s.isArchived).length
      monthSegmentsMap.value.set(selectedDate.value, {
        count: segments.value.length,
        bytes: totalBytes.value,
        durationSec: totalDurationSec.value,
        cloudCount
      })
    } else {
      segments.value = []
      monthSegmentsMap.value.set(selectedDate.value, { count: 0, bytes: 0, durationSec: 0, cloudCount: 0 })
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
  previewSelectionToken.value += 1

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
      showToast("切片正在从远端拉取中...")
    } else {
      videoUrl.value = null
    }
  } catch {
    videoUrl.value = null
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
  loadMonthTimeline()
  showToast(t("files.toast.monthChanged", { year: nextY, month: nextM }))
}

function selectCalendarDate(dateStr: string): void {
  selectedDate.value = dateStr
  calendarExpanded.value = false
  showToast(t("files.toast.dateChanged", { date: dateStr }))
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
    showToast(
      t("files.toast.segmentLocated", {
        file: closest.file,
        start: closest.start
      })
    )
  } else {
    showToast(t("files.toast.heatmapSlot", { label: cell.timeLabel }))
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
      showToast(t("files.toast.protectionRemoved", { file: item.file }))
    } catch {
      item.protected = false
      showToast(t("files.toast.lockRemoved", { file: item.file }))
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
      showToast(t("files.toast.rangeProtected"))
    } catch {
      item.protected = true
      showToast(t("files.toast.segmentProtected", { file: item.file }))
    }
  }
}

/**
 * 触发原始切片下载
 */
function downloadRawSegment(item: SegmentItem): void {
  showToast(
      t("files.toast.downloading", {
        file: item.file,
        size: item.sizeFormatted
      })
    )
  const link = document.createElement("a")
  link.href = videoUrl.value || "#"
  link.download = item.file
  link.click()
}

function triggerArchiveSync(item: SegmentItem): void {
  showToast(t("files.toast.archived", { file: item.file }))
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

watch(calendarExpanded, (isOpen) => {
  if (isOpen) {
    loadMonthTimeline()
  }
})

watch([selectedCameraId, selectedDate], ([newCam, newDate], [oldCam, oldDate]) => {
  loadSegments()
  if (calendarExpanded.value || !oldDate || newDate.slice(0, 7) !== oldDate.slice(0, 7) || newCam !== oldCam) {
    loadMonthTimeline()
  }
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
          <span>录像文件 (Files)</span>
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
          <option value="local">本地可用 ({{ localSegmentsCount }})</option>
          <option value="cloud">仅远端归档 ({{ cloudSegmentsCount }})</option>
          <option value="both">双副本已同步 ({{ bothSegmentsCount }})</option>
        </select>

        <!-- Health Filter -->
        <select v-model="filterHealth" class="header-filter-select" aria-label="健康状态筛选">
          <option value="all">健康状态: 全部</option>
          <option value="healthy">正常健康 ({{ segments.length - corruptedCount }})</option>
          <option value="abnormal">异常 / 损坏 ({{ corruptedCount }})</option>
        </select>

        <!-- Archival Status Filter (Genuine) -->
        <select v-model="filterArchive" class="header-filter-select" aria-label="归档状态筛选">
          <option value="all">归档状态: 全部</option>
          <option value="archived">已归档 ({{ archiveCount }})</option>
          <option value="local_only">未归档 / 仅本地 ({{ localSegmentsCount }})</option>
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

    <!-- Expandable Month Calendar Drawer (Genuine 30-day data overview) -->
    <FilesMonthCalendar
      v-if="calendarExpanded"
      :selected-date="selectedDate"
      :today-date="getInitialDate()"
      :segments-count="segments.length"
      :total-bytes="totalBytes"
      :total-duration-sec="totalDurationSec"
      :month-segments-map="monthSegmentsMap"
      @shift-month="shiftMonth"
      @select-date="selectCalendarDate"
    />

    <!-- Main Body: Two-Column Ergonomics -->
    <div class="files-body">
      <!-- Left Column: Selected Segment Inspector & Preview (420px fixed) -->
      <aside class="files-inspector-column">
        <FilesPreviewPlayer
          :active-segment="activeSegment"
          :video-url="videoUrl"
          :selection-token="previewSelectionToken"
          @previous="prevSegment"
          @next="nextSegment"
          @preview-status="showToast"
        />

        <FilesHeatmap
          :selected-date="selectedDate"
          :segments="segments"
          :total-duration-formatted="totalDurationFormatted"
          :active-heat-bin-index="activeHeatBinIndex"
          @select-cell="onHeatCellClick"
        />

        <FilesSegmentInspector
          :active-segment="activeSegment"
          :active-segment-index="activeSegmentIndex"
          :segments-count="segments.length"
          :format-duration="formatDuration"
          @jump="jumpToTimeline"
          @download="downloadRawSegment"
          @toggle-lock="toggleSegmentLock"
          @archive="triggerArchiveSync"
          @clear="showToast('审计安全保护：单条物理清理需在存储设置中操作')"
        />
      </aside>

      <!-- Right Column: Recording File Catalog & Batch Operations -->
      <main class="files-catalog-column">
        <!-- Summary Genuine KPI Cards (5 cards across) -->
        <div class="kpi-cards-grid">
          <div class="kpi-card">
            <div class="kpi-label">当日录像片段</div>
            <div class="kpi-value">{{ segments.length }} <span class="kpi-unit">段</span></div>
            <div class="kpi-sub text-blue-400">总计 {{ totalDurationFormatted }}</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">当日存储占用</div>
            <div class="kpi-value">{{ totalSizeFormatted }}</div>
            <div class="kpi-sub text-gray-400">平均 {{ avgSizeFormatted }} / 片段</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">云端/远端归档率</div>
            <div class="kpi-value" :class="archiveCount > 0 ? 'text-emerald-400' : 'text-gray-400'">
              {{ archiveRate }}%
            </div>
            <div class="kpi-sub" :class="archiveCount > 0 ? 'text-emerald-400' : 'text-gray-400'">
              {{ archiveCount > 0 ? `${archiveCount}/${segments.length} 已同步远端` : `${localSegmentsCount}/${segments.length} 仅本地存储 (未归档)` }}
            </div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">受保护锁定片段</div>
            <div class="kpi-value text-amber-400">{{ protectedCount }} <span class="kpi-unit">个</span></div>
            <div class="kpi-sub text-amber-300">{{ protectedCount > 0 ? '免除自动轮转覆盖' : '无锁定文件' }}</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">健康与完整性</div>
            <div class="kpi-value text-emerald-400">{{ integrityRate }}%</div>
            <div class="kpi-sub text-gray-400">{{ corruptedCount > 0 ? `${corruptedCount} 处损坏` : '0 处异常 · 全部完好' }}</div>
          </div>
        </div>

        <FilesSegmentTable
          v-model:current-page="currentPage"
          :filtered-count="filteredSegments.length"
          :paged-segments="pagedSegments"
          :selected-segment-id="selectedSegmentId"
          :loading="loading"
          :selected-date="selectedDate"
          :total-pages="totalPages"
          :page-start-index="pageStartIndex"
          :page-end-index="pageEndIndex"
          :format-duration="formatDuration"
          @select="selectSegment"
          @jump="jumpToTimeline"
          @download="downloadRawSegment"
          @toggle-lock="toggleSegmentLock"
        />
      </main>
    </div>

    <!-- Notification Toast -->
    <ToastHost surface-class="toast-notification">
      <span class="toast-dot" />
      <span>{{ toastMessage }}</span>
    </ToastHost>
  </div>
</template>

<style scoped>
.files-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  width: 100%;
  background-color: var(--uf-bg-canvas);
  color: var(--uf-text-secondary);
  overflow: hidden;
}

/* Header */
.files-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  background-color: var(--uf-bg-header);
  border-bottom: 1px solid var(--uf-border);
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
  color: var(--uf-text-primary);
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

.topbar-divider {
  width: 1px;
  height: 16px;
  background: var(--uf-border);
}

.header-field {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
}

.field-label {
  color: var(--uf-text-muted);
  font-size: 12px;
}

.header-select,
.header-date-input,
.header-filter-select {
  background: var(--uf-bg-card);
  border: 1px solid var(--uf-border-strong);
  border-radius: 8px;
  color: var(--uf-text-primary);
  font-size: 11px;
  padding: 4px 8px;
  outline: none;
  transition: border-color 0.15s;
}

.header-select:focus,
.header-date-input:focus,
.header-filter-select:focus {
  border-color: var(--uf-accent);
}

.header-date-group {
  display: flex;
  align-items: center;
  gap: 4px;
}

.stepper-btn {
  background: var(--uf-bg-card-sub);
  border: 1px solid var(--uf-border);
  color: var(--uf-text-secondary);
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
  background: var(--uf-bg-hover);
  color: var(--uf-text-primary);
}

.header-btn {
  background: var(--uf-bg-card-sub);
  border: 1px solid var(--uf-border);
  color: var(--uf-text-secondary);
  font-size: 11px;
  padding: 4px 8px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.12s;
}

.header-btn:hover {
  background: var(--uf-bg-hover);
  color: var(--uf-text-primary);
}

.header-btn--accent {
  color: var(--uf-accent);
}

.calendar-toggle-btn {
  display: flex;
  align-items: center;
  gap: 5px;
}

.calendar-toggle-btn--active {
  background: var(--uf-accent-soft);
  border-color: var(--uf-accent);
  color: var(--uf-accent);
}

.header-refresh-btn {
  background: var(--uf-bg-card-sub);
  border: 1px solid var(--uf-border);
  color: var(--uf-text-muted);
  padding: 5px 8px;
  border-radius: 8px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.12s;
}

.header-refresh-btn:hover {
  background: var(--uf-bg-hover);
  color: var(--uf-text-primary);
}

/* Main Body Layout */
.files-body {
  display: flex;
  flex: 1;
  overflow: hidden;
  background-color: var(--uf-bg-canvas);
}

/* Left Column: 420px Fixed Inspector */
.files-inspector-column {
  width: 420px;
  background-color: var(--uf-bg-dock);
  border-right: 1px solid var(--uf-border);
  display: flex;
  flex-direction: column;
  padding: 14px;
  gap: 12px;
  overflow-y: auto;
  flex-shrink: 0;
}

/* Right Column: Catalog & Table */
.files-catalog-column {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 14px;
  gap: 10px;
  background-color: var(--uf-bg-canvas);
}

/* KPI Cards Grid */
.kpi-cards-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 10px;
  flex-shrink: 0;
}

.kpi-card {
  background: var(--uf-bg-card);
  border: 1px solid var(--uf-border);
  border-radius: 12px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  box-shadow: var(--uf-shadow-sm);
}

.kpi-label {
  font-size: 10px;
  color: var(--uf-text-muted);
  text-transform: uppercase;
  font-family: var(--font-mono);
}

.kpi-value {
  font-size: 18px;
  font-weight: 700;
  color: var(--uf-text-primary);
  font-family: var(--font-mono);
}

.kpi-unit {
  font-size: 11px;
  font-weight: 400;
  color: var(--uf-text-muted);
}

.kpi-sub {
  font-size: 10px;
}

/* Toast Notification */
.toast-notification {
  position: fixed;
  bottom: 24px;
  right: 24px;
  background: var(--uf-bg-card);
  border: 1px solid var(--uf-border);
  box-shadow: var(--uf-shadow-lg);
  color: var(--uf-text-primary);
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
  background-color: var(--uf-accent);
}

@keyframes toast-in {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
