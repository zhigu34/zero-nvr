<script setup lang="ts">
import {
  computed,
  onMounted,
  reactive,
  ref
} from "vue"
import { useI18n } from "vue-i18n"

import {
  listCameraGroups,
  listCameras,
  type CameraGroup,
  type CameraSummary
} from "../../api/cameras"
import { errorMessage } from "../../api/client"
import {
  createOidcProvider,
  createRole,
  createUser,
  deleteOidcProvider,
  getRoleCameraScope,
  getUserCameraScope,
  listOidcProviders,
  listPermissions,
  listRoles,
  listUsers,
  issueUserPasswordReset,
  setRoleCameraScope,
  setUserCameraScope,
  setUserEnabled,
  updateOidcProvider,
  updateRole,
  updateUser,
  type AdminUser,
  type CameraScope,
  type OidcProvider,
  type Role
} from "../../api/system"
import UiIcon from "../ui/UiIcon.vue"

const { locale, t } = useI18n({ useScope: "global" })

type AccessTab = "users" | "roles" | "oidc"
type EditorKind =
  | "user"
  | "role"
  | "password"
  | "scope"
  | "oidc"
  | null

const tab = ref<AccessTab>("users")
const users = ref<AdminUser[]>([])
const roles = ref<Role[]>([])
const oidcProviders = ref<OidcProvider[]>([])
const permissions = ref<string[]>([])
const cameras = ref<CameraSummary[]>([])
const cameraGroups = ref<CameraGroup[]>([])
const loading = ref(false)
const saving = ref(false)
const error = ref<string | null>(null)
const notice = ref<string | null>(null)
const editorKind = ref<EditorKind>(null)
const editingUser = ref<AdminUser | null>(null)
const editingRole = ref<Role | null>(null)
const editingOidc = ref<OidcProvider | null>(null)
const scopeOwnerType = ref<"user" | "role">("user")
const scopeOwnerId = ref("")
const scopeOwnerLabel = ref("")


const userForm = reactive({
  username: "",
  displayName: "",
  email: "",
  password: "",
  roleIds: [] as string[]
})

const roleForm = reactive({
  name: "",
  description: "",
  permissionIds: [] as string[]
})

const oidcForm = reactive({
  key: "",
  name: "",
  issuer: "",
  clientId: "",
  clientSecret: "",
  enabled: true,
  autoProvision: false,
  emailLinking: false,
  defaultRoleIds: [] as string[]
})

const issuedReset = ref<{
  token: string
  expires_at: string
} | null>(null)

const scopeForm = reactive({
  mode: "inherit" as CameraScope["mode"],
  cameraIds: [] as string[],
  groupIds: [] as string[]
})

const permissionGroups = computed(() => {
  const groups = new Map<string, string[]>()
  for (const permission of permissions.value) {
    const domain = permission.split(".", 1)[0] || "other"
    const items = groups.get(domain) ?? []
    items.push(permission)
    groups.set(domain, items)
  }
  return Array.from(groups.entries())
    .map(([domain, items]) => ({
      domain,
      items: items.sort()
    }))
    .sort((a, b) => a.domain.localeCompare(b.domain))
})

function closeEditor(): void {
  editorKind.value = null
  editingUser.value = null
  editingRole.value = null
  editingOidc.value = null
  scopeOwnerId.value = ""
  scopeOwnerLabel.value = ""
  scopeForm.groupIds = []
}

async function refresh(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const [
      userItems,
      roleItems,
      oidcItems,
      permissionItems,
      cameraItems,
      groupItems
    ] = await Promise.all([
      listUsers(),
      listRoles(),
      listOidcProviders(),
      listPermissions(),
      listCameras().catch(() => []),
      listCameraGroups().catch(() => [])
    ])
    users.value = userItems
    roles.value = roleItems
    oidcProviders.value = oidcItems
    permissions.value = permissionItems
    cameras.value = cameraItems
    cameraGroups.value = groupItems
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    loading.value = false
  }
}

function openCreateUser(): void {
  editingUser.value = null
  userForm.username = ""
  userForm.displayName = ""
  userForm.email = ""
  userForm.password = ""
  const viewer = roles.value.find((item) => item.name === "Viewer")
  userForm.roleIds = viewer ? [viewer.id] : []
  editorKind.value = "user"
  notice.value = null
}

function openEditUser(user: AdminUser): void {
  editingUser.value = user
  userForm.username = user.username
  userForm.displayName = user.display_name
  userForm.email = user.email ?? ""
  userForm.password = ""
  userForm.roleIds = user.roles.map((item) => item.id)
  editorKind.value = "user"
  notice.value = null
}

