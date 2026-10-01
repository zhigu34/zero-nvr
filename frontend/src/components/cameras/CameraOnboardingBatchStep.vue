<script setup lang="ts">
/**
 * Batch onboarding step: pick discovered devices, apply a shared template, add
 * per-device credential overrides and import them in one go.
 *
 * Extracted from `CameraOnboardingPanel`. Three helpers stay with the parent and
 * arrive as callback props, because the panel's own script still uses them for
 * the import payload (`batchCredential`) and for the discovery and file-import
 * sections (`candidateName`, `batchStateLabel`). Everything derived purely from
 * this step's own inputs — `batchCandidates`, `canBatchImport`, `batchResultMap`
 * — moved in.
 */
import { computed } from "vue"
import { useI18n } from "vue-i18n"

import {
  type CameraGroup,
  type DiscoveryCandidate,
  type DiscoverySession
} from "../../api/cameras"
import { type StorageTarget } from "../../api/storage"
import {
  type BatchCredentialOverride,
  type BatchResult,
  type BatchResultState,
  type BatchTimeSyncMode,
  type OnboardingWorkingAction
} from "./onboarding"

const props = defineProps<{
  discovery: DiscoverySession
  batchGroups: CameraGroup[]
  batchStorageTargets: StorageTarget[]
  batchResults: BatchResult[]
  /** Whether the operator may choose a storage target. */
  canManageStorage: boolean
  working: OnboardingWorkingAction
  /** Lazily creates and returns the credential override for a device. */
  batchCredential: (candidateId: string) => BatchCredentialOverride
  candidateName: (candidate: DiscoveryCandidate) => string
  batchStateLabel: (value: BatchResultState) => string
}>()

const emit = defineEmits<{ run: [] }>()

const { t } = useI18n({ useScope: "global" })

const batchSelectedIds = defineModel<string[]>("batchSelectedIds", {
  required: true
})
const batchNameTemplate = defineModel<string>("batchNameTemplate", {
  required: true
})
const batchUsername = defineModel<string>("batchUsername", { required: true })
const batchPassword = defineModel<string>("batchPassword", { required: true })
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

const batchCandidates = computed(() => {
  const selected = new Set(batchSelectedIds.value)
  return props.discovery.candidates.filter((candidate: DiscoveryCandidate) =>
    selected.has(candidate.id)
  )
})

const canBatchImport = computed(
  () =>
    batchCandidates.value.length > 0 &&
    batchCandidates.value.every((candidate) => Boolean(candidate.host)) &&
    props.working === null
)

const batchResultMap = computed(
  () =>
    new Map(
      props.batchResults.map((result) => [result.candidate_id, result])
    )
)
</script>

<template>
  <div class="onboarding-step">
          <div class="step-heading">
            <span>B</span>
            <div>
              <strong>{{ t("cameras.onboarding.batchOnboarding") }}</strong>
              <p>
                {{ t("cameras.onboarding.batchHint") }}
              </p>
            </div>
          </div>

          <div class="profile-list">
            <div
              v-for="candidate in discovery.candidates"
              :key="`batch-${candidate.id}`"
              class="probe-card"
            >
              <label class="check-row">
                <input
                  v-model="batchSelectedIds"
                  type="checkbox"
                  :value="candidate.id"
                  :disabled="!candidate.host || working !== null"
                />
                <span>
                  <strong>{{ candidateName(candidate) }}</strong>
                  · {{ candidate.host || t("cameras.onboarding.addressUnavailable") }}
                </span>
              </label>

              <div
                v-if="batchSelectedIds.includes(candidate.id)"
                class="form-grid"
              >
                <label class="field">
                  <span>{{ t("cameras.onboarding.usernameOverride") }} <small>{{ t("cameras.onboarding.optional") }}</small></span>
                  <input
                    v-model="batchCredential(candidate.id).username"
                    autocomplete="off"
                    :placeholder="t('cameras.onboarding.useSharedUsername')"
                  />
                </label>
                <label class="field">
                  <span>{{ t("cameras.onboarding.passwordOverride") }} <small>{{ t("cameras.onboarding.optional") }}</small></span>
                  <input
                    v-model="batchCredential(candidate.id).password"
                    type="password"
                    autocomplete="new-password"
                    :placeholder="t('cameras.onboarding.useSharedPassword')"
                  />
                </label>
              </div>

              <p
                v-if="batchResultMap.get(candidate.id)"
                class="field-hint"
              >
                <strong>
                  {{ batchStateLabel(batchResultMap.get(candidate.id)?.state || "pending") }}
                </strong>
                · {{ batchResultMap.get(candidate.id)?.message }}
              </p>
            </div>
          </div>

          <div class="form-grid form-grid--three">
            <label class="field">
              <span>{{ t("cameras.onboarding.sharedUsername") }}</span>
              <input
                v-model="batchUsername"
                autocomplete="username"
              />
            </label>
            <label class="field">
              <span>{{ t("cameras.onboarding.sharedPassword") }}</span>
              <input
                v-model="batchPassword"
                type="password"
                autocomplete="new-password"
              />
            </label>
            <label class="field">
              <span>{{ t("cameras.onboarding.nameTemplate") }}</span>
              <input
                v-model="batchNameTemplate"
                placeholder="{name}"
              />
              <small>{{ t("cameras.onboarding.nameTemplateHint", { name: "{name}", host: "{host}" }) }}</small>
            </label>
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

          <div class="onboarding-actions">
            <span class="field-hint">
              {{ t("cameras.onboarding.devicesSelected", { count: batchSelectedIds.length }) }}
            </span>
            <button
              class="button button--primary"
              type="button"
              :disabled="!canBatchImport"
              @click="emit('run')"
            >
              {{ working === "batch" ? t("cameras.onboarding.batchImporting") : t("cameras.onboarding.importSelectedDevices") }}
            </button>
          </div>
  </div>
</template>
