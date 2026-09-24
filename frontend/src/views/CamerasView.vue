<script setup lang="ts">
import {
  computed,
  onBeforeUnmount,
  onMounted,
  ref
} from "vue"
import { useI18n } from "vue-i18n"

import { listCameras, type CameraSummary } from "../api/cameras"
import { errorMessage } from "../api/client"
import CameraDetailPanel from "../components/cameras/CameraDetailPanel.vue"
import CameraGroupsPanel from "../components/cameras/CameraGroupsPanel.vue"
import CameraOnboardingPanel from "../components/cameras/CameraOnboardingPanel.vue"
import { useAuthStore } from "../stores/auth"

const auth = useAuthStore()
const { t, te } = useI18n({ useScope: "global" })
const cameras = ref<CameraSummary[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const showOnboarding = ref(false)
const selectedCamera = ref<CameraSummary | null>(null)
const workspace = ref<"cameras" | "groups" | "retired">("cameras")

const activeCameras = computed(() =>
  cameras.value.filter((camera) => !camera.retired_at)
)
const retiredCameras = computed(() =>
  cameras.value.filter((camera) => Boolean(camera.retired_at))
)
const inventoryCameras = computed(() =>
  workspace.value === "retired"
    ? retiredCameras.value
    : activeCameras.value
)
const inventoryTitle = computed(() =>
  workspace.value === "retired"
    ? t("cameras.retiredCameras")
    : t("cameras.configuredCameras")
)

function adapterLabel(value: string | null): string {
  const normalized = value?.toLowerCase() || "manual"
  const key = `cameras.adapter.${normalized}`
  return te(key) ? t(key) : value || t("cameras.manual")
}

async function refresh(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    cameras.value = await listCameras({
      includeRetired: auth.hasPermission("camera.configure")
    })
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    loading.value = false
  }
}

function handleRefresh(): void {
  void refresh()
}

function handleCreated(): void {
  showOnboarding.value = false
  void refresh()
}

function openCamera(camera: CameraSummary): void {
  selectedCamera.value = camera
}

async function handleCameraChanged(): Promise<void> {
  const selectedId = selectedCamera.value?.id
  await refresh()
  if (selectedId) {
    selectedCamera.value =
      cameras.value.find((item) => item.id === selectedId) ?? null
    if (selectedCamera.value?.retired_at) {
      workspace.value = "retired"
    } else if (
      selectedCamera.value &&
      workspace.value === "retired"
    ) {
      workspace.value = "cameras"
    }
  }
}