async function saveUser(): Promise<void> {
  saving.value = true
  error.value = null
  try {
    if (editingUser.value) {
      await updateUser(editingUser.value.id, {
        display_name: userForm.displayName.trim(),
        email: userForm.email.trim() || null,
        role_ids: [...userForm.roleIds]
      })
      notice.value = t("system.access.userUpdated", { username: editingUser.value.username })
    } else {
      await createUser({
        username: userForm.username.trim(),
        display_name: userForm.displayName.trim(),
        email: userForm.email.trim() || null,
        password: userForm.password,
        role_ids: [...userForm.roleIds]
      })
      notice.value = t("system.access.userCreated")
    }
    closeEditor()
    await refresh()
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    saving.value = false
  }
}

async function toggleUser(user: AdminUser): Promise<void> {
  error.value = null
  try {
    await setUserEnabled(user.id, !user.enabled)
    await refresh()
  } catch (caught) {
    error.value = errorMessage(caught)
  }
}

function openPasswordReset(user: AdminUser): void {
  editingUser.value = user
  issuedReset.value = null
  editorKind.value = "password"
  notice.value = null
}

async function savePasswordReset(): Promise<void> {
  if (!editingUser.value) return

  saving.value = true
  error.value = null
  try {
    issuedReset.value =
      await issueUserPasswordReset(
        editingUser.value.id
      )
    notice.value = t("system.access.resetIssued", { username: editingUser.value.username })
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    saving.value = false
  }
}

async function copyIssuedReset(): Promise<void> {
  if (!issuedReset.value) return
  try {
    await navigator.clipboard.writeText(
      issuedReset.value.token
    )
    notice.value = t("system.access.resetCopied")
  } catch {
    notice.value = t("system.access.copyBlocked")
  }
}

function openCreateRole(): void {
  editingRole.value = null
  roleForm.name = ""
  roleForm.description = ""
  roleForm.permissionIds = []
  editorKind.value = "role"
  notice.value = null
}

function openEditRole(role: Role): void {
  editingRole.value = role
  roleForm.name = role.name
  roleForm.description = role.description ?? ""
  roleForm.permissionIds = [...role.permissions]
  editorKind.value = "role"
  notice.value = null
}

async function saveRole(): Promise<void> {
  saving.value = true
  error.value = null
  try {
    if (editingRole.value) {
      if (editingRole.value.built_in) {
        throw new Error(t("system.access.builtinRoleImmutable"))
      }
      await updateRole(editingRole.value.id, {
        name: roleForm.name.trim(),
        description: roleForm.description.trim() || null,
        permissions: [...roleForm.permissionIds]
      })
      notice.value = t("system.access.roleUpdated")
    } else {
      await createRole({
        name: roleForm.name.trim(),
        description: roleForm.description.trim() || null,
        permissions: [...roleForm.permissionIds]
      })
      notice.value = t("system.access.roleCreated")
    }
    closeEditor()
    await refresh()
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    saving.value = false
  }
}

function openCreateOidc(): void {
  editingOidc.value = null
  oidcForm.key = ""
  oidcForm.name = ""
  oidcForm.issuer = ""
  oidcForm.clientId = ""
  oidcForm.clientSecret = ""
  oidcForm.enabled = true
  oidcForm.autoProvision = false
  oidcForm.emailLinking = false
  const viewer = roles.value.find(
    (item) => item.name === "Viewer"
  )
  oidcForm.defaultRoleIds = viewer
    ? [viewer.id]
    : []
  editorKind.value = "oidc"
  notice.value = null
}

function openEditOidc(provider: OidcProvider): void {
  editingOidc.value = provider
  oidcForm.key = provider.key
  oidcForm.name = provider.name
  oidcForm.issuer = provider.issuer
  oidcForm.clientId = provider.client_id
  oidcForm.clientSecret = ""
  oidcForm.enabled = provider.enabled
  oidcForm.autoProvision =
    provider.auto_provision
  oidcForm.emailLinking =
    provider.email_linking
  oidcForm.defaultRoleIds = [
    ...provider.default_role_ids
  ]
  editorKind.value = "oidc"
  notice.value = null
}

async function saveOidc(): Promise<void> {
  saving.value = true
  error.value = null
  try {
    if (
      oidcForm.autoProvision &&
      !oidcForm.defaultRoleIds.length
    ) {
      throw new Error(
        t("system.access.defaultRoleRequired")
      )
    }

    if (editingOidc.value) {
      const changes: {
        name: string
        enabled: boolean
        issuer: string
        client_id: string
        auto_provision: boolean
        email_linking: boolean
        default_role_ids: string[]
        client_secret?: string
      } = {
        name: oidcForm.name.trim(),
        enabled: oidcForm.enabled,
        issuer: oidcForm.issuer.trim(),
        client_id: oidcForm.clientId.trim(),
        auto_provision: oidcForm.autoProvision,
        email_linking: oidcForm.emailLinking,
        default_role_ids: [
          ...oidcForm.defaultRoleIds
        ]
      }
      if (oidcForm.clientSecret) {
        changes.client_secret =
          oidcForm.clientSecret
      }
      await updateOidcProvider(
        editingOidc.value.key,
        changes
      )
      notice.value = t("system.access.oidcUpdated")
    } else {
      await createOidcProvider({
        key: oidcForm.key.trim(),
        name: oidcForm.name.trim(),
        enabled: oidcForm.enabled,
        issuer: oidcForm.issuer.trim(),
        client_id: oidcForm.clientId.trim(),
        client_secret:
          oidcForm.clientSecret,
        auto_provision:
          oidcForm.autoProvision,
        email_linking:
          oidcForm.emailLinking,
        default_role_ids: [
          ...oidcForm.defaultRoleIds
        ]
      })
      notice.value = t("system.access.oidcCreated")
    }
    closeEditor()
    await refresh()
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    saving.value = false
  }
}

