<script setup lang="ts">
/**
 * General settings tab: the system display name plus the runtime tuning limits.
 *
 * Extracted from `SystemView` with its markup unchanged — every class here is
 * defined globally (`system-page-header`, `system-form-card`, `system-section`),
 * so nothing depended on the parent's scoped styles.
 *
 * The two form objects are owned by the view (it seeds them from the settings
 * response and reads them back when saving), so they are passed in and bound
 * with `v-model` against their properties. Mutating a prop's properties is
 * intentional here; the alternative would be copying state in both directions
 * for no benefit.
 */
import { useI18n } from "vue-i18n"

export interface GeneralForm {
  systemName: string
}

export interface RuntimeTuningForm {
  prebufferFragmentSeconds: number
  prebufferBufferSeconds: number
  turnCredentialTtlSeconds: number
  playbackCacheMiB: number
  playbackCacheTtlSeconds: number
  playbackRestoreLockTtlSeconds: number
  liveTranscodeMaxDerivatives: number
  liveTranscodeIdleTtlSeconds: number
  liveTranscodeLeaseTtlSeconds: number
  liveTranscodeStartupTimeoutSeconds: number
  liveTranscodeCpuThreads: number
  liveTranscodeVideoBitrateKbps: number
}

defineProps<{
  generalForm: GeneralForm
  runtimeForm: RuntimeTuningForm
  generalSaving: boolean
  runtimeSaving: boolean
  /** Whether the operator may change system settings at all. */
  canManage: boolean
}>()

const emit = defineEmits<{ saveGeneral: []; saveRuntime: [] }>()

const { t } = useI18n({ useScope: "global" })
</script>

<template>
  <header class="system-page-header">
    <div>
      <strong>{{ t("system.main.general") }}</strong>
      <span>{{ t("system.main.generalDesc") }}</span>
    </div>
  </header>

  <form
    class="system-form-card"
    @submit.prevent="emit('saveGeneral')"
  >
    <label>
      <span>{{ t("system.main.systemName") }}</span>
      <input
        v-model="generalForm.systemName"
        required
        maxlength="128"
      />
      <small>
        {{ t("system.main.systemNameHint") }}
      </small>
    </label>

    <div class="system-form-actions">
      <button
        class="button button--primary"
        type="submit"
        :disabled="generalSaving || !canManage"
      >
        {{ generalSaving ? t("system.main.saving") : t("system.main.saveGeneral") }}
      </button>
    </div>
  </form>

  <div class="system-section">
    <div class="system-section__heading">
      <strong>{{ t("system.main.runtimeTuning") }}</strong>
      <span>
        {{ t("system.main.runtimeHint") }}
      </span>
    </div>
    <form
      class="system-form-card system-form-card--wide"
      @submit.prevent="emit('saveRuntime')"
    >
      <div class="system-subsection">
        <div class="system-subsection__heading">
          <div>
            <strong>{{ t("system.main.eventPrebuffer") }}</strong>
            <span>
              {{ t("system.main.eventPrebufferHint") }}
            </span>
          </div>
        </div>
        <div class="system-form-row">
          <label>
            <span>{{ t("system.main.fragmentSeconds") }}</span>
            <input
              v-model.number="runtimeForm.prebufferFragmentSeconds"
              type="number"
              min="2"
              max="30"
              required
            />
          </label>
          <label>
            <span>{{ t("system.main.bufferSeconds") }}</span>
            <input
              v-model.number="runtimeForm.prebufferBufferSeconds"
              type="number"
              min="10"
              max="600"
              required
            />
          </label>
        </div>
        <small>
          {{ t("system.main.tmpfsHint") }}
        </small>
      </div>

      <div class="system-subsection">
        <div class="system-subsection__heading">
          <div>
            <strong>{{ t("system.main.turnCredentials") }}</strong>
            <span>
              {{ t("system.main.turnHint") }}
            </span>
          </div>
        </div>
        <div class="system-form-row">
          <label>
            <span>{{ t("system.main.credentialTtl") }}</span>
            <input
              v-model.number="runtimeForm.turnCredentialTtlSeconds"
              type="number"
              min="60"
              max="3600"
              required
            />
          </label>
        </div>
      </div>

      <div class="system-form-row">
        <label>
          <span>{{ t("system.main.playbackCacheLimit") }}</span>
          <input
            v-model.number="runtimeForm.playbackCacheMiB"
            type="number"
            min="64"
            max="1048576"
            step="64"
            required
          />
        </label>
        <label>
          <span>{{ t("system.main.playbackCacheTtl") }}</span>
          <input
            v-model.number="runtimeForm.playbackCacheTtlSeconds"
            type="number"
            min="60"
            max="604800"
            required
          />
        </label>
        <label>
          <span>{{ t("system.main.restoreLockTtl") }}</span>
          <input
            v-model.number="runtimeForm.playbackRestoreLockTtlSeconds"
            type="number"
            min="60"
            max="604800"
            required
          />
        </label>
      </div>

      <div class="system-subsection">
        <div class="system-subsection__heading">
          <div>
            <strong>{{ t("system.main.compatTranscode") }}</strong>
            <span>
              {{ t("system.main.compatTranscodeHint") }}
            </span>
          </div>
        </div>
        <div class="system-form-row">
          <label>
            <span>{{ t("system.main.maxDerivatives") }}</span>
            <input
              v-model.number="runtimeForm.liveTranscodeMaxDerivatives"
              type="number"
              min="1"
              max="8"
              required
            />
          </label>
          <label>
            <span>{{ t("system.main.cpuThreads") }}</span>
            <input
              v-model.number="runtimeForm.liveTranscodeCpuThreads"
              type="number"
              min="1"
              max="8"
              required
            />
          </label>
          <label>
            <span>{{ t("system.main.videoBitrate") }}</span>
            <input
              v-model.number="runtimeForm.liveTranscodeVideoBitrateKbps"
              type="number"
              min="512"
              max="20000"
              step="128"
              required
            />
          </label>
        </div>
        <div class="system-form-row">
          <label>
            <span>{{ t("system.main.idleTtl") }}</span>
            <input
              v-model.number="runtimeForm.liveTranscodeIdleTtlSeconds"
              type="number"
              min="5"
              max="300"
              required
            />
          </label>
          <label>
            <span>{{ t("system.main.leaseTtl") }}</span>
            <input
              v-model.number="runtimeForm.liveTranscodeLeaseTtlSeconds"
              type="number"
              min="15"
              max="300"
              required
            />
          </label>
          <label>
            <span>{{ t("system.main.startupTimeout") }}</span>
            <input
              v-model.number="runtimeForm.liveTranscodeStartupTimeoutSeconds"
              type="number"
              min="1"
              max="30"
              step="0.5"
              required
            />
          </label>
        </div>
      </div>

      <div class="system-form-actions">
        <button
          class="button button--primary"
          type="submit"
          :disabled="runtimeSaving || !canManage"
        >
          {{ runtimeSaving ? t("system.main.saving") : t("system.main.saveRuntime") }}
        </button>
      </div>
    </form>
  </div>
</template>
