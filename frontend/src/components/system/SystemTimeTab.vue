<script setup lang="ts">
/**
 * Time and NTP tab: the recording timezone, host NTP configuration and the
 * per-camera clock drift report.
 *
 * Extracted from `SystemView`. Every class it uses is defined globally, so no
 * stylesheet change was needed.
 *
 * `healthDetail` and the NTP server list helpers moved here: the view no longer
 * references them now that this markup has left. `timeForm` stays owned by the
 * view (it seeds it from the settings response and sends it when saving), so it
 * is passed in and bound directly.
 */
import { useI18n } from "vue-i18n"

import {
  type CameraClockHealth,
  type CameraNtpApplyResult,
  type HealthComponent
} from "../../api/system"
import { useSystemFormatters } from "../../composables/useSystemFormatters"
import UiIcon from "../ui/UiIcon.vue"
import StatusPill from "../ui/StatusPill.vue"

export interface TimeForm {
  recordingTimezone: string
  ntpMode: "manual" | "dhcp"
  ntpServers: string[]
}

const props = defineProps<{
  timeForm: TimeForm
  timeSaving: boolean
  ntpApplying: boolean
  ntpApplyResult: CameraNtpApplyResult | null
  hostClockHealth: HealthComponent | null
  cameraClockHealth: CameraClockHealth | null
  cameraClockLoading: boolean
  /** Whether the operator may change system settings at all. */
  canManage: boolean
}>()

const emit = defineEmits<{
  save: [applyToCameras: boolean]
  checkClocks: []
}>()

const { t } = useI18n({ useScope: "global" })
const { formatTime, pretty, stateLabel, statusVariant } = useSystemFormatters()

/** NTP accepts at most four servers, mirroring the backend's validation. */
function addNtpServer(): void {
  if (props.timeForm.ntpServers.length >= 4) return
  props.timeForm.ntpServers.push("")
}

function removeNtpServer(index: number): void {
  props.timeForm.ntpServers.splice(index, 1)
  // Never leave the list empty: the form always shows at least one row.
  if (!props.timeForm.ntpServers.length) {
    props.timeForm.ntpServers.push("")
  }
}

function moveNtpServer(index: number, direction: -1 | 1): void {
  const target = index + direction
  if (target < 0 || target >= props.timeForm.ntpServers.length) {
    return
  }
  const [item] = props.timeForm.ntpServers.splice(index, 1)
  props.timeForm.ntpServers.splice(target, 0, item)
}

/** Read one health detail as display text, tolerating a missing payload. */
function healthDetail(item: HealthComponent | null, key: string): string {
  const value = item?.details[key]
  if (typeof value === "string" || typeof value === "number") {
    return String(value)
  }
  return "—"
}
</script>

