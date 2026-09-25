<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue"
import { useI18n } from "vue-i18n"

import { errorMessage } from "../../api/client"
import {
  createOidcProvider,
  deleteOidcProvider,
  listOidcProviders,
  listRoles,
  updateOidcProvider,
  type OidcProvider,
  type Role
} from "../../api/system"
import UiIcon from "../ui/UiIcon.vue"

const { t } = useI18n({ useScope: "global" })

const providers = ref<OidcProvider[]>([])
const roles = ref<Role[]>([])
const loading = ref(false)
const saving = ref(false)
const editorOpen = ref(false)
const editing = ref<OidcProvider | null>(null)
const error = ref<string | null>(null)
const notice = ref<string | null>(null)

const form = reactive({
  key: "",
  name: "",
  enabled: true,
  issuer: "",
  clientId: "",
  clientSecret: "",
  autoProvision: false,
  emailLinking: false,
  defaultRoleIds: [] as string[]
})

const callbackUrl = computed(() => {
  const key = editing.value?.key || form.key.trim().toLowerCase()
  if (!key) return ""
  return (
    window.location.origin +
    "/api/v1/auth/oidc/" +
    encodeURIComponent(key) +
    "/callback"
  )
})

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    ;[providers.value, roles.value] = await Promise.all([
      listOidcProviders(),
      listRoles()
    ])
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    loading.value = false
  }
}

function openCreate(): void {
  editing.value = null
  form.key = ""
  form.name = ""
  form.enabled = true
  form.issuer = ""
  form.clientId = ""
  form.clientSecret = ""
  form.autoProvision = false
  form.emailLinking = false
  form.defaultRoleIds = []
  error.value = null
  notice.value = null
  editorOpen.value = true
}

function openEdit(item: OidcProvider): void {
  editing.value = item
  form.key = item.key
  form.name = item.name
  form.enabled = item.enabled
  form.issuer = item.issuer
  form.clientId = item.client_id
  form.clientSecret = ""
  form.autoProvision = item.auto_provision
  form.emailLinking = item.email_linking
  form.defaultRoleIds = [...item.default_role_ids]
  error.value = null
  notice.value = null
  editorOpen.value = true
}

async function save(): Promise<void> {
  saving.value = true
  error.value = null
  try {
    if (editing.value) {
      const changes: {
        name: string
        enabled: boolean
        issuer: string
        client_id: string
        auto_provision: boolean
        email_linking: boolean
        default_role_ids: string[]
        client_secret_action: "keep" | "replace"
        client_secret?: string
      } = {
        name: form.name.trim(),
        enabled: form.enabled,
        issuer: form.issuer.trim(),
        client_id: form.clientId.trim(),
        auto_provision: form.autoProvision,
        email_linking: form.emailLinking,
        default_role_ids: [...form.defaultRoleIds],
        client_secret_action: (
          form.clientSecret
            ? "replace"
            : "keep"
        )
      }
      if (form.clientSecret) {
        changes.client_secret = form.clientSecret
      }
      await updateOidcProvider(editing.value.key, changes)
      notice.value = t("system.oidc.updated", { name: form.name.trim() })
    } else {
      await createOidcProvider({
        key: form.key.trim().toLowerCase(),
        name: form.name.trim(),
        enabled: form.enabled,
        issuer: form.issuer.trim(),
        client_id: form.clientId.trim(),
        client_secret: form.clientSecret,
        auto_provision: form.autoProvision,
        email_linking: form.emailLinking,
        default_role_ids: [...form.defaultRoleIds]
      })
      notice.value = t("system.oidc.created", { name: form.name.trim() })
    }
    form.clientSecret = ""
    editorOpen.value = false
    editing.value = null
    await load()
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    saving.value = false
  }
}

async function remove(item: OidcProvider): Promise<void> {
  if (
    !window.confirm(
      t("system.oidc.deleteConfirm", { name: item.name })
    )
  ) {
    return
  }

  error.value = null
  try {
    await deleteOidcProvider(item.key)
    notice.value = t("system.oidc.deleted", { name: item.name })
    await load()
  } catch (caught) {
    error.value = errorMessage(caught)
  }
}

