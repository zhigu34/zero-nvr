
<script setup lang="ts">
import {
  computed,
  onMounted,
  reactive,
  ref
} from "vue"
import { useI18n } from "vue-i18n"

import {
  createCameraGroup,
  deleteCameraGroup,
  listCameraGroups,
  updateCameraGroup,
  type CameraGroup,
  type CameraSummary
} from "../../api/cameras"
import { errorMessage } from "../../api/client"
import DrawerDialog from "../ui/DrawerDialog.vue"
import EmptyState from "../ui/EmptyState.vue"
import UiIcon from "../ui/UiIcon.vue"

import { confirmAction } from "../../composables/useConfirm"
import { useAsyncResource } from "../../composables/useAsyncResource"

const { loading, error, run } = useAsyncResource()

// These prompts all remove or irreversibly change stored data, so the
// dialog styles the accept action as destructive.
const confirmDestroy = (message: string) =>
  confirmAction({ message, danger: true })

const { t } = useI18n({ useScope: "global" })

const props = defineProps<{
  cameras: CameraSummary[]
}>()

const groups = ref<CameraGroup[]>([])
const saving = ref(false)
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
  if (!group.parent_id) return t("cameras.groupsPanel.topLevel")
  return groupMap.value.get(group.parent_id)?.name ?? t("cameras.groupsPanel.unknownParent")
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
  await run(async () => {
    groups.value = await listCameraGroups()
  })
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
      notice.value = t("cameras.groupsPanel.updated")
    } else {
      await createCameraGroup(body)
      notice.value = t("cameras.groupsPanel.created")
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
  if (!await confirmDestroy(t("cameras.groupsPanel.deleteConfirm", { name: group.name }))) {
    return
  }
  error.value = null
  try {
    await deleteCameraGroup(group.id)
    notice.value = t("cameras.groupsPanel.deleted")
    await refresh()
  } catch (caught) {
    error.value = errorMessage(caught)
  }
}

function groupCameraCount(count: number): string {
  return count === 1
    ? t("cameras.groupsPanel.cameraCountOne", { count })
    : t("cameras.groupsPanel.cameraCountMany", { count })
}

onMounted(() => {
  void refresh()
})
</script>

<template>
  <section class="camera-groups-panel">
    <header class="camera-groups-header">
      <div>
        <strong>{{ t("cameras.groupsPanel.title") }}</strong>
        <span>
          {{ t("cameras.groupsPanel.description") }}
        </span>
      </div>
      <button
        class="button button--primary"
        type="button"
        @click="openCreate"
      >
        <UiIcon name="plus" :size="14" />
        {{ t("cameras.groupsPanel.addGroup") }}
      </button>
    </header>

    <p v-if="error" class="notice notice--error">{{ error }}</p>
    <p v-if="notice" class="notice notice--success">{{ notice }}</p>

    <EmptyState
      v-if="!groups.length && !loading"
      surface-class="empty-state"
      large
    >
      <strong>{{ t("cameras.groupsPanel.noGroups") }}</strong>
      <p>
        {{ t("cameras.groupsPanel.noGroupsHint") }}
      </p>
    </EmptyState>

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
            {{ groupCameraCount(group.camera_ids.length) }}
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
            {{ t("cameras.groupsPanel.edit") }}
          </button>
          <button
            class="icon-button icon-button--danger"
            type="button"
            :title="t('cameras.groupsPanel.deleteGroup')"
            @click="remove(group)"
          >
            <UiIcon name="trash" :size="14" />
          </button>
        </div>
      </article>
    </div>

    <DrawerDialog
      :open="editorOpen"
      backdrop-class="camera-group-drawer-backdrop"
      @dismiss="editorOpen = false"
    >
      <aside class="camera-group-drawer" @click.stop>
      <header class="storage-editor__header">
        <div>
          <strong>
            {{ editing ? t("cameras.groupsPanel.editTitle") : t("cameras.groupsPanel.addTitle") }}
          </strong>
          <span>{{ t("cameras.groupsPanel.hierarchy") }}</span>
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
          <span>{{ t("cameras.name") }}</span>
          <input
            v-model="form.name"
            required
            maxlength="128"
          />
        </label>
        <label>
          <span>{{ t("cameras.groupsPanel.descriptionLabel") }}</span>
          <textarea
            v-model="form.description"
            rows="3"
            maxlength="2048"
          />
        </label>
        <label>
          <span>{{ t("cameras.groupsPanel.parentGroup") }}</span>
          <select v-model="form.parentId">
            <option value="">{{ t("cameras.groupsPanel.topLevel") }}</option>
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
          <legend>{{ t("cameras.groupsPanel.directMembers") }}</legend>
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
                <small>{{ camera.location || t("cameras.noLocation") }}</small>
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
            {{ t("cameras.groupsPanel.cancel") }}
          </button>
          <button
            class="button button--primary"
            type="submit"
            :disabled="saving"
          >
            {{ saving ? t("cameras.groupsPanel.saving") : editing ? t("cameras.groupsPanel.saveGroup") : t("cameras.groupsPanel.createGroup") }}
          </button>
        </div>
      </form>
      </aside>
    </DrawerDialog>
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

