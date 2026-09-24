<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue"
import { useI18n } from "vue-i18n"

import {
  listSessions,
  revokeSession,
  type SessionSummary
} from "../../api/auth"
import { errorMessage } from "../../api/client"
import { useAuthStore } from "../../stores/auth"
import UiIcon from "../ui/UiIcon.vue"

const emit = defineEmits<{
  close: []
}>()

const auth = useAuthStore()
const { locale, t } = useI18n({ useScope: "global" })
const sessions = ref<SessionSummary[]>([])
const loading = ref(false)
const savingPassword = ref(false)
const revokingId = ref<string | null>(null)
const error = ref<string | null>(null)
const notice = ref<string | null>(null)

const passwordForm = reactive({
  currentPassword: "",
  newPassword: "",
  confirmPassword: ""
})

const otherSessions = computed(() =>
  sessions.value.filter((item) => !item.current)
)

function formatTime(value: string): string {
  return new Intl.DateTimeFormat(locale.value, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  }).format(new Date(value))
}

function sourceIp(item: SessionSummary): string {
  const value = item.client_info?.source_ip
  return typeof value === "string" && value ? value : t("account.unknownIp")
}

function userAgent(item: SessionSummary): string {
  const value = item.client_info?.user_agent
  return typeof value === "string" && value
    ? value
    : t("account.unknownClient")
}

async function refreshSessions(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    sessions.value = await listSessions()
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    loading.value = false
  }
}

async function changePassword(): Promise<void> {
  if (
    passwordForm.newPassword !==
    passwordForm.confirmPassword
  ) {
    error.value = t("account.passwordMismatch")
    return
  }

  savingPassword.value = true
  error.value = null
  notice.value = null
  try {
    await auth.changePassword({
      current_password: passwordForm.currentPassword,
      new_password: passwordForm.newPassword
    })
    passwordForm.currentPassword = ""
    passwordForm.newPassword = ""
    passwordForm.confirmPassword = ""
    notice.value = t("account.passwordChanged")
    await refreshSessions()
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    savingPassword.value = false
  }
}

async function revoke(item: SessionSummary): Promise<void> {
  if (item.current) return
  revokingId.value = item.id
  error.value = null
  notice.value = null
  try {
    await revokeSession(item.id)
    sessions.value = sessions.value.filter(
      (current) => current.id !== item.id
    )
    notice.value = t("account.sessionRevoked")
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    revokingId.value = null
  }
}

onMounted(() => {
  void refreshSessions()
})
</script>

<template>
  <aside class="account-panel">
    <header class="account-panel__header">
      <div class="account-panel__identity">
        <span class="user-avatar account-panel__avatar">
          {{
            (
              auth.user?.display_name ||
              auth.user?.username ||
              "Z"
            ).trim().charAt(0).toUpperCase()
          }}
        </span>
        <div>
          <strong>{{ auth.user?.display_name }}</strong>
          <span>@{{ auth.user?.username }}</span>
        </div>
      </div>

      <button
        class="icon-button"
        type="button"
        :title="t('account.close')"
        :aria-label="t('account.close')"
        @click="emit('close')"
      >
        <UiIcon name="close" :size="16" />
      </button>
    </header>

    <div v-if="error" class="account-panel__message account-panel__message--error">
      {{ error }}
    </div>
    <div v-if="notice" class="account-panel__message account-panel__message--ok">
      {{ notice }}
    </div>

    <section class="account-panel__section">
      <div class="account-panel__section-heading">
        <div>
          <strong>{{ t("account.changePassword") }}</strong>
          <span>
            {{ t("account.changePasswordDescription") }}
          </span>
        </div>
      </div>

      <form
        class="account-password-form"
        @submit.prevent="changePassword"
      >
        <label>
          <span>{{ t("account.currentPassword") }}</span>
          <input
            v-model="passwordForm.currentPassword"
            type="password"
            autocomplete="current-password"
            required
          />
        </label>
        <label>
          <span>{{ t("account.newPassword") }}</span>
          <input
            v-model="passwordForm.newPassword"
            type="password"
            minlength="12"
            maxlength="256"
            autocomplete="new-password"
            required
          />
        </label>
        <label>
          <span>{{ t("account.confirmNewPassword") }}</span>
          <input
            v-model="passwordForm.confirmPassword"
            type="password"
            minlength="12"
            maxlength="256"
            autocomplete="new-password"
            required
          />
        </label>

        <div class="account-panel__actions">
          <button
            class="button button--primary"
            type="submit"
            :disabled="savingPassword"
          >
            {{
              savingPassword
                ? t("account.changing")
                : t("account.changePassword")
            }}
          </button>
        </div>
      </form>
    </section>

    <section class="account-panel__section">
      <div class="account-panel__section-heading account-panel__section-heading--row">
        <div>
          <strong>{{ t("account.activeSessions") }}</strong>
          <span>
            {{ t("account.activeSessionsDescription") }}
          </span>
        </div>
        <button
          class="button button--ghost button--compact"
          type="button"
          :disabled="loading"
          @click="refreshSessions"
        >
          <UiIcon name="refresh" :size="13" />
          {{ t("account.refresh") }}
        </button>
      </div>

      <div v-if="loading && !sessions.length" class="account-sessions-empty">
        {{ t("account.loadingSessions") }}
      </div>

      <div v-else class="account-session-list">
        <article
          v-for="item in sessions"
          :key="item.id"
          class="account-session"
        >
          <span class="account-session__icon">
            <UiIcon name="system" :size="15" />
          </span>

          <div class="account-session__main">
            <div>
              <strong>
                {{ item.current ? t("account.thisBrowser") : sourceIp(item) }}
              </strong>
              <span
                v-if="item.current"
                class="status-pill status-pill--ok"
              >
                {{ t("account.current") }}
              </span>
            </div>
            <span>{{ userAgent(item) }}</span>
            <small>
              {{ t("account.lastActive", {
                last: formatTime(item.last_seen_at),
                expires: formatTime(item.expires_at)
              }) }}
            </small>
          </div>

          <button
            v-if="!item.current"
            class="button button--ghost button--compact"
            type="button"
            :disabled="revokingId === item.id"
            @click="revoke(item)"
          >
            {{
              revokingId === item.id
                ? t("account.revoking")
                : t("account.revoke")
            }}
          </button>
        </article>
      </div>

      <p
        v-if="!loading && !otherSessions.length"
        class="account-panel__hint"
      >
        {{ t("account.noOtherSessions") }}
      </p>
    </section>
  </aside>
