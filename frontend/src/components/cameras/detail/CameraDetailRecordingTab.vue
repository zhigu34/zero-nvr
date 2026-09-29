<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from "vue"
import { useI18n } from "vue-i18n"
import { type CameraDetail } from "../../../api/cameras"
import { ApiClientError, errorMessage } from "../../../api/client"
import {
  createRecordingTrigger,
  getRecordingPolicy,
  listRecordingTriggers,
  putRecordingPolicy,
  stopRecordingTrigger,
  type RecordingPolicy,
  type RecordingPolicyPut,
  type RecordingScheduleWindow,
  type RecordingTrigger
} from "../../../api/recordings"
import { type RetentionPolicy, type StorageTarget } from "../../../api/storage"
import UiIcon from "../../ui/UiIcon.vue"

type RecordingMode = "continuous" | "schedule" | "events" | "off"

interface SmartTag {
  key: string
  label: string
  emoji: string
  aliases: string[]
}

const props = defineProps<{
  camera: CameraDetail
  canConfigure: boolean
  localTargets: StorageTarget[]
  retentionPolicies: RetentionPolicy[]
}>()

const emit = defineEmits<{
  changed: []
  notice: [msg: string]
  error: [msg: string]
}>()

const { t } = useI18n({ useScope: "global" })

const savingRecording = ref(false)
const policy = ref<RecordingPolicy | null>(null)

// Manual Recording Dashboard State
const manualReason = ref("")
const manualRecordingBusy = ref(false)
const activeManualTrigger = ref<RecordingTrigger | null>(null)
const manualElapsedSeconds = ref(0)
let manualTimer: number | null = null

const SMART_TAGS: SmartTag[] = [
  { key: "person", label: "人体 / 访客", emoji: "🚶", aliases: ["person"] },
  { key: "vehicle", label: "机动车", emoji: "🚗", aliases: ["vehicle", "car"] },
  { key: "bicycle", label: "两轮车", emoji: "🛵", aliases: ["bicycle", "motorcycle"] },
  { key: "pet", label: "宠物动物", emoji: "🐕", aliases: ["pet", "dog", "cat", "animal"] },
  { key: "package", label: "快递包裹", emoji: "📦", aliases: ["package"] },
  { key: "face", label: "人脸近景", emoji: "🧑", aliases: ["face"] }
]

const weekdays = computed(() => [
  t("cameras.detail.weekdays.mon"),
  t("cameras.detail.weekdays.tue"),
  t("cameras.detail.weekdays.wed"),
  t("cameras.detail.weekdays.thu"),
  t("cameras.detail.weekdays.fri"),
  t("cameras.detail.weekdays.sat"),
  t("cameras.detail.weekdays.sun")
])

const recordingForm = reactive({
  mode: "continuous" as RecordingMode,
  eventRecording: false,
  timezone: "UTC",
  segmentSeconds: 300,
  preRoll: 10,
  postRoll: 10,
  storageTargetId: "",
  retentionPolicyId: "",
  labels: "",
  zones: "",
  minConfidence: 0.6,
  weekly: [] as RecordingScheduleWindow[]
})

function defaultWeekly(): RecordingScheduleWindow[] {
  return [
    {
      days: [0, 1, 2, 3, 4, 5, 6],
      start: "00:00",
      end: "23:59"
    }
  ]
}

function resetPolicy(value: RecordingPolicy | null): void {
  if (value === null) {
    recordingForm.mode = "continuous"
    recordingForm.eventRecording = false
    recordingForm.segmentSeconds = 300
    recordingForm.preRoll = 10
    recordingForm.postRoll = 10
    recordingForm.storageTargetId = ""
    recordingForm.retentionPolicyId = ""
    recordingForm.labels = ""
    recordingForm.zones = ""
    recordingForm.minConfidence = 0.6
    recordingForm.weekly = defaultWeekly()
    return
  }

  if (!value.enabled) {
    recordingForm.mode = "off"
  } else if (
    value.baseline_mode === "disabled" &&
    value.event_recording_enabled
  ) {
    recordingForm.mode = "events"
  } else if (value.baseline_mode === "disabled") {
    recordingForm.mode = "off"
  } else {
    recordingForm.mode = value.baseline_mode
  }

  recordingForm.eventRecording =
    recordingForm.mode === "events" ? true : value.event_recording_enabled
  recordingForm.timezone =
    value.schedule_timezone ||
    Intl.DateTimeFormat().resolvedOptions().timeZone ||
    "UTC"
  recordingForm.segmentSeconds = value.segment_target_seconds
  recordingForm.preRoll = value.pre_roll_seconds
  recordingForm.postRoll = value.post_roll_seconds
  recordingForm.storageTargetId = value.storage_target_id ?? ""
  recordingForm.retentionPolicyId = value.retention_policy_id ?? ""
  recordingForm.labels = (value.event_filter.labels ?? []).join(", ")
  recordingForm.zones = (value.event_filter.zones ?? []).join(", ")
  recordingForm.minConfidence = value.event_filter.min_confidence ?? 0.6
  recordingForm.weekly =
    value.schedule.weekly?.map((item) => ({
      days: [...item.days],
      start: item.start,
      end: item.end
    })) ?? defaultWeekly()
}

