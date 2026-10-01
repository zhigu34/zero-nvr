<script setup lang="ts">
/**
 * CSV batch import: download the template, pick a file, review the parsed rows
 * and import them.
 *
 * Extracted from `CameraOnboardingPanel` — the last inline branch of that view.
 * The four shared batch settings use `defineModel`, so they stay the panel's
 * refs and are shared with the ONVIF batch step. `fileBatchReadyCount` and
 * `fileBatchInvalidCount` moved in, because both derive purely from
 * `fileBatchRows`; `canFileBatchImport` stayed behind, as the panel's own
 * payload guard reads it.
 *
 * The file input lives here so the panel never has to reach across components
 * for it; the panel receives the chosen `File`.
 */
import { computed } from "vue"
import { useI18n } from "vue-i18n"

import { type CameraGroup } from "../../api/cameras"
import { type StorageTarget } from "../../api/storage"
import {
  type BatchResultState,
  type BatchTimeSyncMode,
  type FileBatchResult,
  type FileImportRow,
  type OnboardingWorkingAction
} from "./onboarding"

const props = defineProps<{
  batchGroups: CameraGroup[]
  batchStorageTargets: StorageTarget[]
  fileBatchName: string
  fileBatchRows: FileImportRow[]
  fileBatchResults: FileBatchResult[]
  canFileBatchImport: boolean
  /** Whether the operator may choose a storage target. */
  canManageStorage: boolean
  working: OnboardingWorkingAction
  batchStateLabel: (value: BatchResultState) => string
}>()

const emit = defineEmits<{
  downloadTemplate: []
  fileSelected: [file: File]
  run: []
}>()

const { t } = useI18n({ useScope: "global" })

const batchGroupId = defineModel<string>("batchGroupId", { required: true })
const batchRecordingMode = defineModel<"continuous" | "events" | "off">(
  "batchRecordingMode",
  { required: true }
)
const batchStorageTargetId = defineModel<string>("batchStorageTargetId", {
  required: true
})
const batchTimeSyncMode = defineModel<BatchTimeSyncMode>("batchTimeSyncMode", {
  required: true
})

const fileBatchReadyCount = computed(
  () => props.fileBatchRows.filter((row) => !row.errors.length).length
)
const fileBatchInvalidCount = computed(
  () => props.fileBatchRows.length - fileBatchReadyCount.value
)

function onBatchFile(event: Event): void {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) {
    emit("fileSelected", file)
  }
  // Allow re-selecting the same file after a failed parse.
  input.value = ""
}
</script>