</template>

<style scoped>
.account-panel {
  position: fixed;
  top: var(--topbar-height);
  right: 0;
  bottom: 0;
  z-index: 50;
  width: min(420px, 96vw);
  overflow-y: auto;
  border-left: 1px solid var(--border-subtle);
  background: var(--surface-raised);
  box-shadow: -18px 0 48px rgba(0, 0, 0, 0.18);
}

.account-panel__header {
  position: sticky;
  top: 0;
  z-index: 2;
  display: flex;
  min-height: 64px;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 0 11px 0 14px;
  border-bottom: 1px solid var(--border-subtle);
  background: var(--surface-raised);
}

.account-panel__identity {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 9px;
}

.account-panel__avatar {
  width: 32px;
  height: 32px;
  flex: 0 0 32px;
}

.account-panel__identity strong,
.account-panel__identity div > span {
  display: block;
}

.account-panel__identity strong {
  font-size: 11px;
}

.account-panel__identity div > span {
  margin-top: 2px;
  color: var(--text-muted);
  font-size: 8px;
}

.account-panel__message {
  margin: 10px 12px 0;
  padding: 8px 9px;
  border-radius: var(--radius-sm);
  font-size: 8px;
}

.account-panel__message--error {
  background: var(--danger-soft);
  color: var(--danger);
}

.account-panel__message--ok {
  background: var(--success-soft);
  color: var(--success);
}

.account-panel__section {
  padding: 14px;
  border-bottom: 1px solid var(--border-subtle);
}

.account-panel__section-heading {
  margin-bottom: 10px;
}

.account-panel__section-heading--row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.account-panel__section-heading strong,
.account-panel__section-heading span {
  display: block;
}

.account-panel__section-heading strong {
  font-size: 10px;
}

.account-panel__section-heading span {
  max-width: 310px;
  margin-top: 2px;
  color: var(--text-muted);
  font-size: 8px;
  line-height: 1.4;
}

.account-password-form {
  display: grid;
  gap: 9px;
}

.account-password-form label {
  display: grid;
  gap: 5px;
}

.account-password-form label > span {
  color: var(--text-muted);
  font-size: 8px;
  font-weight: 650;
  text-transform: uppercase;
}

.account-password-form input {
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

.account-password-form input:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--focus-ring);
}

.account-panel__actions {
  display: flex;
  justify-content: flex-end;
}

.account-session-list {
  display: grid;
  gap: 6px;
}

.account-session {
  display: grid;
  grid-template-columns: 30px minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  min-height: 66px;
  padding: 7px 8px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: var(--surface-base);
}

.account-session__icon {
  display: grid;
  width: 28px;
  height: 28px;
  border-radius: var(--radius-sm);
  background: var(--surface-subtle);
  color: var(--text-muted);
  place-items: center;
}

.account-session__main {
  min-width: 0;
}

.account-session__main > div {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 6px;
}

.account-session__main strong,
.account-session__main > span,
.account-session__main small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.account-session__main strong {
  font-size: 9px;
}

.account-session__main > span {
  margin-top: 3px;
  color: var(--text-secondary);
  font-size: 7px;
}

.account-session__main small {
  margin-top: 2px;
  color: var(--text-muted);
  font-size: 7px;
}

.account-sessions-empty,
.account-panel__hint {
  color: var(--text-muted);
  font-size: 8px;
}

.account-sessions-empty {
  padding: 20px 0;
  text-align: center;
}

.account-panel__hint {
  margin: 8px 0 0;
}

@media (max-width: 540px) {
  .account-session {
    grid-template-columns: 30px minmax(0, 1fr);
  }

  .account-session > .button {
    grid-column: 1 / -1;
    justify-self: end;
  }
}
</style>