onMounted(() => {
  void load()
})
</script>

<template>
  <section class="oidc-panel">
    <header class="system-page-header">
      <div>
        <strong>{{ t("system.oidc.title") }}</strong>
        <span>
          {{ t("system.oidc.description") }}
        </span>
      </div>
      <button
        class="button button--primary"
        type="button"
        @click="openCreate"
      >
        <UiIcon name="plus" :size="14" />
        {{ t("system.oidc.addProvider") }}
      </button>
    </header>

    <div v-if="error" class="events-error">
      <UiIcon name="warning" :size="15" />
      <span>{{ error }}</span>
    </div>
    <div v-if="notice" class="storage-notice">
      <UiIcon name="check" :size="14" />
      <span>{{ notice }}</span>
    </div>

    <div v-if="loading" class="empty-state">
      {{ t("system.oidc.loading") }}
    </div>

    <div v-else-if="!providers.length" class="empty-state empty-state--large">
      <strong>{{ t("system.oidc.empty") }}</strong>
      <p>
        {{ t("system.oidc.emptyHint") }}
      </p>
    </div>

    <div v-else class="oidc-provider-grid">
      <article
        v-for="item in providers"
        :key="item.id"
        class="oidc-provider-card"
      >
        <div class="oidc-provider-card__main">
          <div>
            <strong>{{ item.name }}</strong>
            <span>{{ item.issuer }}</span>
          </div>
          <span
            class="status-pill"
            :class="
              item.enabled
                ? 'status-pill--ok'
                : 'status-pill--muted'
            "
          >
            {{ item.enabled ? t("system.oidc.enabled") : t("system.oidc.disabled") }}
          </span>
        </div>

        <dl>
          <div>
            <dt>{{ t("system.oidc.key") }}</dt>
            <dd>{{ item.key }}</dd>
          </div>
          <div>
            <dt>{{ t("system.oidc.client") }}</dt>
            <dd>{{ item.client_id }}</dd>
          </div>
          <div>
            <dt>{{ t("system.oidc.provisioning") }}</dt>
            <dd>
              {{
                item.auto_provision
                  ? t("system.oidc.defaultRoleCount", { count: item.default_role_ids.length })
                  : t("system.oidc.linkExistingOnly")
              }}
            </dd>
          </div>
          <div>
            <dt>{{ t("system.oidc.emailLinking") }}</dt>
            <dd>{{ item.email_linking ? t("system.oidc.verifiedEmailAllowed") : t("system.oidc.off") }}</dd>
          </div>
        </dl>

        <footer>
          <button
            class="button button--ghost button--compact"
            type="button"
            @click="openEdit(item)"
          >
            {{ t("system.oidc.edit") }}
          </button>
          <button
            class="button button--ghost button--compact"
            type="button"
            @click="remove(item)"
          >
            {{ t("system.oidc.delete") }}
          </button>
        </footer>
      </article>
    </div>

    <aside v-if="editorOpen" class="system-drawer">
      <header class="storage-editor__header">
        <div>
          <strong>
            {{ editing ? t("system.oidc.editTitle") : t("system.oidc.addTitle") }}
          </strong>
          <span>{{ t("system.oidc.discovery") }}</span>
        </div>
        <button
          class="icon-button"
          type="button"
          @click="editorOpen = false"
        >
          <UiIcon name="close" :size="16" />
        </button>
      </header>

      <form
        class="storage-editor__form"
        @submit.prevent="save"
      >
        <label>
          <span>{{ t("system.oidc.providerKey") }}</span>
          <input
            v-model="form.key"
            required
            maxlength="64"
            pattern="[a-z0-9][a-z0-9_-]{0,63}"
            :disabled="Boolean(editing)"
            :placeholder="t('system.oidc.authentikKey')"
          />
          <small>
            {{ t("system.oidc.providerKeyHint") }}
          </small>
        </label>

        <label>
          <span>{{ t("system.oidc.displayName") }}</span>
          <input
            v-model="form.name"
            required
            maxlength="128"
            :placeholder="t('system.oidc.authentikName')"
          />
        </label>

        <label>
          <span>{{ t("system.oidc.issuerUrl") }}</span>
          <input
            v-model="form.issuer"
            required
            type="url"
            placeholder="https://id.example.com/application/o/zero-nvr/"
          />
          <small>
            {{ t("system.oidc.httpsHint") }}
          </small>
        </label>

        <label>
          <span>{{ t("system.oidc.clientId") }}</span>
          <input
            v-model="form.clientId"
            required
            autocomplete="off"
          />
        </label>

        <label>
          <span>{{ t("system.oidc.clientSecret") }}</span>
          <input
            v-model="form.clientSecret"
            type="password"
            :required="!editing"
            autocomplete="new-password"
          />
          <small>
            {{
              editing
                ? t("system.oidc.keepSecretHint")
                : t("system.oidc.encryptedSecretHint")
            }}
          </small>
        </label>

        <label v-if="callbackUrl">
          <span>{{ t("system.oidc.callbackUrl") }}</span>
          <input
            :value="callbackUrl"
            readonly
          />
          <small>
            {{ t("system.oidc.callbackHint") }}
          </small>
        </label>

        <label class="storage-check">
          <input
            v-model="form.enabled"
            type="checkbox"
          />
          <span>{{ t("system.oidc.providerEnabled") }}</span>
        </label>

        <label class="storage-check">
          <input
            v-model="form.emailLinking"
            type="checkbox"
          />
          <span>
            {{ t("system.oidc.allowEmailLinking") }}
            <small>
              {{ t("system.oidc.emailLinkingHint") }}
            </small>
          </span>
        </label>

        <label class="storage-check">
          <input
            v-model="form.autoProvision"
            type="checkbox"
          />
          <span>
            {{ t("system.oidc.autoProvision") }}
            <small>
              {{ t("system.oidc.autoProvisionHint") }}
            </small>
          </span>
        </label>

        <fieldset class="system-role-list">
          <legend>{{ t("system.oidc.defaultRoles") }}</legend>
          <label
            v-for="role in roles"
            :key="role.id"
          >
            <input
              v-model="form.defaultRoleIds"
              type="checkbox"
              :value="role.id"
            />
            <span>
              <strong>{{ role.name }}</strong>
              <small>{{ role.description || t("system.oidc.noDescription") }}</small>
            </span>
          </label>
        </fieldset>

        <div class="storage-editor__actions">
          <button
            class="button button--ghost"
            type="button"
            @click="editorOpen = false"
          >
            {{ t("system.oidc.cancel") }}
          </button>
          <button
            class="button button--primary"
            type="submit"
            :disabled="saving"
          >
            {{
              saving
                ? t("system.oidc.saving")
                : editing
                  ? t("system.oidc.saveProvider")
                  : t("system.oidc.createProvider")
            }}
          </button>
        </div>
      </form>
    </aside>
  </section>
</template>

<style scoped>
.oidc-panel {
  display: grid;
  gap: 12px;
}

.oidc-provider-grid {
  display: grid;
  gap: 8px;
}

.oidc-provider-card {
  display: grid;
  gap: 10px;
  padding: 11px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--surface-raised);
}

.oidc-provider-card__main,
.oidc-provider-card footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.oidc-provider-card__main > div > strong,
.oidc-provider-card__main > div > span {
  display: block;
}

.oidc-provider-card__main > div > strong {
  font-size: 10px;
}

.oidc-provider-card__main > div > span {
  margin-top: 2px;
  color: var(--text-muted);
  font-size: 8px;
}

.oidc-provider-card dl {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 6px;
  margin: 0;
}

.oidc-provider-card dl > div {
  min-width: 0;
  padding: 7px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: var(--surface-base);
}

.oidc-provider-card dt {
  color: var(--text-muted);
  font-size: 7px;
}

.oidc-provider-card dd {
  overflow: hidden;
  margin: 3px 0 0;
  color: var(--text-secondary);
  font-size: 8px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.oidc-provider-card footer {
  justify-content: flex-end;
}

@media (max-width: 900px) {
  .oidc-provider-card dl {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
