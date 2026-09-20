<script setup lang="ts">
import {
  computed,
  onBeforeUnmount,
  onMounted,
  reactive,
  ref
} from "vue"

import {
  listCameras,
  type CameraSummary
} from "../api/cameras"
import { errorMessage } from "../api/client"
import {
  createRetentionPolicy,
  createStorageTarget,
  deleteRetentionPolicy,
  deleteStorageTarget,
  listRetentionPolicies,
  listStorageTargets,
  testStorageTarget,
  updateRetentionPolicy,
  updateStorageTarget,
  type RetentionPolicy,
  type RetentionPolicyCreate,
  type StorageTarget
} from "../api/storage"
import UiIcon from "../components/ui/UiIcon.vue"
import { useAuthStore } from "../stores/auth"

type StorageTab = "targets" | "retention"
type TargetFormType = "local" | "rclone"

const auth = useAuthStore()
const tab = ref<StorageTab>("targets")
const targets = ref<StorageTarget[]>([])
const policies = ref<RetentionPolicy[]>([])
const cameras = ref<CameraSummary[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const notice = ref<string | null>(null)
const targetPanelOpen = ref(false)
const policyPanelOpen = ref(false)
const targetSaving = ref(false)
const policySaving = ref(false)
const testingTargetId = ref<string | null>(null)
const testResults = ref<Record<string, string>>({})

const targetForm = reactive({
  type: "local" as TargetFormType,
  name: "",
  path: "/recordings",
  defaultRecording: false,
  remote: "",
  basePath: "zero-nvr",
  defaultArchive: false,
  rcloneConfig: ""
})

const policyForm = reactive({
  name: "Default retention",
  scopeType: "GLOBAL" as "GLOBAL" | "CAMERA",
  scopeId: "",
  ordinaryDays: 14,
  eventDays: 30,
  manualDays: 90,
  mode: "BEST_EFFORT" as "BEST_EFFORT" | "HARD",
  requireArchive: true,
  enabled: true
})

const localTargets = computed(() =>
  targets.value.filter((item) => item.type === "local")
)

const archiveTargets = computed(() =>
  targets.value.filter((item) => item.type === "rclone")
)

const enabledPolicyCount = computed(() =>
  policies.value.filter((item) => item.enabled).length
)

function formatBytes(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "—"
  const units = ["B", "KB", "MB", "GB", "TB", "PB"]
  let index = 0
  let amount = value
  while (amount >= 1024 && index < units.length - 1) {
    amount /= 1024
    index += 1
  }
  const digits = amount >= 100 || index === 0 ? 0 : amount >= 10 ? 1 : 2
  return `${amount.toFixed(digits)} ${units[index]}`
}

function targetDetail(target: StorageTarget): string {
  if (target.type === "local") {
    const path = target.config.path
    return typeof path === "string" ? path : "Local path"
  }

  const remote = target.config.remote
  const basePath = target.config.base_path
  const remoteText = typeof remote === "string" ? remote : "rclone"
  const baseText =
    typeof basePath === "string" && basePath
      ? `:${basePath}`
      : ":"
  return `${remoteText}${baseText}`
}

function targetIsDefault(target: StorageTarget): boolean {
  return target.type === "local"
    ? target.config.default_recording === true
    : target.config.default_archive === true
}

function cameraName(cameraId: string | null): string {
  if (!cameraId) return "All cameras"
  return cameras.value.find((item) => item.id === cameraId)?.name ??
    "Unknown camera"
}

function scopeLabel(policy: RetentionPolicy): string {
  if (policy.scope_type === "GLOBAL") return "All cameras"
  if (policy.scope_type === "CAMERA") return cameraName(policy.scope_id)
  return "Camera group"
}

async function refresh(): Promise<void> {
  if (!auth.hasPermission("storage.manage")) return

  loading.value = true
  error.value = null
  try {
    const [targetItems, retentionItems, cameraItems] =
      await Promise.all([
        listStorageTargets(),
        listRetentionPolicies(),
        auth.hasPermission("camera.view")
          ? listCameras()
          : Promise.resolve([])
      ])
    targets.value = targetItems
    policies.value = retentionItems
    cameras.value = cameraItems
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    loading.value = false
  }
}

function resetTargetForm(type: TargetFormType = "local"): void {
  targetForm.type = type
  targetForm.name = ""
  targetForm.path = "/recordings"
  targetForm.defaultRecording = false
  targetForm.remote = ""
  targetForm.basePath = "zero-nvr"
  targetForm.defaultArchive = false
  targetForm.rcloneConfig = ""
}

function openTargetPanel(type: TargetFormType = "local"): void {
  resetTargetForm(type)
  targetPanelOpen.value = true
  policyPanelOpen.value = false
  notice.value = null
}

async function saveTarget(): Promise<void> {
  targetSaving.value = true
  error.value = null

  try {
    if (targetForm.type === "local") {
      await createStorageTarget({
        type: "local",
        role: "recording",
        name: targetForm.name.trim(),
        enabled: true,
        config: {
          path: targetForm.path.trim(),
          default_recording: targetForm.defaultRecording
        }
      })
    } else {
      await createStorageTarget({
        type: "rclone",
        role: "archive",
        name: targetForm.name.trim(),
        enabled: true,
        config: {
          remote: targetForm.remote.trim(),
          base_path: targetForm.basePath.trim(),
          default_archive: targetForm.defaultArchive
        },
        rclone_config: targetForm.rcloneConfig
      })
    }

    targetPanelOpen.value = false
    notice.value = "Storage target created."
    await refresh()
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    targetSaving.value = false
  }
}

async function runTargetTest(target: StorageTarget): Promise<void> {
  testingTargetId.value = target.id
  error.value = null
  try {
    const result = await testStorageTarget(target.id)
    testResults.value = {
      ...testResults.value,
      [target.id]:
        result.free_bytes !== null
          ? `Ready · ${formatBytes(result.free_bytes)} free`
          : "Ready · read/write/delete verified"
    }
  } catch (caught) {
    error.value = errorMessage(caught)
    testResults.value = {
      ...testResults.value,
      [target.id]: "Test failed"
    }
  } finally {
    testingTargetId.value = null
  }
}

async function toggleTarget(target: StorageTarget): Promise<void> {
  try {
    await updateStorageTarget(target.id, {
      enabled: !target.enabled
    })
    await refresh()
  } catch (caught) {
    error.value = errorMessage(caught)
  }
}

async function removeTarget(target: StorageTarget): Promise<void> {
  if (!window.confirm(`Delete storage target "${target.name}"?`)) {
    return
  }
  try {
    await deleteStorageTarget(target.id)
    notice.value = "Storage target deleted."
    await refresh()
  } catch (caught) {
    error.value = errorMessage(caught)
  }
}

function resetPolicyForm(): void {
  policyForm.name = "Default retention"
  policyForm.scopeType = "GLOBAL"
  policyForm.scopeId = ""
  policyForm.ordinaryDays = 14
  policyForm.eventDays = 30
  policyForm.manualDays = 90
  policyForm.mode = "BEST_EFFORT"
  policyForm.requireArchive = true
  policyForm.enabled = true
}

function openPolicyPanel(): void {
  resetPolicyForm()
  policyPanelOpen.value = true
  targetPanelOpen.value = false
  notice.value = null
}

async function savePolicy(): Promise<void> {
  policySaving.value = true
  error.value = null
  const body: RetentionPolicyCreate = {
    name: policyForm.name.trim(),
    scope_type: policyForm.scopeType,
    scope_id:
      policyForm.scopeType === "CAMERA"
        ? policyForm.scopeId || null
        : null,
    ordinary_keep_days: Number(policyForm.ordinaryDays),
    event_keep_days: Number(policyForm.eventDays),
    manual_keep_days: Number(policyForm.manualDays),
    mode: policyForm.mode,
    require_archive_before_delete: policyForm.requireArchive,
    enabled: policyForm.enabled
  }

  try {
    await createRetentionPolicy(body)
    policyPanelOpen.value = false
    notice.value = "Retention policy created."
    await refresh()
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    policySaving.value = false
  }
}

async function togglePolicy(policy: RetentionPolicy): Promise<void> {
  try {
    await updateRetentionPolicy(policy.id, {
      enabled: !policy.enabled
    })
    await refresh()
  } catch (caught) {
    error.value = errorMessage(caught)
  }
}

async function removePolicy(policy: RetentionPolicy): Promise<void> {
  if (!window.confirm(`Delete retention policy "${policy.name}"?`)) {
    return
  }
  try {
    await deleteRetentionPolicy(policy.id)
    notice.value = "Retention policy deleted."
    await refresh()
  } catch (caught) {
    error.value = errorMessage(caught)
  }
}

function handleRefreshEvent(): void {
  void refresh()
}

onMounted(() => {
  void refresh()
  window.addEventListener("zero-nvr:refresh", handleRefreshEvent)
})

onBeforeUnmount(() => {
  window.removeEventListener("zero-nvr:refresh", handleRefreshEvent)
})
</script>

<template>
  <section class="storage-workspace">
    <header class="storage-header">
      <div>
        <strong>Storage</strong>
        <span>
          Local recording, remote archive and retention lifecycle.
        </span>
      </div>

      <button
        class="button button--ghost"
        type="button"
        :disabled="loading"
        @click="refresh"
      >
        <UiIcon name="refresh" :size="15" />
        Refresh
      </button>
    </header>

    <div class="storage-summary">
      <article>
        <UiIcon name="drive" :size="19" />
        <div>
          <span>Recording targets</span>
          <strong>{{ localTargets.length }}</strong>
        </div>
      </article>
      <article>
        <UiIcon name="cloud" :size="19" />
        <div>
          <span>Archive targets</span>
          <strong>{{ archiveTargets.length }}</strong>
        </div>
      </article>
      <article>
        <UiIcon name="shield" :size="19" />
        <div>
          <span>Active retention policies</span>
          <strong>{{ enabledPolicyCount }}</strong>
        </div>
      </article>
    </div>

    <div
      v-if="error"
      class="events-error"
    >
      <UiIcon name="warning" :size="16" />
      <span>{{ error }}</span>
    </div>

    <div
      v-if="notice"
      class="storage-notice"
    >
      <UiIcon name="check" :size="15" />
      <span>{{ notice }}</span>
    </div>

    <div class="storage-tabs">
      <button
        type="button"
        :class="{ 'storage-tab--active': tab === 'targets' }"
        @click="tab = 'targets'"
      >
        Storage targets
      </button>
      <button
        type="button"
        :class="{ 'storage-tab--active': tab === 'retention' }"
        @click="tab = 'retention'"
      >
        Retention
      </button>
    </div>

    <div class="storage-layout">
      <div class="storage-main">
        <template v-if="tab === 'targets'">
          <div class="storage-section-header">
            <div>
              <strong>Storage targets</strong>
              <span>
                Cameras always record locally first; archive copies are asynchronous.
              </span>
            </div>
            <div class="storage-section-actions">
              <button
                class="button button--ghost"
                type="button"
                @click="openTargetPanel('rclone')"
              >
                <UiIcon name="cloud" :size="14" />
                Add archive
              </button>
              <button
                class="button button--primary"
                type="button"
                @click="openTargetPanel('local')"
              >
                <UiIcon name="plus" :size="14" />
                Add local
              </button>
            </div>
          </div>

          <div v-if="!targets.length && !loading" class="storage-empty">
            <UiIcon name="storage" :size="28" />
            <strong>No storage targets</strong>
            <span>Add a local recording target to start storing footage.</span>
          </div>

          <div v-else class="storage-target-list">
            <article
              v-for="target in targets"
              :key="target.id"
              class="storage-target-card"
            >
              <div class="storage-target-card__icon">
                <UiIcon
                  :name="target.type === 'local' ? 'drive' : 'cloud'"
                  :size="20"
                />
              </div>

              <div class="storage-target-card__main">
                <div class="storage-target-card__title">
                  <strong>{{ target.name }}</strong>
                  <span
                    class="status-pill"
                    :class="{
                      'status-pill--ok': target.enabled,
                      'status-pill--muted': !target.enabled
                    }"
                  >
                    {{ target.enabled ? "Enabled" : "Disabled" }}
                  </span>
                  <span
                    v-if="targetIsDefault(target)"
                    class="status-pill"
                  >
                    Default
                  </span>
                </div>
                <span class="storage-target-card__path">
                  {{ targetDetail(target) }}
                </span>
                <span
                  v-if="testResults[target.id]"
                  class="storage-target-card__test"
                >
                  {{ testResults[target.id] }}
                </span>
                <span
                  v-else-if="target.type === 'rclone'"
                  class="storage-target-card__test"
                >
                  {{
                    target.credentials_configured
                      ? "Credentials configured"
                      : "Credentials missing"
                  }}
                </span>
              </div>

              <div class="storage-target-card__actions">
                <button
                  class="button button--ghost button--compact"
                  type="button"
                  :disabled="testingTargetId === target.id"
                  @click="runTargetTest(target)"
                >
                  <UiIcon name="activity" :size="14" />
                  {{
                    testingTargetId === target.id
                      ? "Testing…"
                      : "Test"
                  }}
                </button>
                <button
                  class="icon-button"
                  type="button"
                  :title="target.enabled ? 'Disable' : 'Enable'"
                  @click="toggleTarget(target)"
                >
                  <UiIcon
                    :name="target.enabled ? 'pause' : 'play'"
                    :size="15"
                  />
                </button>
                <button
                  class="icon-button icon-button--danger"
                  type="button"
                  title="Delete target"
                  @click="removeTarget(target)"
                >
                  <UiIcon name="trash" :size="15" />
                </button>
              </div>
            </article>
          </div>
        </template>

        <template v-else>
          <div class="storage-section-header">
            <div>
              <strong>Retention policies</strong>
              <span>
                Preserve event/manual footage longer while ordinary footage rotates.
              </span>
            </div>
            <button
              class="button button--primary"
              type="button"
              @click="openPolicyPanel"
            >
              <UiIcon name="plus" :size="14" />
              Add policy
            </button>
          </div>

          <div v-if="!policies.length && !loading" class="storage-empty">
            <UiIcon name="shield" :size="28" />
            <strong>No retention policies</strong>
            <span>Create a global policy or override a single camera.</span>
          </div>

          <div v-else class="retention-table-wrap">
            <table class="retention-table">
              <thead>
                <tr>
                  <th>Policy</th>
                  <th>Scope</th>
                  <th>Ordinary</th>
                  <th>Event</th>
                  <th>Manual</th>
                  <th>Archive</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="policy in policies"
                  :key="policy.id"
                >
                  <td>
                    <strong>{{ policy.name }}</strong>
                    <small>{{ policy.mode === "HARD" ? "Hard limit" : "Best effort" }}</small>
                  </td>
                  <td>{{ scopeLabel(policy) }}</td>
                  <td>{{ policy.ordinary_keep_days }}d</td>
                  <td>{{ policy.event_keep_days }}d</td>
                  <td>{{ policy.manual_keep_days }}d</td>
                  <td>
                    {{
                      policy.require_archive_before_delete
                        ? "Required"
                        : "Optional"
                    }}
                  </td>
                  <td>
                    <span
                      class="status-pill"
                      :class="{
                        'status-pill--ok': policy.enabled,
                        'status-pill--muted': !policy.enabled
                      }"
                    >
                      {{ policy.enabled ? "Enabled" : "Disabled" }}
                    </span>
                  </td>
                  <td class="retention-table__actions">
                    <button
                      class="icon-button"
                      type="button"
                      :title="policy.enabled ? 'Disable' : 'Enable'"
                      @click="togglePolicy(policy)"
                    >
                      <UiIcon
                        :name="policy.enabled ? 'pause' : 'play'"
                        :size="14"
                      />
                    </button>
                    <button
                      class="icon-button icon-button--danger"
                      type="button"
                      title="Delete policy"
                      @click="removePolicy(policy)"
                    >
                      <UiIcon name="trash" :size="14" />
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>
      </div>

      <aside
        v-if="targetPanelOpen"
        class="storage-editor"
      >
        <header class="storage-editor__header">
          <div>
            <strong>
              {{
                targetForm.type === "local"
                  ? "Add local storage"
                  : "Add archive storage"
              }}
            </strong>
            <span>
              {{
                targetForm.type === "local"
                  ? "Recording destination"
                  : "rclone remote archive"
              }}
            </span>
          </div>
          <button
            class="icon-button"
            type="button"
            title="Close"
            @click="targetPanelOpen = false"
          >
            <UiIcon name="close" :size="16" />
          </button>
        </header>

        <form class="storage-editor__form" @submit.prevent="saveTarget">
          <label>
            <span>Name</span>
            <input
              v-model="targetForm.name"
              required
              maxlength="128"
              placeholder="Primary recordings"
            />
          </label>

          <template v-if="targetForm.type === 'local'">
            <label>
              <span>Container path</span>
              <input
                v-model="targetForm.path"
                required
                placeholder="/recordings"
              />
            </label>
            <label class="storage-check">
              <input
                v-model="targetForm.defaultRecording"
                type="checkbox"
              />
              <span>Use as default recording target</span>
            </label>
          </template>

          <template v-else>
            <label>
              <span>rclone remote name</span>
              <input
                v-model="targetForm.remote"
                required
                placeholder="archive"
              />
            </label>
            <label>
              <span>Base path</span>
              <input
                v-model="targetForm.basePath"
                placeholder="zero-nvr"
              />
            </label>
            <label>
              <span>rclone config</span>
              <textarea
                v-model="targetForm.rcloneConfig"
                required
                rows="9"
                spellcheck="false"
                placeholder="[archive]&#10;type = s3&#10;..."
              />
              <small>
                Stored encrypted; never returned to the browser.
              </small>
            </label>
            <label class="storage-check">
              <input
                v-model="targetForm.defaultArchive"
                type="checkbox"
              />
              <span>Use as default archive target</span>
            </label>
          </template>

          <div class="storage-editor__actions">
            <button
              class="button button--ghost"
              type="button"
              @click="targetPanelOpen = false"
            >
              Cancel
            </button>
            <button
              class="button button--primary"
              type="submit"
              :disabled="targetSaving"
            >
              {{ targetSaving ? "Saving…" : "Create target" }}
            </button>
          </div>
        </form>
      </aside>

      <aside
        v-if="policyPanelOpen"
        class="storage-editor"
      >
        <header class="storage-editor__header">
          <div>
            <strong>Add retention policy</strong>
            <span>Recording lifecycle rules</span>
          </div>
          <button
            class="icon-button"
            type="button"
            title="Close"
            @click="policyPanelOpen = false"
          >
            <UiIcon name="close" :size="16" />
          </button>
        </header>

        <form class="storage-editor__form" @submit.prevent="savePolicy">
          <label>
            <span>Name</span>
            <input
              v-model="policyForm.name"
              required
              maxlength="128"
            />
          </label>

          <label>
            <span>Scope</span>
            <select v-model="policyForm.scopeType">
              <option value="GLOBAL">All cameras</option>
              <option value="CAMERA">Single camera</option>
            </select>
          </label>

          <label v-if="policyForm.scopeType === 'CAMERA'">
            <span>Camera</span>
            <select v-model="policyForm.scopeId" required>
              <option value="" disabled>Select a camera</option>
              <option
                v-for="camera in cameras"
                :key="camera.id"
                :value="camera.id"
              >
                {{ camera.name }}
              </option>
            </select>
          </label>

          <div class="retention-days-grid">
            <label>
              <span>Ordinary days</span>
              <input
                v-model.number="policyForm.ordinaryDays"
                type="number"
                min="0"
                max="36500"
              />
            </label>
            <label>
              <span>Event days</span>
              <input
                v-model.number="policyForm.eventDays"
                type="number"
                min="0"
                max="36500"
              />
            </label>
            <label>
              <span>Manual days</span>
              <input
                v-model.number="policyForm.manualDays"
                type="number"
                min="0"
                max="36500"
              />
            </label>
          </div>

          <label>
            <span>Policy mode</span>
            <select v-model="policyForm.mode">
              <option value="BEST_EFFORT">Best effort</option>
              <option value="HARD">Hard limit</option>
            </select>
          </label>

          <label class="storage-check">
            <input
              v-model="policyForm.requireArchive"
              type="checkbox"
            />
            <span>Require archive before local deletion</span>
          </label>

          <div class="storage-editor__actions">
            <button
              class="button button--ghost"
              type="button"
              @click="policyPanelOpen = false"
            >
              Cancel
            </button>
            <button
              class="button button--primary"
              type="submit"
              :disabled="policySaving"
            >
              {{ policySaving ? "Saving…" : "Create policy" }}
            </button>
          </div>
        </form>
      </aside>
    </div>
  </section>
</template>