async function removeOidc(
  provider: OidcProvider
): Promise<void> {
  if (
    !window.confirm(
      t("system.access.deleteOidcConfirm", { name: provider.name })
    )
  ) {
    return
  }

  error.value = null
  try {
    await deleteOidcProvider(provider.key)
    notice.value = t("system.access.oidcDeleted", { name: provider.name })
    await refresh()
  } catch (caught) {
    error.value = errorMessage(caught)
  }
}

async function openUserScope(user: AdminUser): Promise<void> {
  error.value = null
  try {
    const scope = await getUserCameraScope(user.id)
    scopeOwnerType.value = "user"
    scopeOwnerId.value = user.id
    scopeOwnerLabel.value = `@${user.username}`
    scopeForm.mode = scope.mode
    scopeForm.cameraIds = [...scope.camera_ids]
    scopeForm.groupIds = [...scope.camera_group_ids]
    editorKind.value = "scope"
    notice.value = null
  } catch (caught) {
    error.value = errorMessage(caught)
  }
}

async function openRoleScope(role: Role): Promise<void> {
  error.value = null
  try {
    const scope = await getRoleCameraScope(role.id)
    scopeOwnerType.value = "role"
    scopeOwnerId.value = role.id
    scopeOwnerLabel.value = role.name
    scopeForm.mode =
      scope.mode === "inherit" ? "all" : scope.mode
    scopeForm.cameraIds = [...scope.camera_ids]
    scopeForm.groupIds = [...scope.camera_group_ids]
    editorKind.value = "scope"
    notice.value = null
  } catch (caught) {
    error.value = errorMessage(caught)
  }
}

function toggleScopeCamera(cameraId: string): void {
  const index = scopeForm.cameraIds.indexOf(cameraId)
  if (index >= 0) {
    scopeForm.cameraIds.splice(index, 1)
  } else {
    scopeForm.cameraIds.push(cameraId)
  }
}

function toggleScopeGroup(groupId: string): void {
  const index = scopeForm.groupIds.indexOf(groupId)
  if (index >= 0) {
    scopeForm.groupIds.splice(index, 1)
  } else {
    scopeForm.groupIds.push(groupId)
  }
}

async function saveScope(): Promise<void> {
  if (!scopeOwnerId.value) return
  saving.value = true
  error.value = null

  try {
    const selected = scopeForm.mode === "selected"
    const cameraIds = selected ? [...scopeForm.cameraIds] : []
    const cameraGroupIds = selected
      ? [...scopeForm.groupIds]
      : []

    if (scopeOwnerType.value === "user") {
      await setUserCameraScope(scopeOwnerId.value, {
        mode: scopeForm.mode,
        camera_ids: cameraIds,
        camera_group_ids: cameraGroupIds
      })
    } else {
      if (scopeForm.mode === "inherit") {
        throw new Error(t("system.access.roleScopeNoInherit"))
      }
      await setRoleCameraScope(scopeOwnerId.value, {
        mode: scopeForm.mode,
        camera_ids: cameraIds,
        camera_group_ids: cameraGroupIds
      })
    }

    notice.value = t("system.access.cameraAccessUpdated", { owner: scopeOwnerLabel.value })
    closeEditor()
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    saving.value = false
  }
}

function formatResetExpiry(value: string): string {
  return new Intl.DateTimeFormat(locale.value, { dateStyle: "medium", timeStyle: "medium" }).format(new Date(value))
}

function directCameraCount(count: number): string {
  return t("system.access.directCameraCount", { count })
}

function permissionLabel(permission: string): string {
  const [, action = permission] = permission.split(".")
  return action.replaceAll("_", " ")
}

onMounted(() => {
  void refresh()
})
</script>