async function loadPolicy(): Promise<void> {
  if (!props.camera?.id) return
  try {
    policy.value = await getRecordingPolicy(props.camera.id)
    resetPolicy(policy.value)
  } catch (caught) {
    if (
      caught instanceof ApiClientError &&
      caught.code === "recording_policy_not_configured"
    ) {
      policy.value = null
      resetPolicy(null)
    } else {
      emit("error", errorMessage(caught))
    }
  }
}

watch(
  () => props.camera?.id,
  () => {
    void loadPolicy()
    void loadManualTrigger()
  },
  { immediate: true }
)

function csv(value: string): string[] {
  return Array.from(
    new Set(
      value
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean)
    )
  )
}

function buildPolicy(): RecordingPolicyPut {
  const off = recordingForm.mode === "off"
  const eventOnly = recordingForm.mode === "events"
  const scheduled = recordingForm.mode === "schedule"
  const eventEnabled =
    eventOnly || (!off && recordingForm.eventRecording)

  return {
    baseline_mode:
      off || eventOnly
        ? "disabled"
        : recordingForm.mode === "schedule"
          ? "schedule"
          : "continuous",
    schedule: scheduled
      ? {
          weekly: recordingForm.weekly.map((item) => ({
            days: [...item.days].sort((a, b) => a - b),
            start: item.start,
            end: item.end
          }))
        }
      : {},
    schedule_timezone: scheduled ? recordingForm.timezone.trim() : null,
    event_recording_enabled: eventEnabled,
    event_filter: eventEnabled
      ? {
          labels: csv(recordingForm.labels),
          zones: csv(recordingForm.zones),
          min_confidence: Number(recordingForm.minConfidence)
        }
      : {},
    segment_target_seconds: Number(recordingForm.segmentSeconds),
    pre_roll_seconds: Number(recordingForm.preRoll),
    post_roll_seconds: Number(recordingForm.postRoll),
    storage_target_id: recordingForm.storageTargetId || null,
    retention_policy_id: recordingForm.retentionPolicyId || null,
    enabled: !off
  }
}

async function saveRecording(): Promise<void> {
  if (!props.camera?.id) return
  savingRecording.value = true
  try {
    const res = await putRecordingPolicy(props.camera.id, buildPolicy())
    policy.value = res
    resetPolicy(res)
    if (res.runtime && !res.runtime.recording && res.runtime.desired_mode !== "off") {
      emit("notice", "录像策略已保存。提示：摄像机当前流未在线，当视频流恢复时系统将自动开始录像。")
    } else {
      emit("notice", t("cameras.detail.policySaved"))
    }
    emit("changed")
  } catch (caught: unknown) {
    if (caught instanceof ApiClientError && caught.details?.policy_persisted) {
      try {
        const fetched = await getRecordingPolicy(props.camera.id)
        policy.value = fetched
        resetPolicy(fetched)
      } catch {
        // Keep current form values if refetch fails
      }
      emit("notice", "录像策略已保存。提示：摄像机当前流未在线，当视频流恢复时系统将自动开始录像。")
      emit("changed")
    } else {
      emit("error", errorMessage(caught))
    }
  } finally {
    savingRecording.value = false
  }
}

function addWindow(): void {
  recordingForm.weekly.push({
    days: [0, 1, 2, 3, 4, 5, 6],
    start: "00:00",
    end: "23:59"
  })
}

function removeWindow(index: number): void {
  if (recordingForm.weekly.length <= 1) return
  recordingForm.weekly.splice(index, 1)
}

function toggleDay(window: RecordingScheduleWindow, day: number): void {
  const index = window.days.indexOf(day)
  if (index >= 0) {
    if (window.days.length > 1) window.days.splice(index, 1)
  } else {
    window.days.push(day)
    window.days.sort((a, b) => a - b)
  }
}

async function loadManualTrigger(): Promise<void> {
  if (!props.camera?.id) return
  try {
    const triggers = await listRecordingTriggers(props.camera.id)
    const active = triggers.find(
      (tr) => tr.type.toUpperCase() === "MANUAL" && tr.state === "ACTIVE" && !tr.planned_end_at
    )
    activeManualTrigger.value = active ?? null
    startManualTimer()
  } catch {
    activeManualTrigger.value = null
  }
}

function startManualTimer(): void {
  if (manualTimer !== null) {
    window.clearInterval(manualTimer)
    manualTimer = null
  }
  if (!activeManualTrigger.value) {
    manualElapsedSeconds.value = 0
    return
  }
  const startMs = new Date(activeManualTrigger.value.requested_at).getTime()
  const tick = () => {
    manualElapsedSeconds.value = Math.max(0, Math.floor((Date.now() - startMs) / 1000))
  }
  tick()
  manualTimer = window.setInterval(tick, 1000)
}

function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
}

async function handleStartManual(): Promise<void> {
  if (!props.canConfigure || manualRecordingBusy.value) return
  manualRecordingBusy.value = true
  try {
    const trigger = await createRecordingTrigger(
      props.camera.id,
      manualReason.value.trim() || "配置中心手动触发保全录像"
    )
    activeManualTrigger.value = trigger
    startManualTimer()
    emit("notice", "⏺️ 手动录像已启动，已提升 10 秒前置预录并写入保全存储区")
    manualReason.value = ""
  } catch (caught) {
    emit("error", errorMessage(caught))
  } finally {
    manualRecordingBusy.value = false
  }
}

