<script setup lang="ts">
import {
  computed,
  onMounted,
  reactive,
  ref,
  watch
} from "vue"

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
  getRecordingPolicy,
  putRecordingPolicy,
  type RecordingPolicy,
  type RecordingPolicyPut,
  type RecordingScheduleWindow
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
  const labels: Record<CameraStreamBinding["purpose"], string> = {
    RECORD: "Recording",
    LIVE_HIGH: "Live · High",
    LIVE_LOW: "Live · Low",
    AI_DETECT: "AI detection",
    SNAPSHOT: "Snapshot",
    AUDIO: "Audio"
  }
  return labels[value]
}

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
    stream.has_audio ? "audio" : null
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
    notice.value = "Camera settings saved."
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
      ? "Camera enabled."
      : "Camera disabled."
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
      `Retire "${detail.value.name}"? Live viewing and recording will stop, but recordings and event history will be preserved.`
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
      ? "Camera restored to inventory. It remains disabled until explicitly enabled."
      : "Camera retired. Historical recordings and events are preserved."
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
        `missing: ${result.diff.profiles_missing.join(", ")}`
      )
    }
    if (result.diff.profiles_recovered.length) {
      messages.push(
        `recovered: ${result.diff.profiles_recovered.join(", ")}`
      )
    }
    if (result.diff.profiles_added.length) {
      messages.push(
        `added: ${result.diff.profiles_added.join(", ")}`
      )
    }
    if (result.diff.profiles_changed.length) {
      messages.push(
        `changed: ${result.diff.profiles_changed.join(", ")}`
      )
    }
    if (result.diff.capabilities_added.length) {
      messages.push(
        `capabilities added: ${result.diff.capabilities_added.join(", ")}`
      )
    }
    if (result.diff.capabilities_removed.length) {
      messages.push(
        `capabilities removed: ${result.diff.capabilities_removed.join(", ")}`
      )
    }

    notice.value = messages.length
      ? `ONVIF refresh complete · ${messages.join(" · ")}`
      : "ONVIF capabilities and profiles are unchanged."
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
    notice.value = "Stream bindings saved."
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
    notice.value = "Recording policy saved and reconciled."
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

watch(
  () => props.camera.id,
  () => {
    void load()
  }
)

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
</script>

