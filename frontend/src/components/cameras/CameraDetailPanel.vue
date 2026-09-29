<script setup lang="ts">
import {
  computed,
  onMounted,
  onBeforeUnmount,
  reactive,
  ref,
  watch
} from "vue"
import { useI18n } from "vue-i18n"

import {
  getCamera,
  refreshOnvifCapabilities,
  replaceCameraBindings,
  retireCamera,
  restoreCamera,
  setCameraEnabled,
  updateCamera,
  type CameraDetail,
  type CameraStreamBinding,
  type CameraStreamProfile,
  type CameraSummary
} from "../../api/cameras"
import {
  ApiClientError,
  errorMessage
} from "../../api/client"
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
} from "../../api/recordings"
import {
  listRetentionPolicies,
  listStorageTargets,
  type RetentionPolicy,
  type StorageTarget
} from "../../api/storage"
import UiIcon from "../ui/UiIcon.vue"
import { useAuthStore } from "../../stores/auth"

type DetailTab = "general" | "streams" | "recording"
type RecordingMode = "continuous" | "schedule" | "events" | "off"

const props = defineProps<{
  camera: CameraSummary
}>()

const emit = defineEmits<{
  close: []
  changed: []
}>()

const auth = useAuthStore()
const { t, te } = useI18n({ useScope: "global" })
const tab = ref<DetailTab>("general")
const detail = ref<CameraDetail | null>(null)
const policy = ref<RecordingPolicy | null>(null)
const localTargets = ref<StorageTarget[]>([])
const retentionPolicies = ref<RetentionPolicy[]>([])
const loading = ref(false)
const savingGeneral = ref(false)
const savingStreams = ref(false)
const refreshingCapabilities = ref(false)
const savingRecording = ref(false)
const retirementSaving = ref(false)
const error = ref<string | null>(null)
const notice = ref<string | null>(null)

const generalForm = reactive({
  name: "",
  location: "",
  storageLabel: ""
})

const purposes: CameraStreamBinding["purpose"][] = [
  "RECORD",
  "LIVE_HIGH",
  "LIVE_LOW",
  "AI_DETECT",
  "SNAPSHOT",
  "AUDIO"
]

const bindingForm = reactive<Record<CameraStreamBinding["purpose"], string>>({
  RECORD: "",
  LIVE_HIGH: "",
  LIVE_LOW: "",
  AI_DETECT: "",
  SNAPSHOT: "",
  AUDIO: ""
})