async function handleStopManual(): Promise<void> {
  if (!props.canConfigure || manualRecordingBusy.value || !activeManualTrigger.value) return
  manualRecordingBusy.value = true
  try {
    await stopRecordingTrigger(activeManualTrigger.value.id)
    activeManualTrigger.value = null
    startManualTimer()
    emit("notice", "⏹️ 手动录像已停止，录像切片已归档入库")
  } catch (caught) {
    emit("error", errorMessage(caught))
  } finally {
    manualRecordingBusy.value = false
  }
}

function applySchedulePreset(preset: "24x7" | "workdays" | "night" | "weekend"): void {
  if (preset === "24x7") {
    recordingForm.weekly = [
      { days: [0, 1, 2, 3, 4, 5, 6], start: "00:00", end: "23:59" }
    ]
  } else if (preset === "workdays") {
    recordingForm.weekly = [
      { days: [0, 1, 2, 3, 4], start: "08:30", end: "18:00" }
    ]
  } else if (preset === "night") {
    recordingForm.weekly = [
      { days: [0, 1, 2, 3, 4, 5, 6], start: "19:00", end: "23:59" },
      { days: [0, 1, 2, 3, 4, 5, 6], start: "00:00", end: "07:00" }
    ]
  } else if (preset === "weekend") {
    recordingForm.weekly = [
      { days: [5, 6], start: "00:00", end: "23:59" }
    ]
  }
}

function copyWindowToAllDays(window: RecordingScheduleWindow): void {
  window.days = [0, 1, 2, 3, 4, 5, 6]
}

function copyWindowToWorkdays(window: RecordingScheduleWindow): void {
  window.days = [0, 1, 2, 3, 4]
}

function getDayCoverageSegments(dayIndex: number): Array<{ left: number; width: number }> {
  const segments: Array<{ left: number; width: number }> = []
  for (const win of recordingForm.weekly) {
    if (!win.days.includes(dayIndex)) continue
    const [sh, sm] = win.start.split(":").map(Number)
    const [eh, em] = win.end.split(":").map(Number)
    if (isNaN(sh) || isNaN(sm) || isNaN(eh) || isNaN(em)) continue
    const startHour = sh + sm / 60
    const endHour = Math.min(24, eh + em / 60)
    if (endHour <= startHour) continue
    const left = (startHour / 24) * 100
    const width = Math.min(100 - left, ((endHour - startHour) / 24) * 100)
    segments.push({ left, width })
  }
  return segments
}

function getDayCoverageHours(dayIndex: number): string {
  let totalHours = 0
  for (const win of recordingForm.weekly) {
    if (!win.days.includes(dayIndex)) continue
    const [sh, sm] = win.start.split(":").map(Number)
    const [eh, em] = win.end.split(":").map(Number)
    if (isNaN(sh) || isNaN(sm) || isNaN(eh) || isNaN(em)) continue
    const startHour = sh + sm / 60
    const endHour = eh + em / 60
    if (endHour > startHour) {
      totalHours += Math.min(24, endHour) - startHour
    }
  }
  if (totalHours >= 23.9) return "全天 24H"
  if (totalHours <= 0) return "无录像"
  return `${totalHours.toFixed(1)} 小时`
}

function isSmartTagSelected(tag: SmartTag): boolean {
  const currentLabels = recordingForm.labels
    .split(",")
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean)
  return tag.aliases.some((alias) => currentLabels.includes(alias))
}

function toggleSmartTag(tag: SmartTag): void {
  const currentLabels = recordingForm.labels
    .split(",")
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean)

  if (isSmartTagSelected(tag)) {
    const updated = currentLabels.filter((l) => !tag.aliases.includes(l))
    recordingForm.labels = updated.join(", ")
  } else {
    currentLabels.push(tag.key)
    recordingForm.labels = Array.from(new Set(currentLabels)).join(", ")
  }
}

function getConfidenceAdvice(val: number): { label: string; class: string } {
  const pct = Math.round(val * 100)
  if (pct < 50) {
    return { label: `${pct}% · 高灵敏度 (微弱变化即触发，可能有风吹草动)`, class: "text-amber-400" }
  }
  if (pct <= 75) {
    return { label: `${pct}% · 官方标准推荐 (平衡误报与漏报)`, class: "text-emerald-400" }
  }
  return { label: `${pct}% · 高置信度 (仅在极明确目标时触发)`, class: "text-blue-400" }
}

onBeforeUnmount(() => {
  if (manualTimer !== null) {
    window.clearInterval(manualTimer)
    manualTimer = null
  }
})
</script>

