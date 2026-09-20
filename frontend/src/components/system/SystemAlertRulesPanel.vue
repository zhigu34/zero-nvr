<script setup lang="ts">
import {
  computed,
  onMounted,
  reactive,
  ref
} from "vue"

import {
  createAlertPolicy,
  deleteAlertPolicy,
  listAlertPolicies,
  updateAlertPolicy,
  type AlertPolicy
} from "../../api/alerts"
import {
  listCameras,
  type CameraSummary
} from "../../api/cameras"
import { errorMessage } from "../../api/client"
import {
  listNotificationTargets,
  type NotificationTarget
} from "../../api/system"
import UiIcon from "../ui/UiIcon.vue"

const props = defineProps<{
  displayTimezone: string
}>()

const policies = ref<AlertPolicy[]>([])
const cameras = ref<CameraSummary[]>([])
const targets = ref<NotificationTarget[]>([])
const loading = ref(false)
const saving = ref(false)
const error = ref<string | null>(null)
const notice = ref<string | null>(null)
const editorOpen = ref(false)
const editingId = ref<string | null>(null)

const form = reactive({
  name: "",
  enabled: true,
  severity: "warning" as "info" | "warning" | "critical",
  cameraIds: [] as string[],
  categories: "",
  labels: "",
  zones: "",
  minConfidence: 0.6,
  useMinConfidence: false,
  minDuration: 0,
  weekdays: [0, 1, 2, 3, 4, 5, 6] as number[],
  useTimeWindow: false,
  timeStart: "00:00",
  timeEnd: "23:59",
  timezone: "UTC",
  cooldownSeconds: 60,
  notificationTargetIds: [] as string[],
  protectRecording: false,
  protectBefore: 10,
  protectAfter: 20,
  protectExpiresDays: 0
})

const enabledCount = computed(() =>
  policies.value.filter((item) => item.enabled).length
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

function stringArray(
  value: unknown
): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : []
}

function numberArray(
  value: unknown
): number[] {
  return Array.isArray(value)
    ? value.filter((item): item is number => typeof item === "number")
    : []
}

function numberValue(
  value: unknown,
  fallback: number
): number {
  return typeof value === "number" ? value : fallback
}

function pretty(value: string): string {
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (match) => match.toUpperCase())
}

function policyMatchSummary(item: AlertPolicy): string {
  const pieces: string[] = []
  const cameraIds = stringArray(item.match.camera_ids)
  const labels = stringArray(item.match.labels)
  const categories = stringArray(item.match.categories)
  const zones = stringArray(item.match.zones)
  if (cameraIds.length) pieces.push(`${cameraIds.length} camera(s)`)
  if (labels.length) pieces.push(labels.join(", "))
  else if (categories.length) pieces.push(categories.join(", "))
  if (zones.length) pieces.push(`zones: ${zones.join(", ")}`)
  return pieces.join(" · ") || "All matching events"
}

function policyActionSummary(item: AlertPolicy): string {
  const pieces: string[] = []
  const targets = stringArray(item.actions.notification_target_ids)
  if (targets.length) pieces.push(`${targets.length} notification target(s)`)
  if (item.actions.protect_recording === true) {
    pieces.push("protect recording")
  }
  return pieces.join(" · ") || "Create alert only"
}

async function refresh(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    ;[policies.value, cameras.value, targets.value] =
      await Promise.all([
        listAlertPolicies(),
        listCameras(),
        listNotificationTargets()
      ])
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    loading.value = false
  }
}

function resetForm(): void {
  editingId.value = null
  form.name = ""
  form.enabled = true
  form.severity = "warning"
  form.cameraIds = []
  form.categories = ""
  form.labels = ""
  form.zones = ""
  form.minConfidence = 0.6
  form.useMinConfidence = false
  form.minDuration = 0
  form.weekdays = [0, 1, 2, 3, 4, 5, 6]
  form.useTimeWindow = false
  form.timeStart = "00:00"
  form.timeEnd = "23:59"
  form.timezone = props.displayTimezone || "UTC"
  form.cooldownSeconds = 60
  form.notificationTargetIds = []
  form.protectRecording = false
  form.protectBefore = 10
  form.protectAfter = 20
  form.protectExpiresDays = 0
}

function openCreate(): void {
  resetForm()
  editorOpen.value = true
  notice.value = null
}