const recordingForm = reactive({
  mode: "continuous" as RecordingMode,
  eventRecording: false,
  timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
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

// Manual Recording state
const activeManualTrigger = ref<RecordingTrigger | null>(null)
const manualRecordingBusy = ref(false)
const manualReason = ref("")
const manualElapsedSeconds = ref(0)
let manualTimer: number | null = null

// Smart Tags configuration
export interface SmartTag {
  key: string
  label: string
  emoji: string
  aliases: string[]
}

const SMART_TAGS: SmartTag[] = [
  { key: "person", label: "人体 / 访客", emoji: "🚶", aliases: ["person"] },
  { key: "vehicle", label: "机动车", emoji: "🚗", aliases: ["vehicle", "car"] },
  { key: "bicycle", label: "两轮车", emoji: "🛵", aliases: ["bicycle", "motorcycle"] },
  { key: "pet", label: "宠物动物", emoji: "🐕", aliases: ["pet", "dog", "cat", "animal"] },
  { key: "package", label: "快递包裹", emoji: "📦", aliases: ["package"] },
  { key: "motion", label: "画面动态", emoji: "🏃", aliases: ["motion"] }
]

const canConfigure = computed(() =>
  auth.hasPermission("camera.configure")
)

const videoStreams = computed(() =>
  (detail.value?.streams ?? []).filter((item) =>
    Boolean(item.codec)
  )
)

const audioStreams = computed(() =>
  (detail.value?.streams ?? []).filter((item) => item.has_audio)
)

function purposeLabel(value: CameraStreamBinding["purpose"]): string {
  const keys: Record<CameraStreamBinding["purpose"], string> = {
    RECORD: "cameras.detail.purpose.recording",
    LIVE_HIGH: "cameras.detail.purpose.liveHigh",
    LIVE_LOW: "cameras.detail.purpose.liveLow",
    AI_DETECT: "cameras.detail.purpose.aiDetection",
    SNAPSHOT: "cameras.detail.purpose.snapshot",
    AUDIO: "cameras.detail.purpose.audio"
  }
  return t(keys[value])
}

function streamStatusLabel(value: string): string {
  const key = `cameras.detail.streamStatus.${value.toLowerCase()}`
  return te(key) ? t(key) : value
}

function runtimeLabel(value: string): string {
  if (value === "prebuffer") return t("cameras.detail.runtime.prebuffering")
  if (value === "persistent") return t("cameras.detail.runtime.recording")
  return t("cameras.detail.runtime.idle")
}

const weekdays = computed(() => [
  t("cameras.detail.weekdays.mon"),
  t("cameras.detail.weekdays.tue"),
  t("cameras.detail.weekdays.wed"),
  t("cameras.detail.weekdays.thu"),
  t("cameras.detail.weekdays.fri"),
  t("cameras.detail.weekdays.sat"),
  t("cameras.detail.weekdays.sun")
])

const recordingModes = computed(() => [
  { value: "continuous" as RecordingMode, label: t("cameras.detail.continuous"), description: t("cameras.detail.recordAllTime") },
  { value: "schedule" as RecordingMode, label: t("cameras.detail.scheduled"), description: t("cameras.detail.recordWeekly") },
  { value: "events" as RecordingMode, label: t("cameras.detail.eventsOnly"), description: t("cameras.detail.promoteEvents") },
  { value: "off" as RecordingMode, label: t("cameras.detail.off"), description: t("cameras.detail.doNotRecord") }
])

function streamsForPurpose(
  purpose: CameraStreamBinding["purpose"]
): CameraStreamProfile[] {
  return purpose === "AUDIO"
    ? audioStreams.value
    : videoStreams.value
}

function streamDescription(stream: CameraStreamProfile): string {
  const pieces = [
    stream.codec?.toUpperCase(),
    stream.width && stream.height
      ? `${stream.width}×${stream.height}`
      : null,
    stream.fps ? `${Math.round(stream.fps)} fps` : null,
    stream.bitrate_kbps ? `${stream.bitrate_kbps} kbps` : null,
    stream.has_audio ? t("cameras.detail.audio") : null
  ].filter(Boolean)
  return pieces.join(" · ") || stream.adapter_profile_key
}

function resetGeneral(value: CameraDetail): void {
  generalForm.name = value.name
  generalForm.location = value.location ?? ""
  generalForm.storageLabel = value.storage_label ?? ""
}

function resetBindings(value: CameraDetail): void {
  for (const purpose of purposes) {
    bindingForm[purpose] =
      value.bindings.find((item) => item.purpose === purpose)
        ?.stream_profile_id ?? ""
  }
}

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
    recordingForm.mode === "events"
      ? true
      : value.event_recording_enabled
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
  recordingForm.minConfidence =
    value.event_filter.min_confidence ?? 0.6
  recordingForm.weekly =
    value.schedule.weekly?.map((item) => ({
      days: [...item.days],
      start: item.start,
      end: item.end
    })) ?? defaultWeekly()
}

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const [cameraValue, targetValues, retentionValues] =
      await Promise.all([
        getCamera(props.camera.id),
        auth.hasPermission("storage.manage")
          ? listStorageTargets()
          : Promise.resolve([]),
        auth.hasPermission("storage.manage")
          ? listRetentionPolicies()
          : Promise.resolve([])
      ])

    detail.value = cameraValue
    localTargets.value = targetValues.filter(
      (item) =>
        item.type === "local" &&
        item.role === "recording" &&
        item.enabled
    )
    retentionPolicies.value = retentionValues.filter(
      (item) => item.enabled
    )
    resetGeneral(cameraValue)
    resetBindings(cameraValue)

    try {
      policy.value = await getRecordingPolicy(props.camera.id)
    } catch (caught) {
      if (
        caught instanceof ApiClientError &&
        caught.code === "recording_policy_not_configured"
      ) {
        policy.value = null
      } else {
        throw caught
      }
    }
    resetPolicy(policy.value)
    void loadManualTrigger()
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    loading.value = false
  }
}

