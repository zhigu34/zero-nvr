<script setup lang="ts">
import { useI18n } from "vue-i18n"

import type { PlaybackResolve } from "../../api/playback"
import UiIcon from "../ui/UiIcon.vue"

type PlaybackRate = 0.5 | 1 | 2 | 4 | 8

defineProps<{
  playbackControlActive: boolean
  highSpeedMuted: boolean
  effectiveMuted: boolean
  playbackRate: PlaybackRate
  playbackRateOptions: PlaybackRate[]
  currentAt: Date
  formatTimestamp: (date: Date) => string
  canProtect: boolean
  canExport: boolean
  multiCameraMode: boolean
  playbackResult: PlaybackResolve | null
}>()

const diagnosticsOpen = defineModel<boolean>("diagnosticsOpen", { required: true })
const emit = defineEmits<{
  "toggle-playback": []
  "toggle-mute": []
  "set-rate": [rate: PlaybackRate]
  "open-action": [mode: "protect" | "export"]
}>()
const { t } = useI18n({ useScope: "global" })
</script>

<template>
  <div class="playback-controls">
    <button
      class="media-button"
      type="button"
      :aria-label="
        playbackControlActive
          ? t('playback.pause')
          : t('playback.play')
      "
      @click="emit('toggle-playback')"
    >
      <UiIcon
        :name="
          playbackControlActive
            ? 'pause'
            : 'play'
        "
        :size="16"
      />
    </button>

    <button
      class="media-button"
      type="button"
      :disabled="highSpeedMuted"
      :title="
        highSpeedMuted
          ? t('playback.highSpeedMuted')
          : effectiveMuted
            ? t('playback.unmute')
            : t('playback.mute')
      "
      :aria-label="
        highSpeedMuted
          ? t('playback.highSpeedMutedLabel')
          : effectiveMuted
            ? t('playback.unmute')
            : t('playback.mute')
      "
      @click="emit('toggle-mute')"
    >
      <UiIcon
        :name="
          effectiveMuted
            ? 'volume-off'
            : 'volume'
        "
        :size="16"
      />
    </button>

    <div class="playback-speed-switcher">
      <button
        v-for="rate in playbackRateOptions"
        :key="rate"
        class="media-button media-button--text"
        :class="{
          'media-button--active':
            playbackRate === rate
        }"
        type="button"
        :aria-pressed="
          playbackRate === rate
        "
        @click="emit('set-rate', rate)"
      >
        {{ rate }}x
      </button>
    </div>

    <button
      class="media-button media-button--text"
      :class="{
        'media-button--active':
          diagnosticsOpen
      }"
      type="button"
      :aria-pressed="diagnosticsOpen"
      @click="
        diagnosticsOpen =
          !diagnosticsOpen
      "
    >
      {{ t("playback.diagnostics") }}
    </button>

    <span class="playback-current-time">
      {{ formatTimestamp(currentAt) }}
    </span>

    <div class="playback-action-buttons">
      <button
        v-if="canProtect"
        class="media-button media-button--text"
        type="button"
        @click="emit('open-action', 'protect')"
      >
        <UiIcon name="shield" :size="14" />
        {{ t("playback.protect") }}
      </button>
      <button
        v-if="canExport"
        class="media-button media-button--text"
        type="button"
        @click="emit('open-action', 'export')"
      >
        <UiIcon name="export" :size="14" />
        {{ t("playback.export") }}
      </button>
    </div>

    <span
      v-if="multiCameraMode"
      class="playback-codec"
    >
      {{ t("playback.tolerantSync") }}
    </span>
    <span
      v-else-if="
        playbackResult?.status === 'playable'
      "
      class="playback-codec"
    >
      {{ playbackResult.codec || t("playback.video") }}
    </span>
  </div>
</template>

<style scoped>
.playback-action-buttons {
  display: flex;
  align-items: center;
  gap: 2px;
  margin-left: auto;
}
</style>