.camera-group-drawer-backdrop {
  position: fixed;
  inset: 0;
  z-index: 50;
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(4px);
  display: flex;
  justify-content: flex-end;
}

.camera-group-drawer {
  position: relative;
  width: min(440px, 94vw);
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  border-left: 1px solid var(--uf-border);
  background: var(--uf-bg-card);
  box-shadow: var(--uf-shadow-lg);
  animation: slideDrawer 0.22s cubic-bezier(0.16, 1, 0.3, 1);
}

@keyframes slideDrawer {
  from {
    transform: translateX(100%);
  }
  to {
    transform: translateX(0);
  }
}

.camera-group-form {
  display: grid;
  gap: 14px;
  padding: 18px;
}

.camera-group-form > label {
  display: grid;
  gap: 6px;
}

.camera-group-form label > span {
  color: var(--uf-text-muted);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.camera-group-form input,
.camera-group-form textarea,
.camera-group-form select {
  width: 100%;
  min-height: 38px;
  padding: 0 10px;
  border: 1px solid var(--uf-border);
  border-radius: 8px;
  outline: 0;
  background: var(--uf-bg-input);
  color: var(--uf-text-primary);
  font: inherit;
  font-size: 13px;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.camera-group-form input:focus,
.camera-group-form textarea:focus,
.camera-group-form select:focus {
  border-color: var(--uf-accent);
  box-shadow: 0 0 0 3px var(--uf-accent-soft);
}

.camera-group-form textarea {
  min-height: 80px;
  padding: 8px 10px;
  resize: vertical;
}

.camera-group-form fieldset {
  margin: 0;
  padding: 12px;
  border: 1px solid var(--uf-border);
  border-radius: 10px;
  background: var(--uf-bg-card-sub);
}

.camera-group-form legend {
  padding: 0 6px;
  color: var(--uf-text-muted);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.camera-group-camera-list {
  display: grid;
  gap: 6px;
  max-height: 260px;
  overflow-y: auto;
}

.camera-group-camera-list button {
  display: grid;
  min-height: 44px;
  grid-template-columns: 8px minmax(0, 1fr) 18px;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border: 1px solid var(--uf-border);
  border-radius: 8px;
  background: var(--uf-bg-card);
  color: var(--uf-text-primary);
  cursor: pointer;
  text-align: left;
  transition: all 0.15s ease;
}

.camera-group-camera-list button:hover {
  background: var(--uf-bg-hover);
}

.camera-group-camera-list .camera-group-camera--selected {
  border-color: var(--uf-accent);
  background: var(--uf-accent-soft);
  box-shadow: 0 0 0 1px var(--uf-accent);
}

.camera-group-camera-list strong,
.camera-group-camera-list small {
  display: block;
}

.camera-group-camera-list strong {
  font-size: 12px;
  font-weight: 600;
  color: var(--uf-text-primary);
}

.camera-group-camera-list small {
  margin-top: 2px;
  color: var(--uf-text-muted);
  font-size: 11px;
}
</style>