async function saveGeneral(): Promise<void> {
  if (!detail.value) return
  savingGeneral.value = true
  error.value = null
  notice.value = null
  try {
    const updated = await updateCamera(detail.value.id, {
      name: generalForm.name.trim(),
      location: generalForm.location.trim() || null,
      storage_label: generalForm.storageLabel.trim() || null
    })
    detail.value = updated
    resetGeneral(updated)
    notice.value = t("cameras.detail.settingsSaved")
    emit("changed")
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    savingGeneral.value = false
  }
}

async function toggleEnabled(): Promise<void> {
  if (!detail.value) return
  error.value = null
  notice.value = null
  try {
    const updated = await setCameraEnabled(
      detail.value.id,
      !detail.value.enabled
    )
    detail.value = updated
    notice.value = updated.enabled
      ? t("cameras.detail.enabledNotice")
      : t("cameras.detail.disabledNotice")
    emit("changed")
  } catch (caught) {
    error.value = errorMessage(caught)
  }
}

async function toggleRetired(): Promise<void> {
  if (!detail.value || !canConfigure.value) return

  const restoring = Boolean(detail.value.retired_at)
  if (
    !restoring &&
    !window.confirm(
      t("cameras.detail.retireConfirm", { name: detail.value.name })
    )
  ) {
    return
  }

  retirementSaving.value = true
  error.value = null
  notice.value = null
  try {
    const updated = restoring
      ? await restoreCamera(detail.value.id)
      : await retireCamera(detail.value.id)
    detail.value = updated
    notice.value = restoring
      ? t("cameras.detail.restoredNotice")
      : t("cameras.detail.retiredNotice")
    emit("changed")
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    retirementSaving.value = false
  }
}

async function refreshCapabilities(): Promise<void> {
  if (
    !detail.value ||
    detail.value.adapter_type !== "onvif" ||
    !canConfigure.value
  ) {
    return
  }

  refreshingCapabilities.value = true
  error.value = null
  notice.value = null
  try {
    const result = await refreshOnvifCapabilities(
      detail.value.id
    )
    const refreshed = result.cameras.find(
      (item) => item.id === detail.value?.id
    )
    if (refreshed) {
      detail.value = refreshed
      resetBindings(refreshed)
    }

    const messages: string[] = []
    if (result.diff.profiles_missing.length) {
      messages.push(
        t("cameras.detail.refreshMissing", { items: result.diff.profiles_missing.join(", ") })
      )
    }
    if (result.diff.profiles_recovered.length) {
      messages.push(
        t("cameras.detail.refreshRecovered", { items: result.diff.profiles_recovered.join(", ") })
      )
    }
    if (result.diff.profiles_added.length) {
      messages.push(
        t("cameras.detail.refreshAdded", { items: result.diff.profiles_added.join(", ") })
      )
    }
    if (result.diff.profiles_changed.length) {
      messages.push(
        t("cameras.detail.refreshChanged", { items: result.diff.profiles_changed.join(", ") })
      )
    }
    if (result.diff.capabilities_added.length) {
      messages.push(
        t("cameras.detail.capabilitiesAdded", { items: result.diff.capabilities_added.join(", ") })
      )
    }
    if (result.diff.capabilities_removed.length) {
      messages.push(
        t("cameras.detail.capabilitiesRemoved", { items: result.diff.capabilities_removed.join(", ") })
      )
    }

    notice.value = messages.length
      ? t("cameras.detail.refreshComplete", { details: messages.join(" · ") })
      : t("cameras.detail.refreshUnchanged")
    emit("changed")
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    refreshingCapabilities.value = false
  }
}

