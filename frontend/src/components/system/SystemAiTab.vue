<script setup lang="ts">
/**
 * AI / Frigate integration tab: connection settings, MQTT bridge and the
 * Frigate-camera to NVR-camera mapping table.
 *
 * Extracted from `SystemView`. Every class it uses is defined globally, so no
 * stylesheet change was needed.
 *
 * The view owns the form, the mapping list and the connection status because it
 * seeds them from the settings response; they are passed in and bound directly.
 * The two mapping helpers live here since they only touch the passed array.
 */
import { useI18n } from "vue-i18n"

import { type CameraSummary } from "../../api/cameras"
import { type FrigateCameraMapping } from "../../api/system"
import UiIcon from "../ui/UiIcon.vue"

export interface FrigateForm {
  enabled: boolean
  mode: "managed" | "external"
  baseUrl: string
  mqttEnabled: boolean
  mqttHost: string
  mqttPort: number
  mqttTopicPrefix: string
  mqttTls: boolean
  bearerToken: string
  httpUsername: string
  httpPassword: string
  mqttUsername: string
  mqttPassword: string
}

const props = defineProps<{
  frigateForm: FrigateForm
  frigateConfigured: boolean
  frigateVersion: string | null
  frigateMappings: FrigateCameraMapping[]
  frigateSaving: boolean
  frigateTesting: boolean
  cameras: CameraSummary[]
}>()

const emit = defineEmits<{
  save: []
  test: []
  backfill: []
}>()

const { t } = useI18n({ useScope: "global" })

function addMapping(): void {
  props.frigateMappings.push({
    frigate_camera: "",
    camera_id: props.cameras[0]?.id ?? ""
  })
}

function removeMapping(index: number): void {
  props.frigateMappings.splice(index, 1)
}
</script>

<template>
  <header class="system-page-header">
    <div>
      <strong>{{ t("system.main.aiFrigate") }}</strong>
      <span>{{ t("system.main.frigateDesc") }}</span>
    </div>
    <div class="system-page-actions">
      <button
        v-if="frigateConfigured"
        class="button button--ghost"
        type="button"
        :disabled="frigateTesting"
        @click="emit('test')"
      >
        <UiIcon name="activity" :size="14" />
        {{ frigateTesting ? t("system.main.testing") : t("system.main.test") }}
      </button>
      <button
        v-if="frigateConfigured && frigateForm.enabled"
        class="button button--ghost"
        type="button"
        @click="emit('backfill')"
      >
        {{ t("system.main.backfill10m") }}
      </button>
    </div>
  </header>

  <form class="system-form-card system-form-card--wide" @submit.prevent="emit('save')">
    <div class="system-form-row">
      <label>
        <span>{{ t("system.main.mode") }}</span>
        <select v-model="frigateForm.mode">
          <option value="external">{{ t("system.main.externalFrigate") }}</option>
          <option value="managed">{{ t("system.main.managedProfile") }}</option>
        </select>
      </label>
      <label>
        <span>{{ t("system.main.baseUrl") }}</span>
        <input
          v-model="frigateForm.baseUrl"
          required
          placeholder="http://frigate:5000"
        />
      </label>
    </div>

    <label class="storage-check">
      <input v-model="frigateForm.enabled" type="checkbox" />
      <span>{{ t("system.main.enableFrigate") }}</span>
    </label>

    <div class="system-subsection">
      <div class="system-subsection__heading">
        <div>
          <strong>{{ t("system.main.cameraMapping") }}</strong>
          <span>{{ t("system.main.cameraMappingHint") }}</span>
        </div>
        <button class="button button--ghost button--compact" type="button" @click="addMapping">
          <UiIcon name="plus" :size="13" />
          {{ t("system.main.addMapping") }}
        </button>
      </div>
      <div class="frigate-mapping-list">
        <div
          v-for="(mapping, index) in frigateMappings"
          :key="index"
          class="frigate-mapping-row"
        >
          <input
            v-model="mapping.frigate_camera"
            placeholder="front_door"
          />
          <UiIcon name="next" :size="13" />
          <select v-model="mapping.camera_id">
            <option value="" disabled>{{ t("system.main.selectCamera") }}</option>
            <option
              v-for="camera in cameras"
              :key="camera.id"
              :value="camera.id"
            >
              {{ camera.name }}
            </option>
          </select>
          <button class="icon-button icon-button--danger" type="button" @click="removeMapping(index)">
            <UiIcon name="trash" :size="14" />
          </button>
        </div>
      </div>
    </div>

    <div class="system-subsection">
      <div class="system-subsection__heading">
        <div>
          <strong>{{ t("system.main.httpCredentials") }}</strong>
          <span>{{ t("system.main.keepCredentials") }}</span>
        </div>
        <span v-if="frigateConfigured" class="status-pill">
          {{ t("system.main.existing") }} {{ frigateConfigured ? t("system.main.configured") : t("system.main.none") }}
        </span>
      </div>
      <div class="system-form-row system-form-row--three">
        <label>
          <span>{{ t("system.main.bearerToken") }}</span>
          <input v-model="frigateForm.bearerToken" type="password" />
        </label>
        <label>
          <span>{{ t("system.main.username") }}</span>
          <input v-model="frigateForm.httpUsername" />
        </label>
        <label>
          <span>{{ t("system.main.password") }}</span>
          <input v-model="frigateForm.httpPassword" type="password" />
        </label>
      </div>
    </div>

    <div class="system-subsection">
      <div class="system-subsection__heading">
        <div>
          <strong>{{ t("system.main.mqtt") }}</strong>
          <span>{{ t("system.main.mqttHint") }}</span>
        </div>
        <label class="storage-check">
          <input v-model="frigateForm.mqttEnabled" type="checkbox" />
          <span>{{ t("system.main.enableMqtt") }}</span>
        </label>
      </div>
      <div class="system-form-row system-form-row--three">
        <label>
          <span>{{ t("system.main.host") }}</span>
          <input v-model="frigateForm.mqttHost" placeholder="mosquitto" />
        </label>
        <label>
          <span>{{ t("system.main.port") }}</span>
          <input v-model.number="frigateForm.mqttPort" type="number" min="1" max="65535" />
        </label>
        <label>
          <span>{{ t("system.main.topicPrefix") }}</span>
          <input v-model="frigateForm.mqttTopicPrefix" />
        </label>
      </div>
    </div>

    <div class="system-form-actions">
      <span v-if="frigateVersion" class="system-form-hint">
        Frigate {{ frigateVersion }}
      </span>
      <button class="button button--primary" type="submit" :disabled="frigateSaving">
        {{ frigateSaving ? t("system.main.saving") : t("system.main.saveFrigate") }}
      </button>
    </div>
  </form>
</template>
