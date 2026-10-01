<script setup lang="ts">
/**
 * ONVIF connection details: host, port and credentials, plus the probe trigger.
 *
 * Extracted from `CameraOnboardingPanel`. The four fields are `defineModel`s, so
 * the panel keeps its existing refs — its `inspectDevice` and `useCandidate`
 * functions read those refs directly and are unaffected.
 */
import { useI18n } from "vue-i18n"

import { type OnboardingWorkingAction } from "./onboarding"

const onvifHost = defineModel<string>("onvifHost", { required: true })
const onvifPort = defineModel<number>("onvifPort", { required: true })
const onvifUsername = defineModel<string>("onvifUsername", { required: true })
const onvifPassword = defineModel<string>("onvifPassword", { required: true })

defineProps<{ working: OnboardingWorkingAction }>()

const emit = defineEmits<{ inspect: [] }>()

const { t } = useI18n({ useScope: "global" })
</script>

<template>
  <div class="form-grid form-grid--three">
    <label class="field field--grow">
      <span>{{ t("cameras.onboarding.hostOrIp") }}</span>
      <input
        v-model="onvifHost"
        placeholder="192.168.1.50"
        autocomplete="off"
        required
      />
    </label>
    <label class="field">
      <span>{{ t("cameras.onboarding.port") }}</span>
      <input
        v-model.number="onvifPort"
        type="number"
        min="1"
        max="65535"
        inputmode="numeric"
      />
    </label>
    <label class="field">
      <span>{{ t("cameras.onboarding.username") }}</span>
      <input v-model="onvifUsername" autocomplete="username" />
    </label>
  </div>

  <label class="field">
    <span>{{ t("cameras.onboarding.password") }}</span>
    <input
      v-model="onvifPassword"
      type="password"
      autocomplete="current-password"
    />
  </label>

  <button
    class="button button--primary"
    type="button"
    :disabled="working !== null || !onvifHost.trim()"
    @click="emit('inspect')"
  >
    {{ working === "inspect" ? t("cameras.onboarding.inspecting") : t("cameras.onboarding.testInspect") }}
  </button>
</template>