async function saveStreams(): Promise<void> {
  if (!detail.value) return
  savingStreams.value = true
  error.value = null
  notice.value = null
  try {
    const bindings = purposes
      .filter((purpose) => Boolean(bindingForm[purpose]))
      .map((purpose) => ({
        purpose,
        stream_profile_id: bindingForm[purpose],
        selection_mode: "manual" as const
      }))

    const updated = await replaceCameraBindings(
      detail.value.id,
      bindings
    )
    detail.value.bindings = updated
    resetBindings(detail.value)
    notice.value = t("cameras.detail.bindingsSaved")
    emit("changed")
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    savingStreams.value = false
  }
}

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
    schedule_timezone: scheduled
      ? recordingForm.timezone.trim()
      : null,
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
  if (!detail.value) return
  savingRecording.value = true
  error.value = null
  notice.value = null
  try {
    policy.value = await putRecordingPolicy(
      detail.value.id,
      buildPolicy()
    )
    resetPolicy(policy.value)
    notice.value = t("cameras.detail.policySaved")
    emit("changed")
  } catch (caught) {
    error.value = errorMessage(caught)
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

// Manual recording methods
async function loadManualTrigger(): Promise<void> {
  if (!props.camera?.id) return
  try {
    const triggers = await listRecordingTriggers(props.camera.id)
    const active = triggers.find(
      (t) => t.type.toUpperCase() === "MANUAL" && t.state === "ACTIVE" && !t.planned_end_at
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
  if (!canConfigure.value || manualRecordingBusy.value) return
  manualRecordingBusy.value = true
  error.value = null
  notice.value = null
  try {
    const trigger = await createRecordingTrigger(
      props.camera.id,
      manualReason.value.trim() || "配置中心手动触发保全录像"
    )
    activeManualTrigger.value = trigger
    startManualTimer()
    notice.value = "⏺️ 手动录像已启动，已提升 10 秒前置预录并写入保全存储区"
    manualReason.value = ""
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    manualRecordingBusy.value = false
  }
}

async function handleStopManual(): Promise<void> {
  if (!canConfigure.value || manualRecordingBusy.value || !activeManualTrigger.value) return
  manualRecordingBusy.value = true
  error.value = null
  notice.value = null
  try {
    await stopRecordingTrigger(activeManualTrigger.value.id)
    activeManualTrigger.value = null
    startManualTimer()
    notice.value = "⏹️ 手动录像已停止，录像切片已归档入库"
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    manualRecordingBusy.value = false
  }
}

// Schedule presets & matrix helpers
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

// Smart tag selection helpers
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

watch(
  () => props.camera.id,
  () => {
    void load()
    void loadManualTrigger()
  }
)

watch(tab, (newTab) => {
  if (newTab === "recording") {
    void loadManualTrigger()
  }
})

watch(
  () => recordingForm.mode,
  (value) => {
    if (value === "events") {
      recordingForm.eventRecording = true
    }
    if (value === "schedule" && !recordingForm.weekly.length) {
      recordingForm.weekly = defaultWeekly()
    }
  }
)

onMounted(() => {
  void load()
})

onBeforeUnmount(() => {
  if (manualTimer !== null) {
    window.clearInterval(manualTimer)
    manualTimer = null
  }
})
</script>

<template>
  <aside class="camera-detail-drawer">
    <header class="camera-detail-header">
      <div>
        <strong>{{ detail?.name || camera.name }}</strong>
        <span>{{ detail?.location || camera.location || t("cameras.noLocation") }}</span>
      </div>
      <button
        class="icon-button"
        type="button"
        :title="t('cameras.detail.close')"
        :aria-label="t('cameras.detail.closeAria')"
        @click="emit('close')"
      >
        <UiIcon name="close" :size="16" />
      </button>
    </header>

    <div class="camera-detail-status">
      <span
        class="status-pill"
        :class="detail?.enabled ? 'status-pill--ok' : 'status-pill--muted'"
      >
        {{
          detail?.retired_at
            ? t("cameras.retired")
            : detail?.enabled
              ? t("cameras.enabled")
              : t("cameras.disabled")
        }}
      </span>
      <span>{{ detail?.adapter_type || "manual" }}</span>
      <span v-if="policy?.runtime">
        {{
          policy.runtime.recording
            ? t("cameras.detail.recording")
            : runtimeLabel(policy.runtime.desired_mode)
        }}
      </span>
    </div>

    <nav class="camera-detail-tabs">
      <button
        type="button"
        :class="{ 'camera-detail-tab--active': tab === 'general' }"
        @click="tab = 'general'"
      >
        {{ t("cameras.detail.general") }}
      </button>
      <button
        type="button"
        :class="{ 'camera-detail-tab--active': tab === 'streams' }"
        @click="tab = 'streams'"
      >
        {{ t("cameras.detail.streams") }}
      </button>
      <button
        type="button"
        :class="{ 'camera-detail-tab--active': tab === 'recording' }"
        @click="tab = 'recording'"
      >
        {{ t("cameras.detail.recording") }}
      </button>
    </nav>

    <div v-if="error" class="camera-detail-message camera-detail-message--error">
      {{ error }}
    </div>
    <div v-if="notice" class="camera-detail-message camera-detail-message--ok">
      {{ notice }}
    </div>

    <div v-if="loading" class="camera-detail-loading">
      <UiIcon name="refresh" :size="18" />
      {{ t("cameras.detail.loadingCamera") }}
    </div>

    <template v-else-if="detail">
      <form
        v-if="tab === 'general'"
        class="camera-detail-form"
        @submit.prevent="saveGeneral"
      >
        <label>
          <span>{{ t("cameras.name") }}</span>
          <input v-model="generalForm.name" required maxlength="128" />
        </label>
        <label>
          <span>{{ t("cameras.location") }}</span>
          <input v-model="generalForm.location" maxlength="256" />
        </label>
        <label>
          <span>{{ t("cameras.storageLabel") }}</span>
          <input v-model="generalForm.storageLabel" maxlength="128" />
        </label>

        <div class="camera-detail-actions">
          <button
            v-if="canConfigure && !detail.retired_at"
            class="button button--ghost"
            type="button"
            @click="toggleEnabled"
          >
            {{ detail.enabled ? t("cameras.detail.disableCamera") : t("cameras.detail.enableCamera") }}
          </button>
          <button
            v-if="canConfigure"
            class="button button--ghost"
            type="button"
            :disabled="retirementSaving"
            @click="toggleRetired"
          >
            {{
              retirementSaving
                ? t("cameras.detail.saving")
                : detail.retired_at
                  ? t("cameras.detail.restoreCamera")
                  : t("cameras.detail.retireCamera")
            }}
          </button>
          <button
            class="button button--primary"
            type="submit"
            :disabled="savingGeneral || !canConfigure"
          >
            {{ savingGeneral ? t("cameras.detail.saving") : t("cameras.detail.save") }}
          </button>
        </div>
      </form>

      <div v-else-if="tab === 'streams'" class="camera-stream-editor">
        <section class="camera-detail-section">
          <div
            class="camera-detail-section__heading camera-detail-section__heading--actions"
          >
            <div>
              <strong>{{ t("cameras.detail.availableProfiles") }}</strong>
              <span>{{ t("cameras.detail.profilesHint") }}</span>
            </div>
            <button
              v-if="detail.adapter_type === 'onvif'"
              class="button button--ghost button--compact"
              type="button"
              :disabled="refreshingCapabilities || !canConfigure"
              @click="refreshCapabilities"
            >
              <UiIcon name="refresh" :size="12" />
              {{
                refreshingCapabilities
                  ? t("cameras.detail.refreshing")
                  : t("cameras.detail.refreshOnvif")
              }}
            </button>
          </div>

          <article
            v-for="stream in detail.streams"
            :key="stream.id"
            class="camera-stream-profile"
          >
            <div>
              <strong>{{ stream.name }}</strong>
              <span>{{ streamDescription(stream) }}</span>
            </div>
            <span class="status-pill">
              {{ streamStatusLabel(stream.status) }}
            </span>
          </article>
        </section>

        <section class="camera-detail-section">
          <div class="camera-detail-section__heading">
            <strong>{{ t("cameras.detail.purposeBindings") }}</strong>
            <span>{{ t("cameras.detail.purposeHint") }}</span>
          </div>

          <label
            v-for="purpose in purposes"
            :key="purpose"
            class="camera-binding-row"
          >
            <span>{{ purposeLabel(purpose) }}</span>
            <select
              v-model="bindingForm[purpose]"
              :disabled="!canConfigure"
            >
              <option value="">{{ t("cameras.detail.notAssigned") }}</option>
              <option
                v-for="stream in streamsForPurpose(purpose)"
                :key="stream.id"
                :value="stream.id"
              >
                {{ stream.name }} · {{ streamDescription(stream) }}
              </option>
            </select>
          </label>

          <div class="camera-detail-actions">
            <button
              class="button button--primary"
              type="button"
              :disabled="savingStreams || !canConfigure"
              @click="saveStreams"
            >
              {{ savingStreams ? t("cameras.detail.saving") : t("cameras.detail.saveBindings") }}
            </button>
          </div>
        </section>
      </div>

      <form
        v-else
        class="camera-recording-editor"
        @submit.prevent="saveRecording"
      >
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
  </aside>
</template>


<style scoped>
.camera-detail-drawer {
  position: fixed;
  top: var(--topbar-height);
  right: 0;
  bottom: 0;
  z-index: 45;
  display: flex;
  width: min(520px, 96vw);
  flex-direction: column;
  overflow: hidden;
  border-left: 1px solid var(--border-subtle);
  background: var(--surface-raised);
  box-shadow: -18px 0 48px rgba(0, 0, 0, 0.2);
}

.camera-detail-header {
  display: flex;
  min-height: 58px;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 0 12px 0 15px;
  border-bottom: 1px solid var(--border-subtle);
}

.camera-detail-header strong,
.camera-detail-header span {
  display: block;
}

.camera-detail-header strong {
  font-size: 13px;
}

.camera-detail-header span {
  margin-top: 2px;
  color: var(--text-muted);
  font-size: 9px;
}

.camera-detail-status {
  display: flex;
  min-height: 36px;
  align-items: center;
  gap: 8px;
  padding: 0 14px;
  border-bottom: 1px solid var(--border-subtle);
  color: var(--text-muted);
  font-size: 8px;
}

.camera-detail-tabs {
  display: flex;
  padding: 0 8px;
  border-bottom: 1px solid var(--border-subtle);
}

.camera-detail-tabs button {
  position: relative;
  min-height: 38px;
  padding: 0 10px;
  border: 0;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 9px;
  font-weight: 600;
}

.camera-detail-tabs button::after {
  position: absolute;
  right: 9px;
  bottom: -1px;
  left: 9px;
  height: 2px;
  border-radius: 2px;
  background: transparent;
  content: "";
}

.camera-detail-tabs .camera-detail-tab--active {
  color: var(--text-primary);
}

.camera-detail-tabs .camera-detail-tab--active::after {
  background: var(--accent);
}

.camera-detail-message {
  margin: 9px 12px 0;
  padding: 7px 8px;
  border-radius: var(--radius-sm);
  font-size: 9px;
}

.camera-detail-message--error {
  background: var(--danger-soft);
  color: var(--danger);
}

.camera-detail-message--ok {
  background: var(--success-soft);
  color: var(--success);
}

.camera-detail-loading {
  display: flex;
  min-height: 240px;
  align-items: center;
  justify-content: center;
  gap: 7px;
  color: var(--text-muted);
  font-size: 9px;
}

.camera-detail-form,
.camera-stream-editor,
.camera-recording-editor {
  min-height: 0;
  flex: 1;
  overflow-y: auto;
}

.camera-detail-form {
  display: grid;
  align-content: start;
  gap: 11px;
  padding: 14px;
}

.camera-detail-form label,
.camera-detail-field,
.camera-recording-number-grid label {
  display: grid;
  gap: 5px;
}

.camera-detail-form label > span,
.camera-detail-field > span,
.camera-recording-number-grid label > span {
  color: var(--text-muted);
  font-size: 8px;
  font-weight: 650;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.camera-detail-form input,
.camera-detail-field input,
.camera-recording-number-grid input,
.camera-recording-number-grid select,
.camera-binding-row select,
.recording-window input {
  width: 100%;
  min-height: 34px;
  padding: 0 8px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  outline: none;
  background: var(--surface-base);
  color: var(--text-primary);
  font: inherit;
  font-size: 10px;
}

.camera-detail-form input:focus,
.camera-detail-field input:focus,
.camera-recording-number-grid input:focus,
.camera-recording-number-grid select:focus,
.camera-binding-row select:focus,
.recording-window input:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--focus-ring);
}

.camera-detail-actions {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
  margin-top: 5px;
}

.camera-detail-actions--sticky {
  position: sticky;
  bottom: 0;
  z-index: 4;
  margin: 0;
  padding: 10px 13px;
  border-top: 1px solid var(--border-subtle);
  background: var(--surface-raised);
}

.camera-detail-section {
  display: grid;
  gap: 9px;
  padding: 13px 14px;
  border-bottom: 1px solid var(--border-subtle);
}

.camera-detail-section__heading strong,
.camera-detail-section__heading span {
  display: block;
}

.camera-detail-section__heading strong {
  font-size: 10px;
}

.camera-detail-section__heading span {
  margin-top: 2px;
  color: var(--text-muted);
  font-size: 8px;
}

.camera-detail-section__heading--actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.camera-stream-profile {
  display: flex;
  min-height: 48px;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 9px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: var(--surface-base);
}

.camera-stream-profile div {
  min-width: 0;
}

.camera-stream-profile strong,
.camera-stream-profile div > span {
  display: block;
}

.camera-stream-profile strong {
  font-size: 9px;
}

.camera-stream-profile div > span {
  overflow: hidden;
  margin-top: 2px;
  color: var(--text-muted);
  font-size: 8px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.camera-binding-row {
  display: grid;
  grid-template-columns: 100px minmax(0, 1fr);
  align-items: center;
  gap: 8px;
}

.camera-binding-row > span {
  color: var(--text-secondary);
  font-size: 9px;
}

.recording-mode-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
}

.recording-mode-card {
  position: relative;
  display: grid;
  gap: 3px;
  min-height: 68px;
  padding: 10px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: var(--surface-base);
  cursor: pointer;
}

.recording-mode-card input {
  position: absolute;
  opacity: 0;
}

.recording-mode-card strong {
  font-size: 9px;
}

.recording-mode-card span {
  color: var(--text-muted);
  font-size: 8px;
  line-height: 1.35;
}

.recording-mode-card--active {
  border-color: var(--accent);
  box-shadow: 0 0 0 1px var(--accent);
}

.recording-window-list {
  display: grid;
  gap: 7px;
}

.recording-window {
  display: grid;
  gap: 7px;
  padding: 8px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: var(--surface-base);
}

.recording-window__days {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 3px;
}

.recording-window__days button {
  min-height: 26px;
  padding: 0;
  border: 1px solid var(--border-subtle);
  border-radius: 4px;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 7px;
}

.recording-window__days .recording-day--active {
  border-color: var(--accent);
  background: var(--accent-soft);
  color: var(--accent);
}

.recording-window__time {
  display: grid;
  grid-template-columns: 1fr auto 1fr 30px;
  align-items: center;
  gap: 6px;
}

.recording-window__time > span {
  color: var(--text-muted);
  font-size: 8px;
}

.camera-recording-number-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 7px;
}

.camera-recording-number-grid--two {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

/* Manual Recording Section */
.manual-recording-section {
  background: rgba(239, 68, 68, 0.04);
  border-left: 3px solid #ef4444;
}

.manual-heading-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.manual-badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 7px;
  border-radius: 9999px;
  font-size: 10px;
  font-weight: 600;
  font-family: monospace;
}

.manual-badge--active {
  background: rgba(239, 68, 68, 0.2);
  color: #fca5a5;
  border: 1px solid rgba(239, 68, 68, 0.4);
}

.manual-badge--idle {
  background: rgba(255, 255, 255, 0.05);
  color: #9ca3af;
  border: 1px solid rgba(255, 255, 255, 0.1);
}

.manual-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  margin-right: 5px;
}

