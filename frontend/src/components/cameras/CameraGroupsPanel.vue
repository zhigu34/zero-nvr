<script setup lang="ts">
import {
  computed,
  onMounted,
  reactive,
  ref
} from "vue"

import {
  createCameraGroup,
  deleteCameraGroup,
  listCameraGroups,
  updateCameraGroup,
  type CameraGroup,
  type CameraSummary
} from "../../api/cameras"
import { errorMessage } from "../../api/client"
import UiIcon from "../ui/UiIcon.vue"

const props = defineProps<{
  cameras: CameraSummary[]
}>()

const groups = ref<CameraGroup[]>([])
const loading = ref(false)
const saving = ref(false)
const error = ref<string | null>(null)
const notice = ref<string | null>(null)
const editorOpen = ref(false)
const editing = ref<CameraGroup | null>(null)

const form = reactive({
  name: "",
  description: "",
  parentId: "",
  cameraIds: [] as string[]
})

const groupMap = computed(() =>
  new Map(groups.value.map((item) => [item.id, item]))
)

function parentName(group: CameraGroup): string {
  if (!group.parent_id) return "Top level"
  return groupMap.value.get(group.parent_id)?.name ?? "Unknown parent"
}

function descendantIds(groupId: string): Set<string> {
  const result = new Set<string>()
  const pending = [groupId]
  while (pending.length) {
    const current = pending.pop()
    if (!current) continue
    for (const group of groups.value) {
      if (
        group.parent_id === current &&
        !result.has(group.id)
      ) {
        result.add(group.id)
        pending.push(group.id)
      }
    }
  }
  return result
}

const availableParents = computed(() => {
  if (!editing.value) return groups.value
  const blocked = descendantIds(editing.value.id)
  blocked.add(editing.value.id)
  return groups.value.filter((item) => !blocked.has(item.id))
})

async function refresh(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    groups.value = await listCameraGroups()
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    loading.value = false
  }
}

function openCreate(): void {
  editing.value = null
  form.name = ""
  form.description = ""
  form.parentId = ""
  form.cameraIds = []
  editorOpen.value = true
  notice.value = null
}

function openEdit(group: CameraGroup): void {
  editing.value = group
  form.name = group.name
  form.description = group.description ?? ""
  form.parentId = group.parent_id ?? ""
  form.cameraIds = [...group.camera_ids]
  editorOpen.value = true
  notice.value = null
}

function toggleCamera(cameraId: string): void {
  const index = form.cameraIds.indexOf(cameraId)
  if (index >= 0) {
    form.cameraIds.splice(index, 1)
  } else {
    form.cameraIds.push(cameraId)
  }
}

async function save(): Promise<void> {
  saving.value = true
  error.value = null
  try {
    const body = {
      name: form.name.trim(),
      description: form.description.trim() || null,
      parent_id: form.parentId || null,
      camera_ids: [...form.cameraIds]
    }
    if (editing.value) {
      await updateCameraGroup(editing.value.id, body)
      notice.value = "Camera group updated."
    } else {
      await createCameraGroup(body)
      notice.value = "Camera group created."
    }
    editorOpen.value = false
    editing.value = null
    await refresh()
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    saving.value = false
  }
}

async function remove(group: CameraGroup): Promise<void> {
  if (!window.confirm(`Delete camera group "${group.name}"?`)) {
    return
  }
  error.value = null
  try {
    await deleteCameraGroup(group.id)
    notice.value = "Camera group deleted."
    await refresh()
  } catch (caught) {
    error.value = errorMessage(caught)
  }
}

onMounted(() => {
  void refresh()
})
</script>

<template>
  <section class="camera-groups-panel">
    <header class="camera-groups-header">
      <div>
        <strong>Camera groups</strong>
        <span>
          Organize cameras for access control and future multi-camera views.
        </span>
      </div>
      <button
        class="button button--primary"
        type="button"
        @click="openCreate"
      >
        <UiIcon name="plus" :size="14" />
        Add group
      </button>
    </header>

    <p v-if="error" class="notice notice--error">{{ error }}</p>
    <p v-if="notice" class="notice notice--success">{{ notice }}</p>

    <div
      v-if="!groups.length && !loading"
      class="empty-state empty-state--large"
    >
      <strong>No camera groups</strong>
      <p>
        Create groups such as Exterior, Entrances, Floor 1 or Warehouse.
      </p>
    </div>

    <div v-else class="camera-group-grid">
      <article
        v-for="group in groups"
        :key="group.id"
        class="camera-group-card"
      >
        <div class="camera-group-card__icon">
          <UiIcon name="folder" :size="18" />
        </div>
        <div class="camera-group-card__main">
          <strong>{{ group.name }}</strong>
          <span>{{ parentName(group) }}</span>
          <small>
            {{ group.camera_ids.length }}
            camera{{ group.camera_ids.length === 1 ? "" : "s" }}
          </small>
          <p v-if="group.description">
            {{ group.description }}
          </p>
        </div>
        <div class="camera-group-card__actions">
          <button
            class="button button--ghost button--compact"
            type="button"
            @click="openEdit(group)"
          >
            Edit
          </button>
          <button
            class="icon-button icon-button--danger"
            type="button"
            title="Delete group"
            @click="remove(group)"
          >
            <UiIcon name="trash" :size="14" />
          </button>
        </div>
      </article>
    </div>

    <aside v-if="editorOpen" class="camera-group-drawer">
      <header class="storage-editor__header">
        <div>
          <strong>
            {{ editing ? "Edit camera group" : "Add camera group" }}
          </strong>
          <span>Hierarchy and direct members</span>
        </div>
        <button
          class="icon-button"
          type="button"
          @click="editorOpen = false"
        >
          <UiIcon name="close" :size="16" />
        </button>
      </header>

      <form class="camera-group-form" @submit.prevent="save">
        <label>
          <span>Name</span>
          <input
            v-model="form.name"
            required
            maxlength="128"
          />
        </label>
        <label>
          <span>Description</span>
          <textarea
            v-model="form.description"
            rows="3"
            maxlength="2048"
          />
        </label>
        <label>
          <span>Parent group</span>
          <select v-model="form.parentId">
            <option value="">Top level</option>
            <option
              v-for="group in availableParents"
              :key="group.id"
              :value="group.id"
            >
              {{ group.name }}
            </option>
          </select>
        </label>

        <fieldset>
          <legend>Direct camera members</legend>
          <div class="camera-group-camera-list">
            <button
              v-for="camera in props.cameras"
              :key="camera.id"
              type="button"
              :class="{
                'camera-group-camera--selected':
                  form.cameraIds.includes(camera.id)
              }"
              @click="toggleCamera(camera.id)"
            >
              <span
                class="live-camera-row__status"
                :class="{
                  'live-camera-row__status--enabled':
                    camera.enabled
                }"
              />
              <span>
                <strong>{{ camera.name }}</strong>
                <small>{{ camera.location || "No location" }}</small>
              </span>
              <UiIcon
                v-if="form.cameraIds.includes(camera.id)"
                name="check"
                :size="14"
              />
            </button>
          </div>
        </fieldset>

        <div class="storage-editor__actions">
          <button
            class="button button--ghost"
            type="button"
            @click="editorOpen = false"
          >
            Cancel
          </button>
          <button
            class="button button--primary"
            type="submit"
            :disabled="saving"
          >
            {{ saving ? "Saving…" : editing ? "Save group" : "Create group" }}
          </button>
        </div>
      </form>
    </aside>
  </section>