<template>
  <aside class="camera-detail-drawer">
    <header class="camera-detail-header">
      <div>
        <strong>{{ detail?.name || camera.name }}</strong>
        <span>{{ detail?.location || camera.location || "No location" }}</span>
      </div>
      <button
        class="icon-button"
        type="button"
        title="Close"
        aria-label="Close camera details"
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
            ? "Retired"
            : detail?.enabled
              ? "Enabled"
              : "Disabled"
        }}
      </span>
      <span>{{ detail?.adapter_type || "manual" }}</span>
      <span v-if="policy?.runtime">
        {{
          policy.runtime.recording
            ? "Recording"
            : prettyRuntime(policy.runtime.desired_mode)
        }}
      </span>
    </div>

    <nav class="camera-detail-tabs">
      <button
        type="button"
        :class="{ 'camera-detail-tab--active': tab === 'general' }"
        @click="tab = 'general'"
      >
        General
      </button>
      <button
        type="button"
        :class="{ 'camera-detail-tab--active': tab === 'streams' }"
        @click="tab = 'streams'"
      >
        Streams
      </button>
      <button
        type="button"
        :class="{ 'camera-detail-tab--active': tab === 'recording' }"
        @click="tab = 'recording'"
      >
        Recording
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
      Loading camera…
    </div>

    <template v-else-if="detail">
      <form
        v-if="tab === 'general'"
        class="camera-detail-form"
        @submit.prevent="saveGeneral"
      >
        <label>
          <span>Name</span>
          <input v-model="generalForm.name" required maxlength="128" />
        </label>
        <label>
          <span>Location</span>
          <input v-model="generalForm.location" maxlength="256" />
        </label>
        <label>
          <span>Storage label</span>
          <input v-model="generalForm.storageLabel" maxlength="128" />
        </label>

        <div class="camera-detail-actions">
          <button
            v-if="canConfigure && !detail.retired_at"
            class="button button--ghost"
            type="button"
            @click="toggleEnabled"
          >
            {{ detail.enabled ? "Disable camera" : "Enable camera" }}
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
                ? "Saving…"
                : detail.retired_at
                  ? "Restore camera"
                  : "Retire camera"
            }}
          </button>
          <button
            class="button button--primary"
            type="submit"
            :disabled="savingGeneral || !canConfigure"
          >
            {{ savingGeneral ? "Saving…" : "Save" }}
          </button>
        </div>
      </form>

      <div v-else-if="tab === 'streams'" class="camera-stream-editor">
        <section class="camera-detail-section">
          <div
            class="camera-detail-section__heading camera-detail-section__heading--actions"
          >
            <div>
              <strong>Available profiles</strong>
              <span>Discovered/probed media profiles.</span>
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
                  ? "Refreshing…"
                  : "Refresh ONVIF"
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
              {{ stream.status }}
            </span>
          </article>
        </section>

        <section class="camera-detail-section">
          <div class="camera-detail-section__heading">
            <strong>Purpose bindings</strong>
            <span>One physical profile may serve multiple product purposes.</span>
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
              <option value="">Not assigned</option>
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
              {{ savingStreams ? "Saving…" : "Save bindings" }}
            </button>
          </div>
        </section>
      </div>

      <form
        v-else
        class="camera-recording-editor"
        @submit.prevent="saveRecording"
      >
        <section class="camera-detail-section">
          <div class="camera-detail-section__heading">
            <strong>Recording mode</strong>
            <span>Baseline recording and event promotion behavior.</span>
          </div>

          <div class="recording-mode-grid">
            <label
              v-for="item in [
                ['continuous', 'Continuous', 'Record all the time'],
                ['schedule', 'Scheduled', 'Record during weekly windows'],
                ['events', 'Events only', 'Prebuffer and promote matching events'],
                ['off', 'Off', 'Do not record this camera']
              ]"
              :key="item[0]"
              class="recording-mode-card"
              :class="{
                'recording-mode-card--active':
                  recordingForm.mode === item[0]
              }"
            >
              <input
                v-model="recordingForm.mode"
                type="radio"
                name="recording-mode"
                :value="item[0]"
                :disabled="!canConfigure"
              />
              <strong>{{ item[1] }}</strong>
              <span>{{ item[2] }}</span>
            </label>
          </div>

          <label
            v-if="recordingForm.mode === 'continuous' || recordingForm.mode === 'schedule'"
            class="storage-check"
          >
            <input
              v-model="recordingForm.eventRecording"
              type="checkbox"
              :disabled="!canConfigure"
            />
            <span>Also preserve event pre/post-roll metadata and event clips</span>
          </label>
        </section>

        <section
          v-if="recordingForm.mode === 'schedule'"
          class="camera-detail-section"
        >
          <div class="camera-detail-section__heading camera-detail-section__heading--actions">
            <div>
              <strong>Weekly schedule</strong>
              <span>Monday=Mon through Sunday=Sun in the selected timezone.</span>
            </div>
            <button
              class="button button--ghost button--compact"
              type="button"
              :disabled="!canConfigure"
              @click="addWindow"
            >
              <UiIcon name="plus" :size="13" />
              Add window
            </button>
          </div>

          <label class="camera-detail-field">
            <span>Timezone</span>
            <input
              v-model="recordingForm.timezone"
              :disabled="!canConfigure"
              required
              placeholder="America/Los_Angeles"
            />
          </label>

          <div class="recording-window-list">
            <article
              v-for="(window, index) in recordingForm.weekly"
              :key="index"
              class="recording-window"
            >
              <div class="recording-window__days">
                <button
                  v-for="(day, dayIndex) in ['Mon','Tue','Wed','Thu','Fri','Sat','Sun']"
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
                <span>to</span>
                <input
                  v-model="window.end"
                  type="time"
                  :disabled="!canConfigure"
                  required
                />
                <button
                  class="icon-button icon-button--danger"
                  type="button"
                  :disabled="!canConfigure || recordingForm.weekly.length <= 1"
                  @click="removeWindow(index)"
                >
                  <UiIcon name="trash" :size="14" />
                </button>
              </div>
            </article>
          </div>
        </section>

        <section
          v-if="recordingForm.mode !== 'off'"
          class="camera-detail-section"
        >
          <div class="camera-detail-section__heading">
            <strong>Recording parameters</strong>
            <span>Finalized segment and event buffer settings.</span>
          </div>

          <div class="camera-recording-number-grid">
            <label>
              <span>Segment seconds</span>
              <input
                v-model.number="recordingForm.segmentSeconds"
                type="number"
                :disabled="!canConfigure"
                min="10"
                max="3600"
              />
            </label>
            <label>
              <span>Pre-roll seconds</span>
              <input
                v-model.number="recordingForm.preRoll"
                type="number"
                :disabled="!canConfigure"
                min="0"
                max="600"
              />
            </label>
            <label>
              <span>Post-roll seconds</span>
              <input
                v-model.number="recordingForm.postRoll"
                type="number"
                :disabled="!canConfigure"
                min="0"
                max="600"
              />
            </label>
          </div>

          <div class="camera-recording-number-grid camera-recording-number-grid--two">
            <label>
              <span>Local storage target</span>
              <select
                v-model="recordingForm.storageTargetId"
                :disabled="!canConfigure"
              >
                <option value="">Use default local target</option>
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
              <span>Retention policy</span>
              <select
                v-model="recordingForm.retentionPolicyId"
                :disabled="!canConfigure"
              >
                <option value="">Inherit retention</option>
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

        <section
          v-if="recordingForm.mode === 'events' || recordingForm.eventRecording"
          class="camera-detail-section"
        >
          <div class="camera-detail-section__heading">
            <strong>Event filter</strong>
            <span>Blank labels/zones match all provider events.</span>
          </div>

          <label class="camera-detail-field">
            <span>Labels</span>
            <input
              v-model="recordingForm.labels"
              :disabled="!canConfigure"
              placeholder="person, car, dog"
            />
          </label>
          <label class="camera-detail-field">
            <span>Zones</span>
            <input
              v-model="recordingForm.zones"
              :disabled="!canConfigure"
              placeholder="front_yard, driveway"
            />
          </label>
          <label class="camera-detail-field">
            <span>Minimum confidence · {{ Math.round(recordingForm.minConfidence * 100) }}%</span>
            <input
              v-model.number="recordingForm.minConfidence"
              type="range"
              :disabled="!canConfigure"
              min="0"
              max="1"
              step="0.05"
            />
          </label>
        </section>

        <div class="camera-detail-actions camera-detail-actions--sticky">
          <button
            class="button button--primary"
            type="submit"
            :disabled="savingRecording || !canConfigure"
          >
            {{
              savingRecording
                ? "Applying…"
                : "Save & reconcile recording"
            }}
          </button>
        </div>
      </form>
    </template>
  </aside>
</template>

<script lang="ts">
function prettyRuntime(value: string): string {
  return value === "prebuffer"
    ? "Prebuffering"
    : value === "persistent"
      ? "Recording"
      : "Idle"
}
</script>

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

@media (max-width: 540px) {
  .recording-mode-grid,
  .camera-recording-number-grid,
  .camera-recording-number-grid--two {
    grid-template-columns: 1fr;
  }

  .camera-binding-row {
    grid-template-columns: 1fr;
  }
}
</style>