<template>
  <div class="onboarding-step onboarding-step--full">
    <div class="step-heading">
      <span>1</span>
      <div>
        <strong>{{ t("cameras.onboarding.batchFileTitle") }}</strong>
        <p>{{ t("cameras.onboarding.batchFileHint") }}</p>
      </div>
    </div>

    <div class="onboarding-actions">
      <button
        class="button button--secondary"
        type="button"
        :disabled="working !== null"
        @click="emit('downloadTemplate')"
      >
        {{ t("cameras.onboarding.downloadCsvTemplate") }}
      </button>
      <label class="field field--grow">
        <span>{{ t("cameras.onboarding.chooseCsvFile") }}</span>
        <input
          type="file"
          accept=".csv,text/csv"
          :disabled="working !== null"
          @change="onBatchFile"
        />
      </label>
    </div>

    <p class="field-hint">
      {{ t("cameras.onboarding.csvColumns") }}
    </p>
    <p v-if="fileBatchName" class="field-hint">
      {{
        t("cameras.onboarding.csvLoaded", {
          file: fileBatchName,
          total: fileBatchRows.length,
          valid: fileBatchReadyCount,
          invalid: fileBatchInvalidCount
        })
      }}
    </p>

    <div v-if="fileBatchRows.length" class="profile-list">
      <article
        v-for="row in fileBatchRows"
        :key="row.line"
        class="probe-card"
      >
        <div class="device-summary">
          <strong>
            {{ t("cameras.onboarding.csvLine", { line: row.line }) }}
            · {{ row.kind?.toUpperCase() || "?" }}
          </strong>
          <span>{{ row.name || row.host || "—" }}</span>
        </div>
        <p
          v-if="row.errors.length"
          class="notice notice--error"
        >
          {{ row.errors.join(" · ") }}
        </p>
        <p v-else class="field-hint">
          {{ t("cameras.onboarding.csvReady") }}
        </p>
      </article>
    </div>
  </div>

  <div class="onboarding-step onboarding-step--full">
    <div class="step-heading">
      <span>2</span>
      <div>
        <strong>{{ t("cameras.onboarding.batchDefaults") }}</strong>
        <p>{{ t("cameras.onboarding.batchDefaultsHint") }}</p>
      </div>
    </div>

    <div class="form-grid form-grid--three">
      <label class="field">
        <span>{{ t("cameras.onboarding.cameraGroup") }} <small>{{ t("cameras.onboarding.optional") }}</small></span>
        <select v-model="batchGroupId">
          <option value="">{{ t("cameras.onboarding.noGroup") }}</option>
          <option
            v-for="group in batchGroups"
            :key="group.id"
            :value="group.id"
          >
            {{ group.name }}
          </option>
        </select>
      </label>
      <label class="field">
        <span>{{ t("cameras.onboarding.recordingDefault") }}</span>
        <select v-model="batchRecordingMode">
          <option value="continuous">{{ t("cameras.onboarding.continuous") }}</option>
          <option value="events">{{ t("cameras.onboarding.eventsOnly") }}</option>
          <option value="off">{{ t("cameras.onboarding.off") }}</option>
        </select>
      </label>
      <label class="field">
        <span>{{ t("cameras.onboarding.storageTarget") }}</span>
        <select
          v-model="batchStorageTargetId"
          :disabled="!canManageStorage"
        >
          <option value="">{{ t("cameras.onboarding.systemDefault") }}</option>
          <option
            v-for="target in batchStorageTargets"
            :key="target.id"
            :value="target.id"
          >
            {{ target.name }}
          </option>
        </select>
      </label>
    </div>

    <div class="form-grid form-grid--three">
      <label class="field">
        <span>{{ t("cameras.onboarding.timeSyncDefault") }}</span>
        <select v-model="batchTimeSyncMode">
          <option value="monitor">{{ t("cameras.onboarding.monitorOnly") }}</option>
          <option value="manage_ntp">{{ t("cameras.onboarding.manageNtp") }}</option>
          <option value="ignore">{{ t("cameras.onboarding.ignore") }}</option>
        </select>
      </label>
    </div>
  </div>

  <div class="onboarding-step onboarding-step--full">
    <div class="step-heading">
      <span>3</span>
      <div>
        <strong>{{ t("cameras.onboarding.batchFileImport") }}</strong>
        <p>{{ t("cameras.onboarding.batchFileImportHint") }}</p>
      </div>
    </div>

    <div class="onboarding-actions">
      <span class="field-hint">
        {{ t("cameras.onboarding.csvReadyCount", { count: fileBatchReadyCount }) }}
      </span>
      <button
        class="button button--primary"
        type="button"
        :disabled="!canFileBatchImport"
        @click="emit('run')"
      >
        {{
          working === "file-batch"
            ? t("cameras.onboarding.fileBatchImporting")
            : t("cameras.onboarding.importCsvRows", {
                count: fileBatchReadyCount
              })
        }}
      </button>
    </div>

    <div v-if="fileBatchResults.length" class="profile-list">
      <article
        v-for="result in fileBatchResults"
        :key="result.line"
        class="probe-card"
      >
        <div class="device-summary">
          <strong>
            {{ t("cameras.onboarding.csvLine", { line: result.line }) }}
            · {{ result.label }}
          </strong>
          <span>{{ batchStateLabel(result.state) }}</span>
        </div>
        <p>{{ result.message }}</p>
      </article>
    </div>
  </div>

</template>
