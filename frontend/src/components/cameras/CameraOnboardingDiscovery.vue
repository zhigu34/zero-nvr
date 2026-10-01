<script setup lang="ts">
/**
 * ONVIF discovery: run a sweep and pick one of the devices it found.
 *
 * Extracted from `CameraOnboardingPanel`. `discoveryStateLabel` moved in with it
 * — this block was its only caller. The three async actions stay with the parent
 * (they own its `working` flag and the request lifecycle) and arrive as events.
 */
import { useI18n } from "vue-i18n"

import {
  type DiscoveryCandidate,
  type DiscoverySession
} from "../../api/cameras"
import { type OnboardingWorkingAction } from "./onboarding"

defineProps<{
  discovery: DiscoverySession | null
  selectedCandidateId: string | null
  working: OnboardingWorkingAction
}>()

const emit = defineEmits<{
  discover: []
  useCandidate: [candidate: DiscoveryCandidate]
}>()

const { t, te } = useI18n({ useScope: "global" })

function discoveryStateLabel(value: string): string {
  const key = `cameras.onboarding.discoveryState.${value.toLowerCase()}`
  return te(key) ? t(key) : value
}
</script>

<template>
  <button
    class="button button--secondary"
    type="button"
    :disabled="working !== null"
    @click="emit('discover')"
  >
    {{ working === "discover" ? t("cameras.onboarding.discovering") : t("cameras.onboarding.discoverDevices") }}
  </button>

  <div
    v-if="discovery && discovery.candidates.length"
    class="candidate-list"
  >
    <button
      v-for="candidate in discovery.candidates"
      :key="candidate.id"
      type="button"
      class="candidate-card"
      :class="{
        'candidate-card--selected': selectedCandidateId === candidate.id
      }"
      :disabled="!candidate.host"
      @click="emit('useCandidate', candidate)"
    >
      <strong>{{ candidate.host || t("cameras.onboarding.addressUnavailable") }}</strong>
      <span>
        {{ candidate.port ? t("cameras.onboarding.portValue", { port: candidate.port }) : t("cameras.onboarding.defaultPort") }}
        · {{ discoveryStateLabel(candidate.state) }}
      </span>
    </button>
  </div>
  <p
    v-else-if="discovery"
    class="field-hint onboarding-hint"
  >
    {{ t("cameras.onboarding.noOnvifDevices") }}
  </p>
</template>