.manual-recording-box {
  margin-top: 8px;
}

.manual-active-details {
  margin-bottom: 8px;
  padding: 6px 9px;
  background: rgba(0, 0, 0, 0.3);
  border-radius: var(--radius-sm);
  border: 1px solid rgba(255, 255, 255, 0.08);
}

.manual-start-row {
  display: flex;
  gap: 7px;
  align-items: center;
}

.manual-reason-input {
  flex: 1;
  min-height: 32px;
  padding: 0 9px;
  background: var(--surface-base);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  font-size: 11px;
}

.manual-action-btn {
  min-height: 32px;
  white-space: nowrap;
  font-size: 11px;
  font-weight: 600;
}

/* Mode Cards Header */
.recording-mode-card__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}

.mode-tag {
  font-size: 8px;
  padding: 1px 5px;
  border-radius: 4px;
  font-weight: 600;
}

.event-toggle-card {
  margin-top: 8px;
  padding: 9px 11px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: var(--surface-base);
}

/* Schedule Presets & Matrix */
.schedule-presets-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  padding: 7px 9px;
  background: var(--surface-base);
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-subtle);
}

.preset-chip {
  padding: 3px 8px;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 4px;
  color: var(--text-primary);
  font-size: 10px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.preset-chip:hover {
  background: var(--accent-soft);
  border-color: var(--accent);
  color: var(--accent);
}

.schedule-matrix-box {
  margin-top: 8px;
  padding: 9px 11px;
  background: #0d1017;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: var(--radius-sm);
}

.schedule-scale {
  display: flex;
  justify-content: space-between;
  padding-left: 28px;
  padding-right: 56px;
  color: #6b7280;
  font-family: monospace;
  font-size: 8px;
  margin-bottom: 4px;
}

.schedule-matrix-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.schedule-matrix-row:last-child {
  margin-bottom: 0;
}

.schedule-matrix-day {
  width: 20px;
  color: #9ca3af;
  font-size: 9px;
  font-weight: 600;
  text-align: center;
}

.schedule-matrix-track {
  flex: 1;
  position: relative;
  height: 14px;
  background: rgba(255, 255, 255, 0.06);
  border-radius: 2px;
  overflow: hidden;
}

.schedule-matrix-bar {
  position: absolute;
  top: 0;
  bottom: 0;
  background: #3b82f6;
  border-radius: 2px;
  box-shadow: 0 0 4px rgba(59, 130, 246, 0.5);
}

.schedule-matrix-hours {
  width: 52px;
  text-align: right;
  font-size: 9px;
  color: #93c5fd;
}

.window-quick-btn {
  padding: 3px 6px;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 3px;
  color: #d1d5db;
  font-size: 9px;
  cursor: pointer;
}

.window-quick-btn:hover {
  background: var(--accent-soft);
  border-color: var(--accent);
  color: var(--accent);
}

/* Smart Tags Chips */
.smart-tags-block {
  margin-bottom: 8px;
}

.smart-tags-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 5px;
}