<template>
  <form class="camera-recording-editor" @submit.prevent="saveRecording">
    <!-- Module 1: 即时手动录制控制台 (Manual Recording Dashboard) -->
    <section class="camera-detail-section manual-recording-section">
      <div class="camera-detail-section__heading camera-detail-section__heading--actions">
        <div>
          <div class="manual-heading-row">
            <strong class="text-white text-xs">即时手动录制 (Manual Recording)</strong>
            <span
              v-if="activeManualTrigger"
              class="manual-badge manual-badge--active animate-pulse"
            >
              <span class="manual-dot bg-red-500"></span>
              正在录制 · {{ formatElapsed(manualElapsedSeconds) }}
            </span>
            <span v-else class="manual-badge manual-badge--idle">
              <span class="manual-dot bg-gray-500"></span>
              空闲待命
            </span>
          </div>
          <span class="text-[10px] text-gray-400 mt-0.5 block">
            遇到突发安防事件可即时开启录像；系统将自动调取前置 10 秒内存预录并写入保全存储区，不会被循环清理覆盖。
          </span>
        </div>
      </div>

      <div class="manual-recording-box">
        <template v-if="activeManualTrigger">
          <div class="manual-active-details">
            <div class="text-[11px] text-gray-300">
              <span class="text-gray-400">录制备忘: </span>
              <strong class="text-white font-medium">{{ activeManualTrigger.reason || '人工即时触发录制' }}</strong>
              <span class="ml-2 font-mono text-[10px] text-gray-400">
                ({{ new Date(activeManualTrigger.requested_at).toLocaleTimeString() }} 开启)
              </span>
            </div>
          </div>
          <button
            type="button"
            class="button button--danger manual-action-btn"
            :disabled="manualRecordingBusy || !canConfigure"
            @click="handleStopManual"
          >
            <UiIcon name="pause" :size="13" />
            <span>{{ manualRecordingBusy ? '正在停止...' : '⏹️ 停止手动录制并归档' }}</span>
          </button>
        </template>

        <template v-else>
          <div class="manual-start-row">
            <input
              v-model="manualReason"
              type="text"
              placeholder="输入手动录像备忘原因 (如：夜巡异常、重点嫌疑排查...)"
              class="manual-reason-input"
              :disabled="manualRecordingBusy || !canConfigure"
            />
            <button
              type="button"
              class="button button--primary manual-action-btn"
              :disabled="manualRecordingBusy || !canConfigure"
              @click="handleStartManual"
            >
              <UiIcon name="play" :size="13" />
              <span>{{ manualRecordingBusy ? '启动中...' : '⏺️ 立即发起手动录制' }}</span>
            </button>
          </div>
        </template>
      </div>
    </section>

    <!-- Module 2: 顶层录制模式选择 (Top-level Mode Cards) -->
    <section class="camera-detail-section">
      <div class="camera-detail-section__heading">
        <strong>录制策略基线模式 (Recording Mode Baseline)</strong>
        <span>选择该机位的底模录制方式，可随时配合 AI 目标打标或计划时间表联动生效</span>
      </div>

      <div class="recording-mode-grid">
        <label
          class="recording-mode-card"
          :class="{ 'recording-mode-card--active': recordingForm.mode === 'continuous' }"
        >
          <input
            v-model="recordingForm.mode"
            type="radio"
            name="recording-mode"
            value="continuous"
            :disabled="!canConfigure"
          />
          <div class="recording-mode-card__header">
            <span class="text-emerald-400 font-bold">🟢 全天候连续录制</span>
            <span class="mode-tag bg-emerald-500/20 text-emerald-400">推荐</span>
          </div>
          <span>24/7 底层不间断连续写盘；配合 AI 目标识别可在回放时间轴上精确标红事件。</span>
        </label>

        <label
          class="recording-mode-card"
          :class="{ 'recording-mode-card--active': recordingForm.mode === 'schedule' }"
        >
          <input
            v-model="recordingForm.mode"
            type="radio"
            name="recording-mode"
            value="schedule"
            :disabled="!canConfigure"
          />
          <div class="recording-mode-card__header">
            <span class="text-purple-400 font-bold">🟣 计划排程定时录制</span>
            <span class="mode-tag bg-purple-500/20 text-purple-400">定时</span>
          </div>
          <span>仅在周一至周日指定的时间段内录制（如营业时段、夜间安防），时段外停止写盘。</span>
        </label>

        <label
          class="recording-mode-card"
          :class="{ 'recording-mode-card--active': recordingForm.mode === 'events' }"
        >
          <input
            v-model="recordingForm.mode"
            type="radio"
            name="recording-mode"
            value="events"
            :disabled="!canConfigure"
          />
          <div class="recording-mode-card__header">
            <span class="text-amber-400 font-bold">🟡 仅事件触发录制</span>
            <span class="mode-tag bg-amber-500/20 text-amber-400">省盘</span>
          </div>
          <span>平常不写盘（常驻 10 秒内存预录），仅在检测到人/车或动态时即时唤醒写盘，大幅节省磁盘。</span>
        </label>

        <label
          class="recording-mode-card"
          :class="{ 'recording-mode-card--active': recordingForm.mode === 'off' }"
        >
          <input
            v-model="recordingForm.mode"
            type="radio"
            name="recording-mode"
            value="off"
            :disabled="!canConfigure"
          />
          <div class="recording-mode-card__header">
            <span class="text-gray-400 font-bold">⚪ 完全停用录制</span>
            <span class="mode-tag bg-white/10 text-gray-400">停用</span>
          </div>
          <span>停止所有自动与事件录像写盘，该机位仅供实时监控多画面预览使用。</span>
        </label>
      </div>

      <!-- Event Recording Toggle for Continuous / Scheduled -->
      <div
        v-if="recordingForm.mode === 'continuous' || recordingForm.mode === 'schedule'"
        class="event-toggle-card"
      >
        <label class="storage-check">
          <input
            v-model="recordingForm.eventRecording"
            type="checkbox"
            :disabled="!canConfigure"
          />
          <div>
            <strong class="text-white text-xs block">启用 AI 智能目标识别与事件打标 (Event Markers & Promotion)</strong>
            <span class="text-[10px] text-gray-400 block mt-0.5">
              开启后，人/车等关键活动将在时间轴上高亮展示并提升保全等级，回放时支持智能快进与事件跳转。
            </span>
          </div>
        </label>
      </div>
    </section>

    <!-- Module 3: 可视化 7×24 小时定时排程器 (Weekly Schedule Matrix) -->
    <section
      v-if="recordingForm.mode === 'schedule'"
      class="camera-detail-section schedule-section"
    >
      <div class="camera-detail-section__heading camera-detail-section__heading--actions">
        <div>
          <strong>7×24 小时周计划排程总览 (Weekly Schedule Matrix)</strong>
          <span>蓝色高亮代表排程内录像时段，深色代表无录像停机；可一键套用常用模版</span>
        </div>
        <button
          class="button button--ghost button--compact"
          type="button"
          :disabled="!canConfigure"
          @click="addWindow"
        >
          <UiIcon name="plus" :size="13" />
          <span>添加时段</span>
        </button>
      </div>

      <!-- Quick Presets -->
      <div class="schedule-presets-bar">
        <span class="text-[10px] text-gray-400 uppercase font-mono">快捷模版:</span>
        <button
          type="button"
          class="preset-chip"
          :disabled="!canConfigure"
          @click="applySchedulePreset('24x7')"
        >
          24×7 全天候
        </button>
        <button
          type="button"
          class="preset-chip"
          :disabled="!canConfigure"
          @click="applySchedulePreset('workdays')"
        >
          工作日营业 (08:30~18:00)
        </button>
        <button
          type="button"
          class="preset-chip"
          :disabled="!canConfigure"
          @click="applySchedulePreset('night')"
        >
          夜间安防 (19:00~07:00)
        </button>
        <button
          type="button"
          class="preset-chip"
          :disabled="!canConfigure"
          @click="applySchedulePreset('weekend')"
        >
          周末全天
        </button>
      </div>

      <!-- 7-Day Visual Matrix Preview -->
      <div class="schedule-matrix-box">
        <div class="schedule-scale">
          <span>00:00</span>
          <span>06:00</span>
          <span>12:00</span>
          <span>18:00</span>
          <span>24:00</span>
        </div>

        <div
          v-for="(day, dIndex) in weekdays"
          :key="day"
          class="schedule-matrix-row"
        >
          <span class="schedule-matrix-day">{{ day }}</span>
          <div class="schedule-matrix-track">
            <div
              v-for="(seg, sIdx) in getDayCoverageSegments(dIndex)"
              :key="sIdx"
              class="schedule-matrix-bar"
              :style="{ left: `${seg.left}%`, width: `${seg.width}%` }"
            ></div>
          </div>
          <span class="schedule-matrix-hours font-mono">{{ getDayCoverageHours(dIndex) }}</span>
        </div>
      </div>

      <!-- Timezone & Windows Editor -->
      <label class="camera-detail-field mt-3">
        <span>{{ t("cameras.detail.timezone") }}</span>
        <input
          v-model="recordingForm.timezone"
          :disabled="!canConfigure"
          required
          placeholder="Asia/Shanghai 或 America/Los_Angeles"
        />
      </label>

      <div class="recording-window-list mt-2">
        <article
          v-for="(window, index) in recordingForm.weekly"
          :key="index"
          class="recording-window"
        >
          <div class="recording-window__days">
            <button
              v-for="(day, dayIndex) in weekdays"
              :key="day"
              type="button"
              :class="{ 'recording-day--active': window.days.includes(dayIndex) }"
              :disabled="!canConfigure"
              @click="toggleDay(window, dayIndex)"
            >
              {{ day }}
            </button>
          </div>

          <div class="recording-window__time">
            <input
              v-model="window.start"
              type="time"
              :disabled="!canConfigure"
              required
            />
            <span class="text-gray-400 text-xs">至</span>
            <input
              v-model="window.end"
              type="time"
              :disabled="!canConfigure"
              required
            />
            <div class="flex items-center space-x-1">
              <button
                type="button"
                class="window-quick-btn"
                title="将本时段应用到整周 7 天"
                :disabled="!canConfigure"
                @click="copyWindowToAllDays(window)"
              >
                全周
              </button>
              <button
                type="button"
                class="window-quick-btn"
                title="将本时段应用到周一至周五工作日"
                :disabled="!canConfigure"
                @click="copyWindowToWorkdays(window)"
              >
                工作日
              </button>
              <button
                class="icon-button icon-button--danger"
                type="button"
                title="删除该时间段"
                :disabled="!canConfigure || recordingForm.weekly.length <= 1"
                @click="removeWindow(index)"
              >
                <UiIcon name="trash" :size="13" />
              </button>
            </div>
          </div>
        </article>
      </div>
    </section>

    <!-- Module 4: AI 智能事件录制与动态捕捉 (Smart Event Studio) -->
    <section
      v-if="recordingForm.mode === 'events' || recordingForm.eventRecording"
      class="camera-detail-section event-studio-section"
    >
      <div class="camera-detail-section__heading">
        <strong>AI 智能目标检测与事件保全 (Smart Object & Event Studio)</strong>
        <span>通过边缘/服务端 AI 模型筛选检测目标，并运用环形预录缓冲还原完整因果</span>
      </div>

      <!-- Smart Tag Chips Selector -->
      <div class="smart-tags-block">
        <span class="text-[10px] text-gray-400 uppercase font-mono block mb-1.5">
          目标类型多选 (点击切换选中状态):
        </span>
        <div class="smart-tags-grid">
          <button
            v-for="tag in SMART_TAGS"
            :key="tag.key"
            type="button"
            class="smart-tag-chip"
            :class="{ 'smart-tag-chip--active': isSmartTagSelected(tag) }"
            :disabled="!canConfigure"
            @click="toggleSmartTag(tag)"
          >
            <span class="tag-emoji">{{ tag.emoji }}</span>
            <span class="tag-label">{{ tag.label }}</span>
            <span class="tag-key font-mono text-[9px]">({{ tag.key }})</span>
          </button>
        </div>
      </div>

      <!-- Visual Pre-roll & Post-roll Graphic Timeline -->
      <div class="timeline-diagram-card">
        <div class="text-[10px] text-gray-300 font-semibold mb-2">
          ⏱️ 智能事件前后缓冲时间轴模型 (Pre-roll & Post-roll Buffer)
        </div>
        <div class="timeline-diagram-flow">
          <div class="timeline-diagram-block timeline-diagram-block--pre">
            <span class="block-title">⏪ 预录内存环存</span>
            <span class="block-desc">内存常驻缓存事件前动作，确保起因不漏截</span>
            <span class="block-val font-mono">{{ recordingForm.preRoll }}s</span>
          </div>
          <div class="timeline-diagram-arrow">➔</div>
          <div class="timeline-diagram-block timeline-diagram-block--event">
            <span class="block-title">🎯 目标侦测触发中</span>
            <span class="block-desc">人/车/包裹进入画面持续录像</span>
            <span class="block-val font-mono">持续中</span>
          </div>
          <div class="timeline-diagram-arrow">➔</div>
          <div class="timeline-diagram-block timeline-diagram-block--post">
            <span class="block-title">⏩ 延录缓冲保护</span>
            <span class="block-desc">目标离开画面后继续延录防漏尾</span>
            <span class="block-val font-mono">{{ recordingForm.postRoll }}s</span>
          </div>
        </div>
      </div>

      <!-- Pre-roll / Post-roll number inputs -->
      <div class="camera-recording-number-grid camera-recording-number-grid--two">
        <label>
          <span>前置预录缓冲时长 (Pre-roll 秒数)</span>
          <input
            v-model.number="recordingForm.preRoll"
            type="number"
            :disabled="!canConfigure"
            min="0"
            max="60"
          />
        </label>
        <label>
          <span>后置延录缓冲时长 (Post-roll 秒数)</span>
          <input
            v-model.number="recordingForm.postRoll"
            type="number"
            :disabled="!canConfigure"
            min="0"
            max="120"
          />
        </label>
      </div>

      <!-- Sensitivity / Confidence Slider -->
      <div class="confidence-slider-block">
        <div class="flex items-center justify-between">
          <span class="text-[10px] text-gray-400 uppercase font-mono font-semibold">
            AI 目标置信度阈值 (Confidence Threshold)
          </span>
          <span
            class="text-[11px] font-mono font-semibold"
            :class="getConfidenceAdvice(recordingForm.minConfidence).class"
          >
            {{ getConfidenceAdvice(recordingForm.minConfidence).label }}
          </span>
        </div>
        <input
          v-model.number="recordingForm.minConfidence"
          type="range"
          :disabled="!canConfigure"
          min="0.1"
          max="1.0"
          step="0.05"
          class="confidence-slider"
        />
      </div>

      <!-- Advanced Custom Labels & Zones (Foldable/Compact) -->
      <div class="advanced-filter-fields">
        <label class="camera-detail-field">
          <span>自定义补充标签 (英文逗号分隔)</span>
          <input
            v-model="recordingForm.labels"
            :disabled="!canConfigure"
            placeholder="例如: person, vehicle, dog, cat"
          />
        </label>
        <label class="camera-detail-field">
          <span>限定侦测区域 (Zones，留空为全画幅)</span>
          <input
            v-model="recordingForm.zones"
            :disabled="!canConfigure"
            placeholder="例如: front_door, driveway"
          />
        </label>
      </div>
    </section>

    <!-- Module 5: 录像存储切片与保留轮转策略 -->
    <section
      v-if="recordingForm.mode !== 'off'"
      class="camera-detail-section"
    >
      <div class="camera-detail-section__heading">
        <strong>存储分段与数据生命周期 (Storage & Retention)</strong>
        <span>控制文件切片大小、落盘节点以及自动轮转淘汰留存策略</span>
      </div>

      <div class="camera-recording-number-grid">
        <label>
          <span>单个切片目标时长 (秒)</span>
          <input
            v-model.number="recordingForm.segmentSeconds"
            type="number"
            :disabled="!canConfigure"
            min="10"
            max="3600"
          />
        </label>
        <label>
          <span>{{ t("cameras.detail.localStorageTarget") }}</span>
          <select
            v-model="recordingForm.storageTargetId"
            :disabled="!canConfigure"
          >
            <option value="">{{ t("cameras.detail.useDefaultLocalTarget") }}</option>
            <option
              v-for="target in localTargets"
              :key="target.id"
              :value="target.id"
            >
              {{ target.name }}
            </option>
          </select>
        </label>
        <label>
          <span>{{ t("cameras.detail.retentionPolicy") }}</span>
          <select
            v-model="recordingForm.retentionPolicyId"
            :disabled="!canConfigure"
          >
            <option value="">{{ t("cameras.detail.inheritRetention") }}</option>
            <option
              v-for="item in retentionPolicies"
              :key="item.id"
              :value="item.id"
            >
              {{ item.name }}
            </option>
          </select>
        </label>
      </div>
    </section>

    <!-- Sticky Actions Bar -->
    <div class="camera-detail-actions camera-detail-actions--sticky">
      <button
        class="button button--primary"
        type="submit"
        :disabled="savingRecording || !canConfigure"
      >
        {{
          savingRecording
            ? t("cameras.detail.applying")
            : t("cameras.detail.saveReconcile")
        }}
      </button>
    </div>
  </form>