<template>
  <header class="system-page-header">
    <div>
      <strong>{{ t("system.main.time") }}</strong>
      <span>
        {{ t("system.main.timeDesc") }}
      </span>
    </div>
    <button
      class="button button--ghost"
      type="button"
      :disabled="cameraClockLoading"
      @click="emit('checkClocks')"
    >
      <UiIcon name="refresh" :size="14" />
      {{
        cameraClockLoading
          ? t("system.main.checkingClocks")
          : t("system.main.checkClocks")
      }}
    </button>
  </header>

  <form
    class="system-form-card system-form-card--time"
    @submit.prevent="emit('save', false)"
  >
    <label>
      <span>{{ t("system.main.recordingTimezone") }}</span>
      <input
        v-model="timeForm.recordingTimezone"
        required
        placeholder="America/Los_Angeles"
        autocomplete="off"
      />
      <small>
        {{ t("system.main.recordingTimezoneHint") }}
      </small>
    </label>

    <label>
      <span>{{ t("system.main.managedNtp") }}</span>
      <select v-model="timeForm.ntpMode">
        <option value="dhcp">
          {{ t("system.main.dhcpNtp") }}
        </option>
        <option value="manual">
          {{ t("system.main.manualNtp") }}
        </option>
      </select>
      <small v-if="timeForm.ntpMode === 'dhcp'">
        {{ t("system.main.dhcpNtpHint") }}
      </small>
      <small v-else>
        {{ t("system.main.manualNtpHint") }}
      </small>
    </label>

    <div
      v-if="timeForm.ntpMode === 'manual'"
      class="time-ntp-list"
    >
      <div class="time-ntp-list__heading">
        <div>
          <strong>{{ t("system.main.manualNtp") }}</strong>
          <span>
            {{ t("system.main.ntpPriorityHint") }}
          </span>
        </div>
        <button
          class="button button--ghost button--compact"
          type="button"
          :disabled="timeForm.ntpServers.length >= 4"
          @click="addNtpServer"
        >
          <UiIcon name="plus" :size="13" />
          {{ t("system.main.addServer") }}
        </button>
      </div>

      <div class="time-ntp-list__rows">
        <div
          v-for="(server, index) in timeForm.ntpServers"
          :key="index"
          class="time-ntp-row"
        >
          <span class="time-ntp-row__priority">
            {{ index + 1 }}
          </span>
          <input
            v-model="timeForm.ntpServers[index]"
            :aria-label="t('system.main.ntpServerPriority', { priority: index + 1 })"
            placeholder="pool.ntp.org"
            maxlength="253"
            autocomplete="off"
          />
          <button
            class="icon-button"
            type="button"
            :title="t('system.main.moveUp')"
            :disabled="index === 0"
            @click="moveNtpServer(index, -1)"
          >
            <UiIcon name="chevron-up" :size="13" />
          </button>
          <button
            class="icon-button"
            type="button"
            :title="t('system.main.moveDown')"
            :disabled="index === timeForm.ntpServers.length - 1"
            @click="moveNtpServer(index, 1)"
          >
            <UiIcon name="chevron-down" :size="13" />
          </button>
          <button
            class="icon-button icon-button--danger"
            type="button"
            :title="t('system.main.removeServer')"
            @click="removeNtpServer(index)"
          >
            <UiIcon name="trash" :size="13" />
          </button>
        </div>
      </div>
    </div>

    <div class="time-policy-note">
      <UiIcon name="activity" :size="15" />
      <span>
        {{ t("system.main.timePolicyPrefix") }}
        <strong>{{ t("system.main.saveApply") }}</strong>
        {{ t("system.main.timePolicySuffix") }}
      </span>
    </div>

    <div class="system-form-actions">
      <button
        class="button button--ghost"
        type="submit"
        :disabled="timeSaving || !canManage"
      >
        {{ timeSaving && !ntpApplying ? t("system.main.saving") : t("system.main.savePolicy") }}
      </button>
      <button
        class="button button--primary"
        type="button"
        :disabled="timeSaving || !canManage"
        @click="emit('save', true)"
      >
        {{
          ntpApplying
            ? t("system.main.savingApplying")
            : t("system.main.saveApply")
        }}
      </button>
    </div>
  </form>

  <div
    v-if="hostClockHealth"
    class="host-clock-health"
  >
    <div class="host-clock-health__main">
      <div>
        <strong>{{ t("system.main.hostClock") }}</strong>
        <span>
          {{ t("system.main.canonicalTimeSource") }}
          {{ healthDetail(hostClockHealth, "canonical_timezone") }}
        </span>
      </div>
      <StatusPill :variant="statusVariant(hostClockHealth.status)">
        {{ stateLabel(hostClockHealth.status) }}
      </StatusPill>
    </div>
    <dl>
      <div>
        <dt>{{ t("system.main.syncState") }}</dt>
        <dd>
          {{
            healthDetail(
              hostClockHealth,
              "sync_state"
            )
          }}
        </dd>
      </div>
      <div>
        <dt>{{ t("system.main.estimatedOffset") }}</dt>
        <dd>
          {{
            healthDetail(
              hostClockHealth,
              "estimated_offset_ms"
            )
          }} ms
        </dd>
      </div>
      <div>
        <dt>{{ t("system.main.estimatedError") }}</dt>
        <dd>
          {{
            healthDetail(
              hostClockHealth,
              "estimated_error_ms"
            )
          }} ms
        </dd>
      </div>
      <div>
        <dt>{{ t("system.main.probe") }}</dt>
        <dd>
          {{
            healthDetail(
              hostClockHealth,
              "source"
            )
          }}
        </dd>
      </div>
    </dl>
    <p v-if="hostClockHealth.status === 'DISABLED'">
      {{ t("system.main.hostClockUnobservable") }}
    </p>
    <p v-else-if="hostClockHealth.status !== 'OK'">
      {{ t("system.main.hostClockUnsynced") }}
    </p>
  </div>

  <div
    v-if="ntpApplyResult"
    class="system-ntp-result"
  >
    <div>
      <strong>
        {{ t("system.main.cameraNtpApplied", { updated: ntpApplyResult.updated, total: ntpApplyResult.total_devices }) }}
      </strong>
      <span>
        {{
          ntpApplyResult.mode === "manual"
            ? t("system.main.manualNtp")
            : t("system.main.dhcpNtp")
        }}
      </span>
    </div>
    <span
      class="status-pill"
      :class="ntpApplyResult.failed ? 'status-pill--error' : 'status-pill--ok'"
    >
      {{ ntpApplyResult.failed ? t("system.main.partial") : t("system.main.appliedState") }}
    </span>
    <ul v-if="ntpApplyResult.failed">
      <li
        v-for="item in ntpApplyResult.results.filter(
          (entry) => entry.status === 'FAILED'
        )"
        :key="item.device_id"
      >
        {{ item.name }} · {{ item.error_code || "apply_failed" }}
      </li>
    </ul>
  </div>

  <div
    v-if="cameraClockHealth"
    class="camera-clock-health"
  >
    <header>
      <div>
        <strong>{{ t("system.main.cameraClockHealth") }}</strong>
        <span>
          {{ t("system.main.clockChecked", { count: cameraClockHealth.total_devices, time: formatTime(cameraClockHealth.checked_at) }) }}
        </span>
      </div>
      <StatusPill :variant="statusVariant(cameraClockHealth.status)">
        {{ cameraClockHealth.status }}
      </StatusPill>
    </header>

    <div
      v-if="!cameraClockHealth.results.length"
      class="camera-clock-health__empty"
    >
      {{ t("system.main.noOnvifClocks") }}
    </div>
    <div v-else class="camera-clock-health__rows">
      <article
        v-for="item in cameraClockHealth.results"
        :key="item.device_id"
      >
        <div>
          <strong>{{ item.name }}</strong>
          <span>
            {{
              item.error_code
                ? pretty(item.error_code)
                : `${item.date_time_type || t("system.main.unknownMode")} · ${item.timezone || t("system.main.timezoneUnknown")}`
            }}
          </span>
        </div>
        <div class="camera-clock-health__metrics">
          <span>
            {{ t("system.main.offset") }}
            <strong>
              {{
                item.offset_ms === null
                  ? "—"
                  : `${item.offset_ms > 0 ? "+" : ""}${item.offset_ms} ms`
              }}
            </strong>
          </span>
          <span>
            {{ t("system.main.rtt") }}
            <strong>
              {{
                item.rtt_ms === null
                  ? "—"
                  : `${item.rtt_ms} ms`
              }}
            </strong>
          </span>
          <span>
            {{ t("system.main.quality") }}
            <strong>
              {{ stateLabel(item.quality) }}
            </strong>
          </span>
        </div>
        <StatusPill :variant="statusVariant(item.status)">
          {{ stateLabel(item.status) }}
        </StatusPill>
      </article>
    </div>
  </div>
</template>
