<script setup lang="ts">
/**
 * ONVIF inspection result: what the device reported, whether its identity
 * conflicts with a camera already on record, and which stream profiles to import.
 *
 * Extracted from `CameraOnboardingPanel`. `profileSummary` moved in — this block
 * was its only caller. The panel's own `identity`, `identityConflict` and
 * `identityRequiresConfirmation` computeds stay with the parent, because its
 * import action label and payload logic read them; this markup reads
 * `inspection.identity` directly instead.
 */
import { useI18n } from "vue-i18n"

import { type OnvifInspection } from "../../api/cameras"

defineProps<{ inspection: OnvifInspection | null }>()

const confirmExistingIdentity = defineModel<boolean>("confirmExistingIdentity", {
  required: true
})
const selectedProfiles = defineModel<string[]>("selectedProfiles", {
  required: true
})

const { t } = useI18n({ useScope: "global" })

function profileSummary(
  profile: OnvifInspection["profiles"][number]
): string {
  const parts = [
    profile.codec,
    profile.width && profile.height
      ? `${profile.width}×${profile.height}`
      : null,
    profile.fps ? `${profile.fps} fps` : null
  ]
  return (
    parts.filter(Boolean).join(" · ") ||
    t("cameras.onboarding.profileUnavailable")
  )
}
</script>

<template>
  <div class="onboarding-step">
  <div class="step-heading">
    <span>2</span>
    <div>
      <strong>{{ t("cameras.onboarding.chooseProfiles") }}</strong>
      <p>{{ t("cameras.onboarding.profilesHint") }}</p>
    </div>
  </div>

  <div v-if="inspection" class="inspection-card">
    <div class="device-summary">
      <strong>
        {{ inspection.device.manufacturer || t("cameras.onboarding.onvifDevice") }}
        {{ inspection.device.model || "" }}
      </strong>
      <span v-if="inspection.device.serial_number">
        S/N {{ inspection.device.serial_number }}
      </span>
    </div>

    <p
      v-if="inspection.identity.state === 'new_device'"
      class="notice notice--success"
      role="status"
    >
      {{ t("cameras.onboarding.newIdentity") }}
    </p>
    <p
      v-else-if="inspection.identity.state === 'same_device'"
      class="notice notice--success"
      role="status"
    >
      {{ t("cameras.onboarding.existingIdentityPrefix") }}
      <strong>
        {{ inspection.identity.matched_device_name || inspection.identity.matched_device_id }}
      </strong>{{ t("cameras.onboarding.existingIdentitySuffix") }}
    </p>
    <div
      v-else-if="
        inspection.identity.state ===
        'probable_match_requires_confirmation'
      "
      class="notice"
      role="status"
    >
      <strong>{{ t("cameras.onboarding.identityConfirmation") }}</strong>
      {{ t("cameras.onboarding.endpointBelongsPrefix") }}
      <strong>
        {{ inspection.identity.matched_device_name || inspection.identity.matched_device_id }}
      </strong>{{ t("cameras.onboarding.endpointBelongsSuffix") }}
      <label class="check-row">
        <input v-model="confirmExistingIdentity" type="checkbox" />
        <span>{{ t("cameras.onboarding.confirmSameDevice") }}</span>
      </label>
    </div>
    <p
      v-else
      class="notice notice--error"
      role="alert"
    >
      <strong>{{ t("cameras.onboarding.identityConflict") }}</strong>
      {{ t("cameras.onboarding.identityConflictHint") }}
    </p>

    <div class="profile-list">
      <label
        v-for="profile in inspection.profiles"
        :key="profile.token"
        class="profile-option"
        :class="{ 'profile-option--disabled': !profile.stream_uri_available }"
      >
        <input
          v-model="selectedProfiles"
          type="checkbox"
          :value="profile.token"
          :disabled="!profile.stream_uri_available"
        />
        <span>
          <strong>{{ profile.name }}</strong>
          <small>{{ profileSummary(profile) }}</small>
        </span>
      </label>
    </div>
  </div>

  <div v-else class="step-empty">
    {{ t("cameras.onboarding.testDeviceHint") }}
  </div>
  </div>
</template>