<template>
  <section class="access-control-panel">
    <header class="system-page-header">
      <div>
        <strong>{{ t("system.access.title") }}</strong>
        <span>
          {{ t("system.access.description") }}
        </span>
      </div>

      <div class="system-page-actions">
        <button
          class="button button--ghost"
          type="button"
          :disabled="loading"
          @click="refresh"
        >
          <UiIcon name="refresh" :size="14" />
          {{ t("system.access.refresh") }}
        </button>
        <button
          v-if="tab === 'users'"
          class="button button--primary"
          type="button"
          @click="openCreateUser"
        >
          <UiIcon name="plus" :size="14" />
          {{ t("system.access.addUser") }}
        </button>
        <button
          v-else-if="tab === 'roles'"
          class="button button--primary"
          type="button"
          @click="openCreateRole"
        >
          <UiIcon name="plus" :size="14" />
          {{ t("system.access.addRole") }}
        </button>
        <button
          v-else
          class="button button--primary"
          type="button"
          @click="openCreateOidc"
        >
          <UiIcon name="plus" :size="14" />
          {{ t("system.access.addOidc") }}
        </button>
      </div>
    </header>

    <div class="access-tabs">
      <button
        type="button"
        :class="{ 'access-tab--active': tab === 'users' }"
        @click="tab = 'users'"
      >
        {{ t("system.access.users") }}
        <span>{{ users.length }}</span>
      </button>
      <button
        type="button"
        :class="{ 'access-tab--active': tab === 'roles' }"
        @click="tab = 'roles'"
      >
        {{ t("system.access.roles") }}
        <span>{{ roles.length }}</span>
      </button>
      <button
        type="button"
        :class="{ 'access-tab--active': tab === 'oidc' }"
        @click="tab = 'oidc'"
      >
        OIDC
        <span>{{ oidcProviders.length }}</span>
      </button>
    </div>

    <div v-if="error" class="events-error">
      <UiIcon name="warning" :size="15" />
      <span>{{ error }}</span>
    </div>
    <div v-if="notice" class="storage-notice">
      <UiIcon name="check" :size="14" />
      <span>{{ notice }}</span>
    </div>

    <div v-if="tab === 'users'" class="system-table-wrap">
      <table class="system-table">
        <thead>
          <tr>
            <th>{{ t("system.access.user") }}</th>
            <th>{{ t("system.access.roles") }}</th>
            <th>{{ t("system.access.email") }}</th>
            <th>{{ t("system.access.status") }}</th>
            <th />
          </tr>
        </thead>
        <tbody>
          <tr v-for="user in users" :key="user.id">
            <td>
              <strong>{{ user.display_name }}</strong>
              <small>@{{ user.username }}</small>
            </td>
            <td>
              {{ user.roles.map((item) => item.name).join(", ") || t("system.access.noRoles") }}
            </td>
            <td>
              <template v-if="user.email">
                {{ user.email }}
                <small>
                  {{ user.email_verified ? t("system.access.verified") : t("system.access.unverified") }}
                </small>
              </template>
              <template v-else>—</template>
            </td>
            <td>
              <span
                class="status-pill"
                :class="user.enabled ? 'status-pill--ok' : 'status-pill--muted'"
              >
                {{ user.enabled ? t("system.access.enabled") : t("system.access.disabled") }}
              </span>
            </td>
            <td class="system-table__actions">
              <div class="access-row-actions">
                <button
                  class="button button--ghost button--compact"
                  type="button"
                  @click="openUserScope(user)"
                >
                  {{ t("system.access.cameras") }}
                </button>
                <button
                  class="button button--ghost button--compact"
                  type="button"
                  @click="openEditUser(user)"
                >
                  {{ t("system.access.edit") }}
                </button>
                <button
                  class="button button--ghost button--compact"
                  type="button"
                  @click="openPasswordReset(user)"
                >
                  {{ t("system.access.password") }}
                </button>
                <button
                  class="button button--ghost button--compact"
                  type="button"
                  @click="toggleUser(user)"
                >
                  {{ user.enabled ? t("system.access.disable") : t("system.access.enable") }}
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div
      v-else-if="tab === 'roles'"
      class="role-card-grid"
    >
      <article
        v-for="role in roles"
        :key="role.id"
        class="role-card"
      >
        <header>
          <div>
            <strong>{{ role.name }}</strong>
            <span>
              {{ role.description || t("system.access.noDescription") }}
            </span>
          </div>
          <span
            v-if="role.built_in"
            class="status-pill"
          >
            {{ t("system.access.builtin") }}
          </span>
        </header>

        <div class="role-card__permissions">
          <span
            v-for="permission in role.permissions"
            :key="permission"
          >
            {{ permission }}
          </span>
        </div>

        <footer>
          <button
            class="button button--ghost button--compact"
            type="button"
            @click="openRoleScope(role)"
          >
            {{ t("system.access.cameraScope") }}
          </button>
          <button
            v-if="!role.built_in"
            class="button button--ghost button--compact"
            type="button"
            @click="openEditRole(role)"
          >
            {{ t("system.access.editRole") }}
          </button>
        </footer>
      </article>
    </div>

    <div v-else class="system-table-wrap">
      <table class="system-table">
        <thead>
          <tr>
            <th>{{ t("system.access.provider") }}</th>
            <th>{{ t("system.access.issuer") }}</th>
            <th>{{ t("system.access.provisioning") }}</th>
            <th>{{ t("system.access.status") }}</th>
            <th />
          </tr>
        </thead>
        <tbody>
          <tr v-if="!oidcProviders.length">
            <td colspan="5">
              {{ t("system.oidc.empty") }}
            </td>
          </tr>
          <tr
            v-for="provider in oidcProviders"
            :key="provider.id"
          >
            <td>
              <strong>{{ provider.name }}</strong>
              <small>{{ provider.key }} · {{ provider.client_id }}</small>
            </td>
            <td>{{ provider.issuer }}</td>
            <td>
              {{
                provider.auto_provision
                  ? t("system.access.autoProvisionShort")
                  : provider.email_linking
                    ? t("system.access.verifiedEmailLinking")
                    : t("system.access.linkedIdentitiesOnly")
              }}
            </td>
            <td>
              <span
                class="status-pill"
                :class="
                  provider.enabled
                    ? 'status-pill--ok'
                    : 'status-pill--muted'
                "
              >
                {{ provider.enabled ? t("system.access.enabled") : t("system.access.disabled") }}
              </span>
            </td>
            <td class="system-table__actions">
              <div class="access-row-actions">
                <button
                  class="button button--ghost button--compact"
                  type="button"
                  @click="openEditOidc(provider)"
                >
                  {{ t("system.access.edit") }}
                </button>
                <button
                  class="button button--ghost button--compact"
                  type="button"
                  @click="removeOidc(provider)"
                >
                  {{ t("system.access.delete") }}
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <aside
      v-if="editorKind === 'user'"
      class="system-drawer"
    >
      <header class="storage-editor__header">
        <div>
          <strong>
            {{ editingUser ? t("system.access.editUser") : t("system.access.addUser") }}
          </strong>
          <span>
            {{
              editingUser
                ? t("system.access.rolesMetadata")
                : t("system.access.createLocalAccount")
            }}
          </span>
        </div>
        <button
          class="icon-button"
          type="button"
          @click="closeEditor"
        >
          <UiIcon name="close" :size="16" />
        </button>
      </header>

      <form class="storage-editor__form" @submit.prevent="saveUser">
        <label>
          <span>{{ t("system.access.username") }}</span>
          <input
            v-model="userForm.username"
            required
            :disabled="Boolean(editingUser)"
          />
        </label>
        <label>
          <span>{{ t("system.access.displayName") }}</span>
          <input v-model="userForm.displayName" required />
        </label>
        <label>
          <span>{{ t("system.access.email") }}</span>
          <input v-model="userForm.email" type="email" />
        </label>
        <label v-if="!editingUser">
          <span>{{ t("system.access.initialPassword") }}</span>
          <input
            v-model="userForm.password"
            type="password"
            minlength="12"
            maxlength="256"
            autocomplete="new-password"
            required
          />
        </label>

        <fieldset class="system-role-list">
          <legend>{{ t("system.access.roles") }}</legend>
          <label v-for="role in roles" :key="role.id">
            <input
              v-model="userForm.roleIds"
              type="checkbox"
              :value="role.id"
            />
            <span>
              <strong>{{ role.name }}</strong>
              <small>{{ role.description || t("system.access.noDescription") }}</small>
            </span>
          </label>
        </fieldset>

        <div class="storage-editor__actions">
          <button
            class="button button--ghost"
            type="button"
            @click="closeEditor"
          >
            {{ t("system.access.cancel") }}
          </button>
          <button
            class="button button--primary"
            type="submit"
            :disabled="saving"
          >
            {{
              saving
                ? t("system.access.saving")
                : editingUser
                  ? t("system.access.saveUser")
                  : t("system.access.createUser")
            }}
          </button>
        </div>
      </form>
    </aside>

    <aside
      v-if="editorKind === 'password' && editingUser"
      class="system-drawer"
    >
      <header class="storage-editor__header">
        <div>
          <strong>{{ t("system.access.issuePasswordReset") }}</strong>
          <span>
            {{ editingUser.display_name }} · @{{ editingUser.username }}
          </span>
        </div>
        <button
          class="icon-button"
          type="button"
          @click="closeEditor"
        >
          <UiIcon name="close" :size="16" />
        </button>
      </header>

      <div
        v-if="issuedReset"
        class="storage-editor__form"
      >
        <p class="access-warning">
          {{ t("system.access.resetShownOnce", { time: formatResetExpiry(issuedReset.expires_at) }) }}
        </p>
        <label>
          <span>{{ t("system.access.oneTimeResetToken") }}</span>
          <textarea
            :value="issuedReset.token"
            rows="4"
            readonly
            spellcheck="false"
          />
        </label>
        <div class="storage-editor__actions">
          <button
            class="button button--ghost"
            type="button"
            @click="copyIssuedReset"
          >
            {{ t("system.access.copyToken") }}
          </button>
          <button
            class="button button--primary"
            type="button"
            @click="closeEditor"
          >
            {{ t("system.access.done") }}
          </button>
        </div>
      </div>

      <form
        v-else
        class="storage-editor__form"
        @submit.prevent="savePasswordReset"
      >
        <p class="access-warning">
          {{ t("system.access.resetIssueHint") }}
        </p>
        <div class="storage-editor__actions">
          <button
            class="button button--ghost"
            type="button"
            @click="closeEditor"
          >
            {{ t("system.access.cancel") }}
          </button>
          <button
            class="button button--primary"
            type="submit"
            :disabled="saving"
          >
            {{ saving ? t("system.access.issuing") : t("system.access.issueResetToken") }}
          </button>
        </div>
      </form>
    </aside>

    <aside
      v-if="editorKind === 'oidc'"
      class="system-drawer"
    >
      <header class="storage-editor__header">
        <div>
          <strong>
            {{
              editingOidc
                ? t("system.access.editOidc")
                : t("system.access.addOidc")
            }}
          </strong>
          <span>
            {{ t("system.access.oidcIdentityProvider") }}
          </span>
        </div>
        <button
          class="icon-button"
          type="button"
          @click="closeEditor"
        >
          <UiIcon name="close" :size="16" />
        </button>
      </header>

      <form
        class="storage-editor__form"
        @submit.prevent="saveOidc"
      >
        <label>
          <span>{{ t("system.access.providerKey") }}</span>
          <input
            v-model="oidcForm.key"
            required
            maxlength="64"
            pattern="[a-z0-9][a-z0-9_-]{0,63}"
            :disabled="Boolean(editingOidc)"
            :placeholder="t('system.access.authentikKey')"
          />
          <small>
            {{ t("system.access.providerKeyHint") }}
          </small>
        </label>

        <label>
          <span>{{ t("system.access.displayName") }}</span>
          <input
            v-model="oidcForm.name"
            required
            maxlength="128"
            :placeholder="t('system.access.authentikName')"
          />
        </label>

        <label>
          <span>{{ t("system.access.issuerUrl") }}</span>
          <input
            v-model="oidcForm.issuer"
            required
            type="url"
            placeholder="https://id.example.com/application/o/zero-nvr/"
          />
          <small>
            {{ t("system.access.httpsHint") }}
          </small>
        </label>

        <label>
          <span>{{ t("system.access.clientId") }}</span>
          <input
            v-model="oidcForm.clientId"
            required
            autocomplete="off"
          />
        </label>

        <label>
          <span>{{ t("system.access.clientSecret") }}</span>
          <input
            v-model="oidcForm.clientSecret"
            type="password"
            :required="!editingOidc"
            autocomplete="new-password"
            :placeholder="
              editingOidc
                ? t('system.access.keepSecretPlaceholder')
                : ''
            "
          />
          <small>
            {{ t("system.access.encryptedHint") }}
          </small>
        </label>

        <label class="storage-check">
          <input
            v-model="oidcForm.enabled"
            type="checkbox"
          />
          <span>{{ t("system.access.providerEnabled") }}</span>
        </label>

        <label class="storage-check">
          <input
            v-model="oidcForm.emailLinking"
            type="checkbox"
          />
          <span>
            {{ t("system.access.linkByVerifiedEmail") }}
            <small>
              {{ t("system.access.emailVerifiedHint") }}
            </small>
          </span>
        </label>

        <label class="storage-check">
          <input
            v-model="oidcForm.autoProvision"
            type="checkbox"
          />
          <span>
            {{ t("system.access.autoProvision") }}
            <small>
              {{ t("system.access.autoProvisionHint") }}
            </small>
          </span>
        </label>

        <fieldset class="system-role-list">
          <legend>{{ t("system.access.defaultRoles") }}</legend>
          <label
            v-for="role in roles"
            :key="role.id"
          >
            <input
              v-model="oidcForm.defaultRoleIds"
              type="checkbox"
              :value="role.id"
            />
            <span>
              <strong>{{ role.name }}</strong>
              <small>
                {{ role.description || t("system.access.noDescription") }}
              </small>
            </span>
          </label>
        </fieldset>

        <div class="storage-editor__actions">
          <button
            class="button button--ghost"
            type="button"
            @click="closeEditor"
          >
            {{ t("system.access.cancel") }}
          </button>
          <button
            class="button button--primary"
            type="submit"
            :disabled="saving"
          >
            {{
              saving
                ? t("system.access.saving")
                : editingOidc
                  ? t("system.access.saveProvider")
                  : t("system.access.createProvider")
            }}
          </button>
        </div>
      </form>
    </aside>

    <aside
      v-if="editorKind === 'role'"
      class="system-drawer access-role-editor"
    >
      <header class="storage-editor__header">
        <div>
          <strong>
            {{ editingRole ? t("system.access.editRole") : t("system.access.addRole") }}
          </strong>
          <span>{{ t("system.access.permissionBundle") }}</span>
        </div>
        <button
          class="icon-button"
          type="button"
          @click="closeEditor"
        >
          <UiIcon name="close" :size="16" />
        </button>
      </header>

      <form class="access-role-form" @submit.prevent="saveRole">
        <label>
          <span>{{ t("system.access.name") }}</span>
          <input
            v-model="roleForm.name"
            required
            maxlength="64"
          />
        </label>
        <label>
          <span>{{ t("system.access.descriptionLabel") }}</span>
          <textarea
            v-model="roleForm.description"
            rows="3"
            maxlength="2048"
          />
        </label>

        <div class="permission-groups">
          <fieldset
            v-for="group in permissionGroups"
            :key="group.domain"
          >
            <legend>{{ group.domain }}</legend>
            <label
              v-for="permission in group.items"
              :key="permission"
            >
              <input
                v-model="roleForm.permissionIds"
                type="checkbox"
                :value="permission"
              />
              <span>
                <strong>{{ permissionLabel(permission) }}</strong>
                <small>{{ permission }}</small>
              </span>
            </label>
          </fieldset>
        </div>

        <div class="storage-editor__actions access-role-form__actions">
          <button
            class="button button--ghost"
            type="button"
            @click="closeEditor"
          >
            {{ t("system.access.cancel") }}
          </button>
          <button
            class="button button--primary"
            type="submit"
            :disabled="saving"
          >
            {{
              saving
                ? t("system.access.saving")
                : editingRole
                  ? t("system.access.saveRole")
                  : t("system.access.createRole")
            }}
          </button>
        </div>
      </form>
    </aside>

    <aside
      v-if="editorKind === 'scope'"
      class="system-drawer"
    >
      <header class="storage-editor__header">
        <div>
          <strong>{{ t("system.access.cameraAccess") }}</strong>
          <span>{{ scopeOwnerLabel }}</span>
        </div>
        <button
          class="icon-button"
          type="button"
          @click="closeEditor"
        >
          <UiIcon name="close" :size="16" />
        </button>
      </header>

      <form class="access-scope-form" @submit.prevent="saveScope">
        <label>
          <span>{{ t("system.access.scopeMode") }}</span>
          <select v-model="scopeForm.mode">
            <option
              v-if="scopeOwnerType === 'user'"
              value="inherit"
            >
              {{ t("system.access.inheritRoles") }}
            </option>
            <option value="all">{{ t("system.access.allCameras") }}</option>
            <option value="selected">{{ t("system.access.selectedCameras") }}</option>
            <option value="none">{{ t("system.access.noCameras") }}</option>
          </select>
        </label>

        <div
          v-if="scopeForm.mode === 'selected'"
          class="access-scope-selection"
        >
          <div v-if="cameraGroups.length" class="access-scope-group-list">
            <span class="access-scope-selection__label">
              {{ t("system.access.cameraGroups") }}
            </span>
            <button
              v-for="group in cameraGroups"
              :key="group.id"
              type="button"
              :class="{
                'access-group--selected':
                  scopeForm.groupIds.includes(group.id)
              }"
              @click="toggleScopeGroup(group.id)"
            >
              <UiIcon name="folder" :size="14" />
              <span>
                <strong>{{ group.name }}</strong>
                <small>{{ directCameraCount(group.camera_ids.length) }}</small>
              </span>
              <UiIcon
                v-if="scopeForm.groupIds.includes(group.id)"
                name="check"
                :size="14"
              />
            </button>
          </div>

          <span class="access-scope-selection__label">
            {{ t("system.access.individualCameras") }}
          </span>
          <div class="access-camera-list">
          <button
            v-for="camera in cameras"
            :key="camera.id"
            type="button"
            :class="{
              'access-camera--selected':
                scopeForm.cameraIds.includes(camera.id)
            }"
            @click="toggleScopeCamera(camera.id)"
          >
            <span
              class="live-camera-row__status"
              :class="{
                'live-camera-row__status--enabled': camera.enabled
              }"
            />
            <span>
              <strong>{{ camera.name }}</strong>
              <small>{{ camera.location || t("system.access.noLocation") }}</small>
            </span>
            <UiIcon
              v-if="scopeForm.cameraIds.includes(camera.id)"
              name="check"
              :size="14"
            />
          </button>
          </div>
        </div>

        <div class="storage-editor__actions">
          <button
            class="button button--ghost"
            type="button"
            @click="closeEditor"
          >
            {{ t("system.access.cancel") }}
          </button>
          <button
            class="button button--primary"
            type="submit"
            :disabled="
              saving ||
              (scopeForm.mode === 'selected' &&
                !scopeForm.cameraIds.length &&
                !scopeForm.groupIds.length)
            "
          >
            {{ saving ? t("system.access.saving") : t("system.access.saveAccess") }}
          </button>
        </div>
      </form>
    </aside>
  </section>