</template>

<style scoped>
.camera-recording-editor {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.camera-detail-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.camera-detail-section__heading {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.camera-detail-section__heading--actions {
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
}

.camera-detail-section__heading strong {
  font-size: 13px;
  font-weight: 600;
  color: var(--uf-text-primary);
}

.camera-detail-section__heading span {
  font-size: 11px;
  color: var(--uf-text-muted);
}

.manual-recording-section {
  padding: 12px;
  border-radius: 9px;
  border: 1px solid var(--uf-border);
  background: var(--uf-bg-card-sub);
}

.manual-heading-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.manual-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 8px;
  border-radius: 9999px;
  font-size: 10px;
  font-weight: 600;
  border: 1px solid var(--uf-border);
}

.manual-badge--active {
  background: rgba(239, 68, 68, 0.15);
  border-color: rgba(239, 68, 68, 0.4);
  color: #ef4444;
}

.manual-badge--idle {
  background: var(--uf-bg-card);
  color: var(--uf-text-muted);
}

.manual-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}

.manual-recording-box {
  margin-top: 10px;
}

.manual-start-row {
  display: flex;
  gap: 8px;
}

.manual-reason-input {
  flex: 1;
  height: 34px;
  padding: 0 10px;
  border-radius: 6px;
  border: 1px solid var(--uf-border);
  background: var(--uf-bg-canvas);
  color: var(--uf-text-primary);
  font-size: 12px;
}