.smart-tag-chip {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 6px 8px;
  background: var(--surface-base);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  font-size: 10px;
  cursor: pointer;
  transition: all 0.15s ease;
  text-align: left;
}

.smart-tag-chip:hover {
  border-color: rgba(59, 130, 246, 0.5);
}

.smart-tag-chip--active {
  background: rgba(59, 130, 246, 0.15);
  border-color: #3b82f6;
  color: #93c5fd;
  font-weight: 600;
}

.tag-emoji {
  font-size: 13px;
}

.tag-label {
  flex: 1;
}

.tag-key {
  color: #6b7280;
}

/* Visual Timeline Diagram */
.timeline-diagram-card {
  margin: 10px 0;
  padding: 9px 12px;
  background: #0e121a;
  border: 1px solid rgba(59, 130, 246, 0.2);
  border-radius: var(--radius-sm);
}

.timeline-diagram-flow {
  display: flex;
  align-items: center;
  gap: 6px;
}

.timeline-diagram-block {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 6px 8px;
  border-radius: 4px;
  text-align: center;
}

.timeline-diagram-block--pre {
  background: rgba(16, 185, 129, 0.12);
  border: 1px solid rgba(16, 185, 129, 0.3);
}

.timeline-diagram-block--event {
  background: rgba(239, 68, 68, 0.15);
  border: 1px solid rgba(239, 68, 68, 0.4);
}

.timeline-diagram-block--post {
  background: rgba(59, 130, 246, 0.12);
  border: 1px solid rgba(59, 130, 246, 0.3);
}

.timeline-diagram-arrow {
  color: #6b7280;
  font-weight: bold;
}

.block-title {
  font-size: 9px;
  font-weight: 700;
  color: #ffffff;
}

.block-desc {
  font-size: 7px;
  color: #9ca3af;
  margin: 2px 0;
  line-height: 1.2;
}

.block-val {
  font-size: 10px;
  font-weight: bold;
  color: #f3f4f6;
}

/* Confidence Slider Block */
.confidence-slider-block {
  margin: 8px 0;
  padding: 8px 10px;
  background: var(--surface-base);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
}

.confidence-slider {
  width: 100%;
  margin-top: 6px;
}

.advanced-filter-fields {
  margin-top: 6px;
  display: grid;
  gap: 6px;
}

@media (max-width: 540px) {
  .recording-mode-grid,
  .camera-recording-number-grid,
  .camera-recording-number-grid--two,
  .smart-tags-grid {
    grid-template-columns: 1fr;
  }

  .camera-binding-row {
    grid-template-columns: 1fr;
  }
}
</style>