onMounted(() => {
  void refresh()
  window.addEventListener("zero-nvr:refresh", handleRefresh)
})
onBeforeUnmount(() => {
  window.removeEventListener("zero-nvr:refresh", handleRefresh)
})
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div>
        <p class="eyebrow">{{ t("cameras.deviceCenter") }}</p>
        <h1>{{ t("cameras.title") }}</h1>
        <p class="page-subtitle">
          {{ t("cameras.description") }}
        </p>
      </div>

      <div class="page-actions">
        <button
          class="button button--secondary"
          :disabled="loading"
          @click="refresh"
        >
          {{ loading ? t("cameras.refreshing") : t("cameras.refresh") }}
        </button>
        <button
          v-if="auth.hasPermission('camera.configure')"
          class="button button--primary"
          type="button"
          @click="
            workspace = 'cameras';
            selectedCamera = null;
            showOnboarding = !showOnboarding
          "
        >
          {{ showOnboarding ? t("cameras.hideOnboarding") : t("cameras.addCamera") }}
        </button>
      </div>
    </div>

    <p v-if="error" class="notice notice--error">{{ error }}</p>

    <div
      v-if="auth.hasPermission('camera.configure')"
      class="camera-workspace-tabs"
    >
      <button
        type="button"
        :class="{ 'camera-workspace-tab--active': workspace === 'cameras' }"
        @click="workspace = 'cameras'"
      >
        {{ t("cameras.title") }}
      </button>
      <button
        type="button"
        :class="{ 'camera-workspace-tab--active': workspace === 'retired' }"
        @click="
          workspace = 'retired';
          showOnboarding = false;
          selectedCamera = null
        "
      >
        {{ t("cameras.retired") }}
        <span v-if="retiredCameras.length">{{ retiredCameras.length }}</span>
      </button>
      <button
        type="button"
        :class="{ 'camera-workspace-tab--active': workspace === 'groups' }"
        @click="
          workspace = 'groups';
          showOnboarding = false;
          selectedCamera = null
        "
      >
        {{ t("cameras.groups") }}
      </button>
    </div>

    <CameraOnboardingPanel
      v-if="showOnboarding && workspace === 'cameras'"
      @created="handleCreated"
      @close="showOnboarding = false"
    />

    <CameraGroupsPanel
      v-if="workspace === 'groups'"
      :cameras="activeCameras"
    />

    <template v-else>
    <section class="panel">
      <div class="panel__header">
        <div>
          <p class="eyebrow">
            {{ workspace === "retired" ? t("cameras.history") : t("cameras.inventory") }}
          </p>
          <h2>{{ inventoryTitle }}</h2>
        </div>
        <span class="badge badge--muted">
          {{ inventoryCameras.length }}
        </span>
      </div>

      <div
        v-if="!inventoryCameras.length"
        class="empty-state empty-state--large"
      >
        <strong>
          {{
            workspace === "retired"
              ? t("cameras.noRetiredCameras")
              : t("cameras.noCamerasConfigured")
          }}
        </strong>
        <p
          v-if="
            auth.hasPermission('camera.configure') &&
            workspace !== 'retired'
          "
        >
          {{ t("cameras.addCameraHint") }}
        </p>
        <p v-else-if="workspace === 'retired'">
          {{ t("cameras.retiredHint") }}
        </p>
        <p v-else>
          {{ t("cameras.scopeEmpty") }}
        </p>
      </div>

      <div v-else class="table-wrap">
        <table class="data-table">
          <thead>
            <tr>
              <th>{{ t("cameras.name") }}</th>
              <th>{{ t("cameras.location") }}</th>
              <th>{{ t("cameras.adapterLabel") }}</th>
              <th>{{ t("cameras.storageLabel") }}</th>
              <th>{{ t("cameras.status") }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="camera in inventoryCameras"
              :key="camera.id"
              class="camera-inventory-row"
              tabindex="0"
              @click="openCamera(camera)"
              @keydown.enter="openCamera(camera)"
            >
              <td>
                <button
                  class="camera-name-button"
                  type="button"
                  @click.stop="openCamera(camera)"
                >
                  {{ camera.name }}
                </button>
              </td>
              <td>{{ camera.location || "—" }}</td>
              <td>{{ adapterLabel(camera.adapter_type) }}</td>
              <td>{{ camera.storage_label || "—" }}</td>
              <td>
                <span
                  class="badge"
                  :class="
                    camera.retired_at
                      ? 'badge--muted'
                      : camera.enabled
                        ? 'badge--ok'
                        : 'badge--muted'
                  "
                >
                  {{
                    camera.retired_at
                      ? t("cameras.retired")
                      : camera.enabled
                        ? t("cameras.enabled")
                        : t("cameras.disabled")
                  }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    </template>

    <CameraDetailPanel
      v-if="selectedCamera"
      :camera="selectedCamera"
      @close="selectedCamera = null"
      @changed="handleCameraChanged"
    />
  </div>
</template>

<style scoped>
.camera-workspace-tabs {
  display: flex;
  gap: 2px;
  margin-bottom: 10px;
  border-bottom: 1px solid var(--border-subtle);
}

.camera-workspace-tabs button {
  display: inline-flex;
  min-height: 34px;
  align-items: center;
  gap: 5px;
  padding: 0 10px;
  border: 0;
  border-bottom: 2px solid transparent;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 9px;
  font-weight: 600;
}

.camera-workspace-tabs button > span {
  display: inline-grid;
  min-width: 17px;
  height: 17px;
  padding: 0 4px;
  border-radius: 999px;
  background: var(--surface-subtle);
  place-items: center;
  font-size: 7px;
}

.camera-workspace-tabs .camera-workspace-tab--active {
  border-bottom-color: var(--accent);
  color: var(--text-primary);
}

.camera-inventory-row {
  cursor: pointer;
}

.camera-inventory-row:hover {
  background: var(--surface-hover);
}

.camera-inventory-row:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: -2px;
}

.camera-name-button {
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--text-primary);
  cursor: pointer;
  font: inherit;
  font-weight: 650;
  text-align: left;
}

.camera-name-button:hover {
  color: var(--accent);
}
</style>