.manual-reason-input:focus {
  outline: none;
  border-color: var(--uf-accent);
}

.manual-action-btn {
  height: 34px;
  white-space: nowrap;
}

.manual-active-details {
  margin-bottom: 8px;
}

.recording-mode-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.recording-mode-card {
  position: relative;
  display: grid;
  gap: 4px;
  min-height: 72px;
  padding: 12px;
  border: 1px solid var(--uf-border);
  border-radius: 9px;
  background: var(--uf-bg-card-sub);
  cursor: pointer;
  transition: all 0.15s ease;
}

.recording-mode-card:hover {
  border-color: var(--uf-border-strong);
}

.recording-mode-card input {
  position: absolute;
  opacity: 0;
}

.recording-mode-card strong {
  font-size: 12px;
  font-weight: 700;
  color: var(--uf-text-primary);
}

.recording-mode-card span {
  color: var(--uf-text-muted);
  font-size: 11px;
  line-height: 1.4;
}

.recording-mode-card--active {
  border-color: var(--uf-accent);
  background: var(--uf-accent-soft);
  box-shadow: 0 0 12px rgba(0, 110, 255, 0.1);
}

.recording-mode-card__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
}

.mode-tag {
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 4px;
  font-weight: 600;
}

.event-toggle-card {
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px solid var(--uf-border);
  background: var(--uf-bg-card-sub);
}

