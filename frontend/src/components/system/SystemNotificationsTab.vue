<script setup lang="ts">
/**
 * Notification tab: the delivery-target cards, the recent-deliveries table and
 * the target editor drawer.
 *
 * Extracted from `SystemView`. Every class it uses is defined globally, so no
 * stylesheet change was needed. The editor drawer lives here because it is part
 * of this tab's markup; it uses the shared `system-drawer` positioning class.
 *
 * The view owns the target list, the form and the panel flag because it seeds
 * them from the API and refetches after a save, so they are passed in and all
 * mutations come back as events — including closing the panel, which used to be
 * an inline assignment in the template.
 */
import { useI18n } from "vue-i18n"

import {
  type NotificationDelivery,
  type NotificationTarget
} from "../../api/system"
import { useSystemFormatters } from "../../composables/useSystemFormatters"
import StatusPill from "../ui/StatusPill.vue"
import UiIcon from "../ui/UiIcon.vue"

export interface NotificationForm {
  name: string
  url: string
  passwordReset: boolean
}

defineProps<{
  targets: NotificationTarget[]
  deliveries: NotificationDelivery[]
  notificationForm: NotificationForm
  notificationPanelOpen: boolean
  editingNotification: NotificationTarget | null
  notificationSaving: boolean
  testingNotificationId: string | null
  /** Whether the operator may manage notification targets. */
  canManage: boolean
}>()

const emit = defineEmits<{
  openPanel: []
  closePanel: []
  editTarget: [target: NotificationTarget]
  removeTarget: [target: NotificationTarget]
  testTarget: [target: NotificationTarget]
  toggleTarget: [target: NotificationTarget]
  save: []
}>()

const { t } = useI18n({ useScope: "global" })
const { formatTime, pretty, stateLabel, statusVariant } = useSystemFormatters()
</script>

<template>
          <header class="system-page-header">
            <div>
              <strong>{{ t("system.main.notifications") }}</strong>
              <span>{{ t("system.main.notificationsDesc") }}</span>
            </div>
            <button
              v-if="canManage"
              class="button button--primary"
              type="button"
              @click="emit('openPanel')"
            >
              <UiIcon name="plus" :size="14" />
              {{ t("system.main.addTarget") }}
            </button>
          </header>

          <div class="notification-grid">
            <article
              v-for="item in targets"
              :key="item.id"
              class="notification-card"
            >
              <div class="notification-card__icon">
                <UiIcon name="bell" :size="19" />
              </div>
              <div class="notification-card__main">
                <strong>{{ item.name }}</strong>
                <span>
                  {{ item.url_configured ? t("system.main.destinationConfigured") : t("system.main.destinationMissing") }}
                  <template v-if="item.config.password_reset === true">
                    {{ t("system.main.passwordResetEmail") }}
                  </template>
                </span>
              </div>
              <StatusPill :variant="item.enabled ? 'ok' : 'muted'">
                {{ item.enabled ? t("system.main.enabled") : t("system.main.disabled") }}
              </StatusPill>
              <div
                v-if="canManage"
                class="notification-card__actions"
              >
                <button
                  class="button button--ghost button--compact"
                  type="button"
                  :disabled="testingNotificationId === item.id"
                  @click="emit('testTarget', item)"
                >
                  {{ testingNotificationId === item.id ? t("system.main.testing") : t("system.main.test") }}
                </button>
                <button
                  class="icon-button"
                  type="button"
                  :title="t('system.main.editNotification')"
                  @click="emit('editTarget', item)"
                >
                  <UiIcon name="system" :size="14" />
                </button>
                <button class="icon-button" type="button" @click="emit('toggleTarget', item)">
                  <UiIcon :name="item.enabled ? 'pause' : 'play'" :size="14" />
                </button>
                <button class="icon-button icon-button--danger" type="button" @click="emit('removeTarget', item)">
                  <UiIcon name="trash" :size="14" />
                </button>
              </div>
            </article>
          </div>

          <div class="system-section">
            <div class="system-section__heading">
              <strong>{{ t("system.main.recentDeliveries") }}</strong>
              <span>{{ t("system.main.recentDeliveriesHint") }}</span>
            </div>
            <div class="system-table-wrap">
              <table class="system-table">
                <thead>
                  <tr>
                    <th>{{ t("system.main.message") }}</th>
                    <th>{{ t("system.main.purpose") }}</th>
                    <th>{{ t("system.main.status") }}</th>
                    <th>{{ t("system.main.attempts") }}</th>
                    <th>{{ t("system.main.sent") }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="item in deliveries" :key="item.id">
                    <td>
                      <strong>{{ item.title }}</strong>
                      <small>{{ item.last_error_code || item.body }}</small>
                    </td>
                    <td>{{ pretty(item.purpose) }}</td>
                    <td>
                      <StatusPill :variant="statusVariant(item.state)">
                        {{ stateLabel(item.state) }}
                      </StatusPill>
                    </td>
                    <td>{{ item.attempt_count }}</td>
                    <td>{{ formatTime(item.sent_at || item.last_attempt_at) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <aside
            v-if="
              notificationPanelOpen &&
              canManage
            "
            class="system-drawer"
          >
            <header class="storage-editor__header">
              <div>
                <strong>
                  {{
                    editingNotification
                      ? t("system.main.editNotification")
                      : t("system.main.addNotification")
                  }}
                </strong>
                <span>{{ t("system.main.appriseCompatible") }}</span>
              </div>
              <button class="icon-button" type="button" @click="emit('closePanel')">
                <UiIcon name="close" :size="16" />
              </button>
            </header>
            <form class="storage-editor__form" @submit.prevent="emit('save')">
              <label>
                <span>{{ t("system.main.name") }}</span>
                <input v-model="notificationForm.name" required />
              </label>
              <label>
                <span>{{ t("system.main.appriseUrl") }}</span>
                <textarea
                  v-model="notificationForm.url"
                  rows="7"
                  :required="!editingNotification"
                  spellcheck="false"
                  :placeholder="
                    editingNotification
                      ? t('system.main.leaveDestination')
                      : 'mailto://user:pass@smtp.example.com?to=alerts@example.com'
                  "
                />
                <small>
                  {{
                    editingNotification
                      ? t("system.main.leaveEncryptedUrl")
                      : t("system.main.encryptedNeverReturned")
                  }}
                </small>
              </label>
              <label class="storage-check">
                <input
                  v-model="notificationForm.passwordReset"
                  type="checkbox"
                />
                <span>
                  {{ t("system.main.passwordResetTarget") }}
                  <small>
                    {{ t("system.main.passwordResetHint") }}
                  </small>
                </span>
              </label>
              <div class="storage-editor__actions">
                <button class="button button--ghost" type="button" @click="emit('closePanel')">
                  {{ t("system.main.cancel") }}
                </button>
                <button class="button button--primary" type="submit" :disabled="notificationSaving">
                  {{
                    notificationSaving
                      ? t("system.main.saving")
                      : editingNotification
                        ? t("system.main.saveTarget")
                        : t("system.main.createTarget")
                  }}
                </button>
              </div>
            </form>
          </aside>
</template>