function openEdit(item: AlertPolicy): void {
  resetForm()
  editingId.value = item.id
  form.name = item.name
  form.enabled = item.enabled
  form.severity = item.severity
  form.cameraIds = stringArray(item.match.camera_ids)
  form.categories = stringArray(item.match.categories).join(", ")
  form.labels = stringArray(item.match.labels).join(", ")
  form.zones = stringArray(item.match.zones).join(", ")
  form.useMinConfidence =
    typeof item.match.min_confidence === "number"
  form.minConfidence = numberValue(
    item.match.min_confidence,
    0.6
  )
  form.minDuration = numberValue(
    item.match.min_duration_seconds,
    0
  )
  const weekdays = numberArray(item.match.weekdays)
  form.weekdays = weekdays.length
    ? weekdays
    : [0, 1, 2, 3, 4, 5, 6]
  form.useTimeWindow =
    typeof item.match.time_start === "string" &&
    typeof item.match.time_end === "string"
  form.timeStart =
    typeof item.match.time_start === "string"
      ? item.match.time_start
      : "00:00"
  form.timeEnd =
    typeof item.match.time_end === "string"
      ? item.match.time_end
      : "23:59"
  form.timezone =
    typeof item.match.timezone === "string"
      ? item.match.timezone
      : props.displayTimezone || "UTC"
  form.cooldownSeconds = item.cooldown_seconds
  form.notificationTargetIds = stringArray(
    item.actions.notification_target_ids
  )
  form.protectRecording =
    item.actions.protect_recording === true
  form.protectBefore = numberValue(
    item.actions.protect_before_seconds,
    10
  )
  form.protectAfter = numberValue(
    item.actions.protect_after_seconds,
    20
  )
  form.protectExpiresDays = numberValue(
    item.actions.protect_expires_days,
    0
  )
  editorOpen.value = true
}

function toggleWeekday(day: number): void {
  const index = form.weekdays.indexOf(day)
  if (index >= 0) {
    if (form.weekdays.length > 1) form.weekdays.splice(index, 1)
  } else {
    form.weekdays.push(day)
    form.weekdays.sort((a, b) => a - b)
  }
}

function buildMatch(): Record<string, unknown> {
  const match: Record<string, unknown> = {}
  if (form.cameraIds.length) {
    match.camera_ids = [...form.cameraIds]
  }
  const categories = csv(form.categories)
  const labels = csv(form.labels)
  const zones = csv(form.zones)
  if (categories.length) match.categories = categories
  if (labels.length) match.labels = labels
  if (zones.length) match.zones = zones
  if (form.useMinConfidence) {
    match.min_confidence = Number(form.minConfidence)
  }
  if (Number(form.minDuration) > 0) {
    match.min_duration_seconds = Number(form.minDuration)
  }
  if (form.useTimeWindow) {
    match.weekdays = [...form.weekdays]
    match.time_start = form.timeStart
    match.time_end = form.timeEnd
    match.timezone = form.timezone.trim()
  }
  return match
}

function buildActions(): Record<string, unknown> {
  const actions: Record<string, unknown> = {
    protect_recording: form.protectRecording
  }
  if (form.notificationTargetIds.length) {
    actions.notification_target_ids = [
      ...form.notificationTargetIds
    ]
  }
  if (form.protectRecording) {
    actions.protect_before_seconds = Number(form.protectBefore)
    actions.protect_after_seconds = Number(form.protectAfter)
    if (Number(form.protectExpiresDays) > 0) {
      actions.protect_expires_days = Number(form.protectExpiresDays)
    }
  }
  return actions
}

async function save(): Promise<void> {
  saving.value = true
  error.value = null
  notice.value = null
  const body = {
    name: form.name.trim(),
    enabled: form.enabled,
    severity: form.severity,
    match: buildMatch(),
    actions: buildActions(),
    cooldown_seconds: Number(form.cooldownSeconds)
  }

  try {
    if (editingId.value) {
      await updateAlertPolicy(editingId.value, body)
      notice.value = "Alert rule updated."
    } else {
      await createAlertPolicy(body)
      notice.value = "Alert rule created."
    }
    editorOpen.value = false
    await refresh()
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    saving.value = false
  }
}

async function toggle(item: AlertPolicy): Promise<void> {
  try {
    await updateAlertPolicy(item.id, {
      enabled: !item.enabled
    })
    await refresh()
  } catch (caught) {
    error.value = errorMessage(caught)
  }
}