.storage-check {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  cursor: pointer;
}

.storage-check input[type="checkbox"] {
  margin-top: 2px;
}

.schedule-presets-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: 4px;
}

.preset-chip {
  padding: 3px 8px;
  background: var(--uf-bg-card-sub);
  border: 1px solid var(--uf-border);
  border-radius: 5px;
  color: var(--uf-text-secondary);
  font-size: 11px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.preset-chip:hover {
  background: var(--uf-accent-soft);
  border-color: var(--uf-accent);
  color: var(--uf-accent);
}

.schedule-matrix-box {
  margin-top: 10px;
  padding: 12px 14px;
  background: var(--uf-bg-card-sub);
  border: 1px solid var(--uf-border);
  border-radius: 9px;
}

.schedule-scale {
  display: flex;
  justify-content: space-between;
  padding-left: 32px;
  padding-right: 60px;
  color: var(--uf-text-muted);
  font-family: var(--font-mono);
  font-size: 10px;
  margin-bottom: 6px;
}

.schedule-matrix-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.schedule-matrix-row:last-child {
  margin-bottom: 0;
}

.schedule-matrix-day {
  width: 24px;
  color: var(--uf-text-muted);
  font-size: 11px;
  font-weight: 600;
  text-align: center;
}

.schedule-matrix-track {
  flex: 1;
  position: relative;
  height: 16px;
  background: var(--uf-border);
  border-radius: 3px;
  overflow: hidden;
}

.schedule-matrix-bar {
  position: absolute;
  top: 0;
  bottom: 0;
  background: var(--uf-accent);
  border-radius: 3px;
  box-shadow: 0 0 6px var(--uf-accent-soft);
}

.schedule-matrix-hours {
  width: 54px;
  text-align: right;
  font-size: 11px;
  color: var(--uf-accent);
  font-family: var(--font-mono);
  font-weight: 600;
}

.camera-detail-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
  color: var(--uf-text-secondary);
}

.camera-detail-field input {
  height: 38px;
  padding: 0 12px;
  border-radius: 8px;
  border: 1px solid var(--uf-border);
  background: var(--uf-bg-canvas);
  color: var(--uf-text-primary);
  font-size: 13px;
}

