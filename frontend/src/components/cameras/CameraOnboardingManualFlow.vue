<script setup lang="ts">
/**
 * Manual (RTSP) camera onboarding: describe the camera, name its streams and
 * probe them before creating it.
 *
 * Extracted from `CameraOnboardingPanel`, whose own state stays in the parent.
 * The text and checkbox fields use `defineModel`, so the parent keeps its
 * existing refs and there is no copy of the form state to keep in sync. (The
 * rest of the app passes a reactive form object down instead; that would have
 * meant reshaping this component's eight separate refs, which is a larger change
 * than this extraction needs.)
 *
 * `manualProbe`, `working` and `canCreateManual` are read-only here — the parent
 * owns the probe lifecycle and the busy flag.
 */
import { useI18n } from "vue-i18n"

import { type CameraProbeResult } from "../../api/cameras"
import { type OnboardingWorkingAction } from "./onboarding"

const manualName = defineModel<string>("manualName", { required: true })
const manualLocation = defineModel<string>("manualLocation", { required: true })
const manualStorageLabel = defineModel<string>("manualStorageLabel", {
  required: true
})
const primaryName = defineModel<string>("primaryName", { required: true })
const primaryUrl = defineModel<string>("primaryUrl", { required: true })
const secondaryEnabled = defineModel<boolean>("secondaryEnabled", {
  required: true
})
const secondaryName = defineModel<string>("secondaryName", { required: true })
const secondaryUrl = defineModel<string>("secondaryUrl", { required: true })

defineProps<{
  manualProbe: CameraProbeResult | null
  working: OnboardingWorkingAction
  canCreateManual: boolean
}>()

const emit = defineEmits<{ test: []; create: [] }>()

const { t } = useI18n({ useScope: "global" })
</script>

<template>
  <div class="onboarding-grid">
    <div class="onboarding-step">
      <div class="step-heading">
        <span>1</span>
        <div>
          <strong>{{ t("cameras.onboarding.describeCamera") }}</strong>
          <p>{{ t("cameras.onboarding.manualHint") }}</p>
        </div>
      </div>

      <label class="field">
        <span>{{ t("cameras.onboarding.cameraName") }}</span>
        <input v-model="manualName" :placeholder="t('cameras.onboarding.garage')" required />
      </label>

      <div class="form-grid">
        <label class="field">
          <span>{{ t("cameras.location") }} <small>{{ t("cameras.onboarding.optional") }}</small></span>
          <input v-model="manualLocation" />
        </label>
        <label class="field">
          <span>{{ t("cameras.storageLabel") }} <small>{{ t("cameras.onboarding.optional") }}</small></span>
          <input v-model="manualStorageLabel" />
        </label>
      </div>
    </div>

    <div class="onboarding-step">
      <div class="step-heading">
        <span>2</span>
        <div>
          <strong>{{ t("cameras.onboarding.configureStreams") }}</strong>
          <p>{{ t("cameras.onboarding.zlmHint") }}</p>
        </div>
      </div>

      <label class="field">
        <span>{{ t("cameras.onboarding.primaryStreamName") }}</span>
        <input v-model="primaryName" required />
      </label>
      <label class="field">
        <span>{{ t("cameras.onboarding.primaryRtspUrl") }}</span>
        <input
          v-model="primaryUrl"
          type="password"
          autocomplete="off"
          placeholder="rtsp://user:password@camera/stream"
          required
        />
      </label>

      <label class="check-row">
        <input v-model="secondaryEnabled" type="checkbox" />
        <span>{{ t("cameras.onboarding.addSecondary") }}</span>
      </label>

      <template v-if="secondaryEnabled">
        <label class="field">
          <span>{{ t("cameras.onboarding.secondaryStreamName") }}</span>
          <input v-model="secondaryName" required />
        </label>
        <label class="field">
          <span>{{ t("cameras.onboarding.secondaryRtspUrl") }}</span>
          <input
            v-model="secondaryUrl"
            type="password"
            autocomplete="off"
            required
          />
        </label>
      </template>
    </div>

    <div class="onboarding-step onboarding-step--full">
      <div class="step-heading">
        <span>3</span>
        <div>
          <strong>{{ t("cameras.onboarding.verifyBeforeCreating") }}</strong>
          <p>
            {{ t("cameras.onboarding.verifyHint") }}
          </p>
        </div>
      </div>

      <div v-if="manualProbe" class="probe-results">
        <article
          v-for="stream in manualProbe.streams"
          :key="stream.role"
          class="probe-card"
        >
          <div>
            <strong>{{ stream.name }}</strong>
            <span>{{ stream.role }}</span>
          </div>
          <p>
            {{ t("cameras.onboarding.video") }}
            <strong>{{ stream.video?.codec || t("cameras.onboarding.notDetected") }}</strong>
            <template v-if="stream.video?.width && stream.video?.height">
              · {{ stream.video.width }}×{{ stream.video.height }}
            </template>
          </p>
          <p>
            {{ t("cameras.onboarding.audio") }}
            <strong>{{ stream.audio?.codec || t("cameras.onboarding.none") }}</strong>
          </p>
        </article>
      </div>

      <div class="onboarding-actions">
        <button
          class="button button--secondary"
          type="button"
          :disabled="
            working !== null ||
            !manualName.trim() ||
            !primaryUrl.trim()
          "
          @click="emit('test')"
        >
          {{ working === "test" ? t("cameras.onboarding.testing") : t("cameras.onboarding.testStreams") }}
        </button>
        <button
          class="button button--primary"
          type="button"
          :disabled="!canCreateManual"
          @click="emit('create')"
        >
          {{ working === "create" ? t("cameras.onboarding.creating") : t("cameras.onboarding.createCamera") }}
        </button>
      </div>
    </div>
  </div>
</template>