async function remove(item: AlertPolicy): Promise<void> {
  if (!window.confirm(`Delete alert rule "${item.name}"?`)) return
  try {
    await deleteAlertPolicy(item.id)
    notice.value = "Alert rule deleted."
    await refresh()
  } catch (caught) {
    error.value = errorMessage(caught)
  }
}

onMounted(() => {
  resetForm()
  void refresh()
})
</script>

<template>
  <section class="alert-rules-panel">
    <header class="system-page-header">
      <div>
        <strong>Alert rules</strong>
        <span>
          Turn matching events into alerts, notifications and protected footage.
        </span>
      </div>
      <button
        class="button button--primary"
        type="button"
        @click="openCreate"
      >
        <UiIcon name="plus" :size="14" />
        Add rule
      </button>
    </header>

    <div class="alert-rule-summary">
      <span>
        <strong>{{ policies.length }}</strong>
        total rules
      </span>
      <span>
        <strong>{{ enabledCount }}</strong>
        enabled
      </span>
      <span>
        <strong>{{ targets.filter((item) => item.enabled).length }}</strong>
        active notification targets
      </span>
    </div>

    <div v-if="error" class="events-error">
      <UiIcon name="warning" :size="15" />
      <span>{{ error }}</span>
    </div>

    <div v-if="notice" class="storage-notice">
      <UiIcon name="check" :size="14" />
      <span>{{ notice }}</span>
    </div>

    <div v-if="!policies.length && !loading" class="storage-empty">
      <UiIcon name="bell" :size="26" />
      <strong>No alert rules</strong>
      <span>Create a rule to turn selected events into actionable alerts.</span>
    </div>

    <div v-else class="alert-rule-list">
      <article
        v-for="item in policies"
        :key="item.id"
        class="alert-rule-card"
      >
        <span
          class="alert-rule-card__severity"
          :class="`alert-rule-card__severity--${item.severity}`"
        />
        <div class="alert-rule-card__main">
          <div class="alert-rule-card__title">
            <strong>{{ item.name }}</strong>
            <span
              class="status-pill"
              :class="item.enabled ? 'status-pill--ok' : 'status-pill--muted'"
            >
              {{ item.enabled ? "Enabled" : "Disabled" }}
            </span>
            <span class="status-pill">
              {{ pretty(item.severity) }}
            </span>
          </div>
          <span>{{ policyMatchSummary(item) }}</span>
          <small>
            {{ policyActionSummary(item) }}
            · cooldown {{ item.cooldown_seconds }}s
          </small>
        </div>
        <div class="alert-rule-card__actions">
          <button
            class="button button--ghost button--compact"
            type="button"
            @click="openEdit(item)"
          >
            Edit
          </button>
          <button
            class="icon-button"
            type="button"
            :title="item.enabled ? 'Disable' : 'Enable'"
            @click="toggle(item)"
          >
            <UiIcon
              :name="item.enabled ? 'pause' : 'play'"
              :size="14"
            />
          </button>
          <button
            class="icon-button icon-button--danger"
            type="button"
            title="Delete rule"
            @click="remove(item)"
          >
            <UiIcon name="trash" :size="14" />
          </button>
        </div>
      </article>
    </div>

    <aside v-if="editorOpen" class="system-drawer alert-rule-editor">
      <header class="storage-editor__header">
        <div>
          <strong>{{ editingId ? "Edit alert rule" : "Add alert rule" }}</strong>
          <span>Event match + actions</span>
        </div>
        <button
          class="icon-button"
          type="button"
          @click="editorOpen = false"
        >
          <UiIcon name="close" :size="15" />
        </button>
      </header>

      <form class="alert-rule-form" @submit.prevent="save">
        <label>
          <span>Name</span>
          <input v-model="form.name" required maxlength="128" />
        </label>

        <div class="alert-rule-form__row">
          <label>
            <span>Alert severity</span>
            <select v-model="form.severity">
              <option value="info">Info</option>
              <option value="warning">Warning</option>
              <option value="critical">Critical</option>
            </select>
          </label>
          <label>
            <span>Cooldown seconds</span>
            <input
              v-model.number="form.cooldownSeconds"
              type="number"
              min="0"
              max="604800"
            />
          </label>
        </div>

        <fieldset>
          <legend>Match cameras</legend>
          <div class="alert-rule-check-grid">
            <label v-for="camera in cameras" :key="camera.id">
              <input
                v-model="form.cameraIds"
                type="checkbox"
                :value="camera.id"
              />
              <span>{{ camera.name }}</span>
            </label>
          </div>
          <small>No selection means all visible cameras.</small>
        </fieldset>

        <div class="alert-rule-form__row">
          <label>
            <span>Categories</span>
            <input
              v-model="form.categories"
              placeholder="object, motion"
            />
          </label>
          <label>
            <span>Labels</span>
            <input
              v-model="form.labels"
              placeholder="person, car"
            />
          </label>
        </div>

        <label>
          <span>Zones</span>
          <input
            v-model="form.zones"
            placeholder="driveway, front_yard"
          />
        </label>

        <div class="alert-rule-form__row">
          <label class="alert-rule-inline-check">
            <input
              v-model="form.useMinConfidence"
              type="checkbox"
            />
            <span>Minimum confidence</span>
          </label>
          <label v-if="form.useMinConfidence">
            <span>{{ Math.round(form.minConfidence * 100) }}%</span>
            <input
              v-model.number="form.minConfidence"
              type="range"
              min="0"
              max="1"
              step="0.05"
            />
          </label>
          <label>
            <span>Minimum duration seconds</span>
            <input
              v-model.number="form.minDuration"
              type="number"
              min="0"
              max="86400"
            />
          </label>
        </div>

        <fieldset>
          <legend>Time window</legend>
          <label class="alert-rule-inline-check">
            <input
              v-model="form.useTimeWindow"
              type="checkbox"
            />
            <span>Restrict by local weekday/time</span>
          </label>

          <template v-if="form.useTimeWindow">
            <div class="alert-rule-weekdays">
              <button
                v-for="(day, index) in ['Mon','Tue','Wed','Thu','Fri','Sat','Sun']"
                :key="day"
                type="button"
                :class="{ 'alert-rule-day--active': form.weekdays.includes(index) }"
                @click="toggleWeekday(index)"
              >
                {{ day }}
              </button>
            </div>
            <div class="alert-rule-form__row">
              <label>
                <span>From</span>
                <input v-model="form.timeStart" type="time" />
              </label>
              <label>
                <span>To</span>
                <input v-model="form.timeEnd" type="time" />
              </label>
            </div>
            <label>
              <span>Timezone</span>
              <input v-model="form.timezone" />
            </label>
          </template>
        </fieldset>

        <fieldset>
          <legend>Notifications</legend>
          <div class="alert-rule-check-grid">
            <label v-for="target in targets" :key="target.id">
              <input
                v-model="form.notificationTargetIds"
                type="checkbox"
                :value="target.id"
                :disabled="!target.enabled"
              />
              <span>
                {{ target.name }}
                <small v-if="!target.enabled">disabled</small>
              </span>
            </label>
          </div>
          <small>
            Leave empty to create an in-app alert without outbound delivery.
          </small>
        </fieldset>

        <fieldset>
          <legend>Recording protection</legend>
          <label class="alert-rule-inline-check">
            <input
              v-model="form.protectRecording"
              type="checkbox"
            />
            <span>Automatically protect matching event footage</span>
          </label>
          <div
            v-if="form.protectRecording"
            class="alert-rule-form__row alert-rule-form__row--three"
          >
            <label>
              <span>Before seconds</span>
              <input
                v-model.number="form.protectBefore"
                type="number"
                min="0"
                max="3600"
              />
            </label>
            <label>
              <span>After seconds</span>
              <input
                v-model.number="form.protectAfter"
                type="number"
                min="0"
                max="86400"
              />
            </label>
            <label>
              <span>Expire days</span>
              <input
                v-model.number="form.protectExpiresDays"
                type="number"
                min="0"
                max="36500"
              />
            </label>
          </div>
        </fieldset>

        <label class="storage-check">
          <input v-model="form.enabled" type="checkbox" />
          <span>Enable this alert rule</span>
        </label>

        <div class="alert-rule-form__actions">
          <button
            class="button button--ghost"
            type="button"
            @click="editorOpen = false"
          >
            Cancel
          </button>
          <button
            class="button button--primary"
            type="submit"
            :disabled="saving"
          >
            {{ saving ? "Saving…" : editingId ? "Save rule" : "Create rule" }}
          </button>
        </div>
      </form>
    </aside>
  </section>
