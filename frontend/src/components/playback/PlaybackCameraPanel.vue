<script setup lang="ts">
import { computed, ref } from "vue"
import { useI18n } from "vue-i18n"

import type { CameraSummary } from "../../api/cameras"
import UiIcon from "../ui/UiIcon.vue"

const props = defineProps<{
  open: boolean
  cameras: CameraSummary[]
  loading: boolean
  activeCameraId: string | null
  syncedCameraIds: string[]
}>()

const emit = defineEmits<{
  refresh: []
  select: [cameraId: string]
  "toggle-sync": [cameraId: string]
}>()

const { t } = useI18n({ useScope: "global" })
const search = ref("")
const filteredCameras = computed(() => {
  const needle = search.value.trim().toLowerCase()
  if (!needle) return props.cameras
  return props.cameras.filter((camera) =>
    [camera.name, camera.location, camera.adapter_type]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(needle))
  )
})

function isSyncParticipant(cameraId: string): boolean {
  return cameraId === props.activeCameraId || props.syncedCameraIds.includes(cameraId)
}
</script>

<template>
  <aside
    v-if="open"
    class="live-camera-panel playback-camera-panel"
  >
    <div class="live-camera-panel__header">
      <div>
        <strong>{{ t("playback.cameras") }}</strong>
        <span>{{ t("playback.availableCount", { count: cameras.length }) }}</span>
      </div>
      <button
        class="icon-button topbar-icon-button"
        type="button"
        :title="t('playback.refreshCameras')"
        :aria-label="t('playback.refreshCameras')"
        :disabled="loading"
        @click="emit('refresh')"
      >
        <UiIcon name="refresh" :size="16" />
      </button>
    </div>

    <label class="live-search">
      <UiIcon name="search" :size="15" />
      <input
        v-model="search"
        type="search"
        :placeholder="t('playback.searchCameras')"
        :aria-label="t('playback.searchCameras')"
      />
    </label>

    <div class="live-camera-list">
      <div
        v-for="camera in filteredCameras"
        :key="camera.id"
        class="playback-camera-select-row"
      >
        <button
          class="live-camera-row playback-camera-select-row__primary"
          :class="{
            'live-camera-row--selected':
              activeCameraId === camera.id
          }"
          type="button"
          @click="emit('select', camera.id)"
        >
          <span
            class="live-camera-row__status"
            :class="{
              'live-camera-row__status--enabled':
                camera.enabled
            }"
          />
          <span class="live-camera-row__copy">
            <strong>{{ camera.name }}</strong>
            <small>
              {{
                camera.location ||
                camera.adapter_type ||
                t("playback.cameraFallback")
              }}
            </small>
          </span>
          <span class="live-camera-row__check">
            <UiIcon
              v-if="activeCameraId === camera.id"
              name="chevron-right"
              :size="14"
            />
          </span>
        </button>

        <button
          class="playback-sync-toggle"
          :class="{
            'playback-sync-toggle--active':
              isSyncParticipant(camera.id)
          }"
          type="button"
          :disabled="
            activeCameraId === camera.id
          "
          :title="
            activeCameraId === camera.id
              ? t('playback.primarySyncCamera')
              : isSyncParticipant(camera.id)
                ? t('playback.removeFromSync')
                : t('playback.addToSync')
          "
          :aria-label="
            isSyncParticipant(camera.id)
              ? t('playback.removeSyncCamera')
              : t('playback.addSyncCamera')
          "
          @click="emit('toggle-sync', camera.id)"
        >
          <UiIcon
            :name="
              isSyncParticipant(camera.id)
                ? 'check'
                : 'plus'
            "
            :size="13"
          />
        </button>
      </div>

      <div
        v-if="!filteredCameras.length && !loading"
        class="live-camera-list__empty"
      >
        {{ t("playback.noCamerasFound") }}
      </div>
    </div>
  </aside>
</template>