</template>

<style scoped>
.access-control-panel {
  display: grid;
  gap: 10px;
}

.access-tabs {
  display: flex;
  gap: 2px;
  border-bottom: 1px solid var(--border-subtle);
}

.access-tabs button {
  display: inline-flex;
  min-height: 34px;
  align-items: center;
  gap: 6px;
  padding: 0 10px;
  border: 0;
  border-bottom: 2px solid transparent;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 9px;
  font-weight: 600;
}

.access-tabs button > span {
  display: inline-grid;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  place-items: center;
  border-radius: 999px;
  background: var(--surface-subtle);
  font-size: 7px;
}

.access-tabs .access-tab--active {
  border-bottom-color: var(--accent);
  color: var(--text-primary);
}

.access-row-actions {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 3px;
}

.role-card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 8px;
}

.role-card {
  display: grid;
  gap: 10px;
  padding: 11px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--surface-raised);
}

.role-card > header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 9px;
}

.role-card > header strong,
.role-card > header div > span {
  display: block;
}

.role-card > header strong {
  font-size: 10px;
}

.role-card > header div > span {
  margin-top: 2px;
  color: var(--text-muted);
  font-size: 8px;
}

.role-card__permissions {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.role-card__permissions > span {
  padding: 3px 5px;
  border: 1px solid var(--border-subtle);
  border-radius: 4px;
  background: var(--surface-base);
  color: var(--text-muted);
  font-size: 7px;
}

.role-card > footer {
  display: flex;
  justify-content: flex-end;
  gap: 4px;
  padding-top: 8px;
  border-top: 1px solid var(--border-subtle);
}

.access-warning {
  margin: 0;
  padding: 8px 9px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: var(--surface-subtle);
  color: var(--text-muted);
  font-size: 8px;
  line-height: 1.45;
}

.access-role-form,
.access-scope-form {
  display: grid;
  gap: 11px;
  padding: 12px;
}

.access-role-form > label,
.access-scope-form > label {
  display: grid;
  gap: 5px;
}

.access-role-form label > span,
.access-scope-form label > span {
  color: var(--text-muted);
  font-size: 8px;
  font-weight: 650;
  text-transform: uppercase;
}

.access-role-form input:not([type="checkbox"]),
.access-role-form textarea,
.access-scope-form select {
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

.access-role-form textarea {
  min-height: 70px;
  padding-block: 7px;
  resize: vertical;
}

.permission-groups {
  display: grid;
  gap: 7px;
}

.permission-groups fieldset {
  display: grid;
  gap: 4px;
  margin: 0;
  padding: 8px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
}

.permission-groups legend {
  padding: 0 5px;
  color: var(--text-muted);
  font-size: 8px;
  font-weight: 650;
  text-transform: uppercase;
}

.permission-groups label {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  padding: 4px;
  border-radius: 4px;
}

.permission-groups label:hover {
  background: var(--surface-hover);
}

.permission-groups input {
  width: 13px;
  height: 13px;
  margin-top: 1px;
  accent-color: var(--accent);
}

.permission-groups label span strong,
.permission-groups label span small {
  display: block;
}

.permission-groups label span strong {
  color: var(--text-secondary);
  font-size: 8px;
  font-weight: 600;
  text-transform: capitalize;
}

.permission-groups label span small {
  margin-top: 1px;
  color: var(--text-muted);
  font-size: 7px;
}

.access-role-form__actions {
  position: sticky;
  bottom: 0;
  padding: 9px 0 0;
  background: var(--surface-raised);
}

.access-scope-selection {
  display: grid;
  gap: 9px;
}

.access-scope-selection__label {
  color: var(--text-muted);
  font-size: 8px;
  font-weight: 650;
  text-transform: uppercase;
}

.access-scope-group-list,
.access-camera-list {
  display: grid;
  gap: 5px;
}

.access-scope-group-list button {
  display: grid;
  min-height: 44px;
  grid-template-columns: 24px minmax(0, 1fr) 18px;
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

.access-scope-group-list .access-group--selected {
  border-color: var(--accent);
  box-shadow: 0 0 0 1px var(--accent);
}

.access-scope-group-list strong,
.access-scope-group-list small {
  display: block;
}

.access-scope-group-list strong {
  font-size: 9px;
}

.access-scope-group-list small {
  margin-top: 2px;
  color: var(--text-muted);
  font-size: 7px;
}

.access-camera-list button {
  display: grid;
  min-height: 48px;
  grid-template-columns: 8px minmax(0, 1fr) 18px;
  align-items: center;
  gap: 7px;
  padding: 6px 8px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: var(--surface-base);
  color: var(--text-primary);
  cursor: pointer;
  text-align: left;
}

.access-camera-list button:hover {
  border-color: var(--border-strong);
}

.access-camera-list .access-camera--selected {
  border-color: var(--accent);
  box-shadow: 0 0 0 1px var(--accent);
}

.access-camera-list button span strong,
.access-camera-list button span small {
  display: block;
}

.access-camera-list button span strong {
  font-size: 9px;
}

.access-camera-list button span small {
  margin-top: 2px;
  color: var(--text-muted);
  font-size: 7px;
}

@media (max-width: 700px) {
  .access-row-actions {
    flex-wrap: wrap;
  }
}
</style>