</template>

<style scoped>
.alert-rules-panel {
  display: grid;
  gap: 10px;
}

.alert-rule-summary {
  display: flex;
  gap: 8px;
}

.alert-rule-summary > span {
  min-height: 42px;
  padding: 7px 10px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: var(--surface-raised);
  color: var(--text-muted);
  font-size: 8px;
}

.alert-rule-summary strong {
  display: block;
  margin-bottom: 1px;
  color: var(--text-primary);
  font-size: 12px;
}

.alert-rule-list {
  display: grid;
  gap: 7px;
}

.alert-rule-card {
  display: grid;
  min-height: 72px;
  grid-template-columns: 4px minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  overflow: hidden;
  padding: 0 9px 0 0;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--surface-raised);
}

.alert-rule-card__severity {
  align-self: stretch;
  background: var(--accent);
}

.alert-rule-card__severity--warning {
  background: #d49a45;
}

.alert-rule-card__severity--critical {
  background: var(--danger);
}

.alert-rule-card__main {
  min-width: 0;
}

.alert-rule-card__title {
  display: flex;
  align-items: center;
  gap: 6px;
}

.alert-rule-card__title strong {
  font-size: 10px;
}

.alert-rule-card__main > span,
.alert-rule-card__main > small {
  display: block;
  overflow: hidden;
  margin-top: 4px;
  color: var(--text-muted);
  font-size: 8px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.alert-rule-card__actions {
  display: flex;
  align-items: center;
  gap: 3px;
}

.alert-rule-form {
  display: grid;
  gap: 11px;
  padding: 12px;
}

.alert-rule-form > label,
.alert-rule-form__row > label {
  display: grid;
  gap: 5px;
}

.alert-rule-form label > span {
  color: var(--text-muted);
  font-size: 8px;
  font-weight: 650;
  text-transform: uppercase;
}

.alert-rule-form input:not([type="checkbox"]):not([type="range"]),
.alert-rule-form select {
  width: 100%;
  min-height: 33px;
  padding: 0 8px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  outline: 0;
  background: var(--surface-base);
  color: var(--text-primary);
  font: inherit;
  font-size: 9px;
}

.alert-rule-form input:focus,
.alert-rule-form select:focus {
  border-color: var(--accent);
}

.alert-rule-form fieldset {
  display: grid;
  gap: 7px;
  margin: 0;
  padding: 9px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
}

.alert-rule-form legend {
  padding: 0 5px;
  color: var(--text-muted);
  font-size: 8px;
  font-weight: 650;
  text-transform: uppercase;
}

.alert-rule-form fieldset > small {
  color: var(--text-muted);
  font-size: 7px;
}

.alert-rule-form__row {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 7px;
}

.alert-rule-form__row--three {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.alert-rule-check-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 4px;
}

.alert-rule-check-grid label,
.alert-rule-inline-check {
  display: flex !important;
  align-items: center;
  gap: 6px !important;
  min-height: 27px;
  padding: 3px 5px;
  border-radius: 4px;
  color: var(--text-secondary);
  font-size: 8px;
}

.alert-rule-check-grid label:hover {
  background: var(--surface-hover);
}

.alert-rule-check-grid input,
.alert-rule-inline-check input {
  width: 13px;
  height: 13px;
  accent-color: var(--accent);
}

.alert-rule-check-grid label > span {
  color: var(--text-secondary);
  font-size: 8px;
  font-weight: 500;
  text-transform: none;
}

.alert-rule-check-grid label small {
  color: var(--text-muted);
  font-size: 7px;
}

.alert-rule-weekdays {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 3px;
}

.alert-rule-weekdays button {
  min-height: 26px;
  padding: 0;
  border: 1px solid var(--border-subtle);
  border-radius: 4px;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 7px;
}

.alert-rule-weekdays .alert-rule-day--active {
  border-color: var(--accent);
  background: var(--accent-soft);
  color: var(--accent);
}

.alert-rule-form__actions {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
  padding-top: 3px;
}

@media (max-width: 560px) {
  .alert-rule-form__row,
  .alert-rule-form__row--three,
  .alert-rule-check-grid {
    grid-template-columns: 1fr;
  }
}
</style>