.recording-window-list {
  display: grid;
  gap: 8px;
}

.recording-window {
  display: grid;
  gap: 8px;
  padding: 10px 12px;
  border: 1px solid var(--uf-border);
  border-radius: 8px;
  background: var(--uf-bg-card);
}

.recording-window__days {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 4px;
}

.recording-window__days button {
  min-height: 28px;
  padding: 0;
  border: 1px solid var(--uf-border);
  border-radius: 5px;
  background: var(--uf-bg-card-sub);
  color: var(--uf-text-muted);
  cursor: pointer;
  font-size: 10px;
  font-weight: 600;
  transition: all 0.15s ease;
}

.recording-window__days .recording-day--active {
  border-color: var(--uf-accent);
  background: var(--uf-accent-soft);
  color: var(--uf-accent);
}

.recording-window__time {
  display: grid;
  grid-template-columns: 1fr auto 1fr auto;
  align-items: center;
  gap: 8px;
}

.recording-window__time input {
  height: 34px;
  padding: 0 8px;
  border-radius: 6px;
  border: 1px solid var(--uf-border);
  background: var(--uf-bg-canvas);
  color: var(--uf-text-primary);
  font-size: 12px;
}

.window-quick-btn {
  padding: 4px 8px;
  background: var(--uf-bg-card-sub);
  border: 1px solid var(--uf-border);
  border-radius: 5px;
  color: var(--uf-text-secondary);
  font-size: 11px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.window-quick-btn:hover {
  background: var(--uf-accent-soft);
  border-color: var(--uf-accent);
  color: var(--uf-accent);
}

.icon-button {
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  border-radius: 6px;
  border: 1px solid var(--uf-border);
  background: transparent;
  color: var(--uf-text-secondary);
  cursor: pointer;
  transition: all 0.15s ease;
}

.icon-button--danger:hover {
  background: rgba(239, 68, 68, 0.15);
  border-color: #ef4444;
  color: #ef4444;
}

.smart-tags-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}

.smart-tag-chip {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 8px 10px;
  border-radius: 7px;
  border: 1px solid var(--uf-border);
  background: var(--uf-bg-card-sub);
  color: var(--uf-text-secondary);
  font-size: 11px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.smart-tag-chip:hover {
  border-color: var(--uf-border-strong);
}

.smart-tag-chip--active {
  border-color: var(--uf-accent);
  background: var(--uf-accent-soft);
  color: var(--uf-accent);
}

.tag-emoji {
  font-size: 14px;
}

.timeline-diagram-card {
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px solid var(--uf-border);
  background: var(--uf-bg-card-sub);
}

.timeline-diagram-flow {
  display: flex;
  align-items: center;
  gap: 8px;
}

.timeline-diagram-block {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 8px;
  border-radius: 6px;
  border: 1px solid var(--uf-border);
  background: var(--uf-bg-canvas);
  text-align: center;
}

.timeline-diagram-block--event {
  border-color: rgba(239, 68, 68, 0.4);
  background: rgba(239, 68, 68, 0.08);
}

.block-title {
  font-size: 11px;
  font-weight: 600;
  color: var(--uf-text-primary);
}

.block-desc {
  font-size: 9px;
  color: var(--uf-text-muted);
}

.block-val {
  font-size: 11px;
  font-weight: 700;
  color: var(--uf-accent);
  margin-top: 2px;
}

.timeline-diagram-arrow {
  color: var(--uf-text-muted);
  font-size: 12px;
}

.confidence-slider-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px solid var(--uf-border);
  background: var(--uf-bg-card-sub);
}

.confidence-slider {
  width: 100%;
}

.advanced-filter-fields {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.camera-recording-number-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.camera-recording-number-grid--two {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.camera-recording-number-grid label {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12px;
  color: var(--uf-text-secondary);
}

.camera-recording-number-grid input,
.camera-recording-number-grid select {
  height: 38px;
  padding: 0 10px;
  border-radius: 8px;
  border: 1px solid var(--uf-border);
  background: var(--uf-bg-canvas);
  color: var(--uf-text-primary);
  font-size: 12px;
}

.camera-detail-actions {
  display: flex;
  justify-content: flex-end;
  padding-top: 16px;
  border-top: 1px solid var(--uf-border);
  margin-top: 8px;
}

.camera-detail-actions--sticky {
  position: sticky;
  bottom: 0;
  background: var(--uf-bg-panel);
  z-index: 10;
  padding-bottom: 8px;
}

.button {
  height: 36px;
  padding: 0 14px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  cursor: pointer;
  transition: all 0.15s ease;
  border: 1px solid transparent;
}

.button--compact {
  height: 28px;
  padding: 0 10px;
  font-size: 12px;
}

.button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.button--primary {
  background: var(--uf-accent);
  color: #ffffff;
}

.button--primary:hover:not(:disabled) {
  opacity: 0.9;
}

.button--danger {
  background: #ef4444;
  color: #ffffff;
}

.button--danger:hover:not(:disabled) {
  background: #dc2626;
}

.button--ghost {
  background: transparent;
  border-color: var(--uf-border);
  color: var(--uf-text-secondary);
}

.button--ghost:hover:not(:disabled) {
  background: var(--uf-bg-card);
  color: var(--uf-text-primary);
  border-color: var(--uf-text-muted);
}
</style>