</template>

<style scoped>
.camera-groups-panel {
  display: grid;
  gap: 10px;
}

.camera-groups-header {
  display: flex;
  min-height: 44px;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.camera-groups-header strong,
.camera-groups-header span {
  display: block;
}

.camera-groups-header strong {
  font-size: 12px;
}

.camera-groups-header span {
  margin-top: 2px;
  color: var(--text-muted);
  font-size: 8px;
}

.camera-group-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 8px;
}

.camera-group-card {
  display: grid;
  grid-template-columns: 38px minmax(0, 1fr) auto;
  align-items: start;
  gap: 9px;
  padding: 10px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--surface-raised);
}

.camera-group-card__icon {
  display: grid;
  width: 36px;
  height: 36px;
  border-radius: var(--radius-sm);
  background: var(--surface-subtle);
  color: var(--text-muted);
  place-items: center;
}

.camera-group-card__main {
  min-width: 0;
}

.camera-group-card__main strong,
.camera-group-card__main span,
.camera-group-card__main small {
  display: block;
}

.camera-group-card__main strong {
  font-size: 10px;
}

.camera-group-card__main span {
  margin-top: 2px;
  color: var(--text-secondary);
  font-size: 8px;
}

.camera-group-card__main small {
  margin-top: 2px;
  color: var(--text-muted);
  font-size: 7px;
}

.camera-group-card__main p {
  margin: 6px 0 0;
  color: var(--text-muted);
  font-size: 8px;
}

.camera-group-card__actions {
  display: flex;
  align-items: center;
  gap: 3px;
}

.camera-group-drawer {
  position: fixed;
  top: var(--topbar-height);
  right: 0;
  bottom: 0;
  z-index: 45;
  width: min(400px, 94vw);
  overflow-y: auto;
  border-left: 1px solid var(--border-subtle);
  background: var(--surface-raised);
  box-shadow: -16px 0 42px rgba(0, 0, 0, 0.18);
}

.camera-group-form {
  display: grid;
  gap: 11px;
  padding: 12px;
}

.camera-group-form > label {
  display: grid;
  gap: 5px;
}

.camera-group-form label > span {
  color: var(--text-muted);
  font-size: 8px;
  font-weight: 650;
  text-transform: uppercase;
}

.camera-group-form input,
.camera-group-form textarea,
.camera-group-form select {
  width: 100%;
  min-height: 34px;
  padding: 0 8px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  outline: 0;
  background: var(--surface-base);
  color: var(--text-primary);
  font: inherit;
  font-size: 9px;
}

.camera-group-form textarea {
  min-height: 70px;
  padding-block: 7px;
  resize: vertical;
}

.camera-group-form fieldset {
  margin: 0;
  padding: 8px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
}

.camera-group-form legend {
  padding: 0 5px;
  color: var(--text-muted);
  font-size: 8px;
  font-weight: 650;
  text-transform: uppercase;
}

.camera-group-camera-list {
  display: grid;
  gap: 4px;
}

.camera-group-camera-list button {
  display: grid;
  min-height: 44px;
  grid-template-columns: 8px minmax(0, 1fr) 18px;
  align-items: center;
  gap: 7px;
  padding: 5px 7px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: var(--surface-base);
  color: var(--text-primary);
  cursor: pointer;
  text-align: left;
}

.camera-group-camera-list .camera-group-camera--selected {
  border-color: var(--accent);
  box-shadow: 0 0 0 1px var(--accent);
}

.camera-group-camera-list strong,
.camera-group-camera-list small {
  display: block;
}

.camera-group-camera-list strong {
  font-size: 9px;
}

.camera-group-camera-list small {
  margin-top: 2px;
  color: var(--text-muted);
  font-size: 7px;
}
</style>
