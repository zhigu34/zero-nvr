<script setup lang="ts">
/**
 * Backup tab: disaster-recovery commands, the configuration-import preflight,
 * the backup policies, the run history and the policy editor drawer.
 *
 * Extracted from `SystemView` together with the three `backup-recovery-card*`
 * rules that were scoped to the view — they style elements that moved here, so
 * they had to travel with the markup.
 *
 * The tab owns the hidden file input as well: it used to be rendered here while
 * its template ref lived in the view, which meant the "validate import" button
 * reached across components to click it. Keeping input and trigger together
 * removes that coupling; the tab now hands the parent a `File`.
 *
 * `backupPolicyName` and `latestBackupByPolicy` also moved in, because both are
 * pure lookups over props the tab already receives.
 */
import { computed, ref } from "vue"
import { useI18n } from "vue-i18n"

import {
  type BackupPolicy,
  type BackupSet,
  type ConfigurationImportApplyResult,
  type ConfigurationImportValidation,
  type SystemSettings
} from "../../api/system"
import { useSystemFormatters } from "../../composables/useSystemFormatters"
import { formatBytes } from "../../utils/format"
import StatusPill from "../ui/StatusPill.vue"
import UiIcon from "../ui/UiIcon.vue"
import SystemRecoveryKitPanel from "./SystemRecoveryKitPanel.vue"

export interface BackupForm {
  name: string
  repository: string
  password: string
  environmentCredentials: string
  initializeIfMissing: boolean
  scheduled: boolean
  cron: string
  keepLast: number
  keepDaily: number
  keepWeekly: number
  keepMonthly: number
  verifyAfter: boolean
  includeDeploymentConfig: boolean
  enabled: boolean
}

const props = defineProps<{
  backupPolicies: BackupPolicy[]
  backups: BackupSet[]
  settings: SystemSettings | null
  backupForm: BackupForm
  backupPanelOpen: boolean
  editingBackupPolicy: BackupPolicy | null
  backupSaving: boolean
  backupRefreshing: boolean
  runningBackupId: string | null
  verifyingBackupId: string | null
  configImportValidation: ConfigurationImportValidation | null
  configImportFileName: string | null
  configImportValidating: boolean
  configImportApplying: boolean
  configImportApplyResult: ConfigurationImportApplyResult | null
  configImportBundle: Record<string, unknown> | null
  /** Whether the operator may change backup settings. */
  canManage: boolean
}>()

const emit = defineEmits<{
  refresh: []
  openPanel: []
  editPolicy: [policy: BackupPolicy]
  savePolicy: []
  runPolicy: [policy: BackupPolicy]
  verifySet: [item: BackupSet]
  exportConfig: []
  configFile: [file: File]
  configApply: []
  configDiscard: []
  copyCommand: [command: string]
  closePanel: []
}>()

const { t } = useI18n({ useScope: "global" })
const { formatTime, pretty, stateLabel, statusVariant } = useSystemFormatters()

const configImportInput = ref<HTMLInputElement | null>(null)

/** The visible button drives the hidden input; the input reports the choice. */
function pickConfigurationFile(): void {
  configImportInput.value?.click()
}

function onConfigurationFile(event: Event): void {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) {
    emit("configFile", file)
  }
  // Allow re-selecting the same file after a failed validation.
  input.value = ""
}

function backupPolicyName(policyId: string): string {
  return (
    props.backupPolicies.find((policy) => policy.id === policyId)?.name ??
    t("system.main.unknownPolicy")
  )
}

/** Most recent run per policy, used to summarise each policy card. */
const latestBackupByPolicy = computed(() => {
  const map = new Map<string, BackupSet>()
  for (const item of props.backups) {
    if (!map.has(item.backup_policy_id)) {
      map.set(item.backup_policy_id, item)
    }
  }
  return map
})
</script>

<template>
          <header class="system-page-header">
            <div>
              <strong>{{ t("system.main.backup") }}</strong>
              <span>{{ t("system.main.backupDesc") }}</span>
            </div>
            <div
              v-if="canManage"
              class="system-page-actions"
            >
              <input
                ref="configImportInput"
                type="file"
                accept=".json,application/json"
                hidden
                @change="onConfigurationFile"
              />
              <button
                class="button button--ghost"
                type="button"
                :disabled="configImportValidating"
                @click="pickConfigurationFile"
              >
                <UiIcon name="check" :size="14" />
                {{
                  configImportValidating
                    ? t("system.main.validating")
                    : t("system.main.validateImport")
                }}
              </button>
              <button
                class="button button--ghost"
                type="button"
                @click="emit('exportConfig')"
              >
                <UiIcon name="download" :size="14" />
                {{ t("system.main.exportConfig") }}
              </button>
              <button
                class="button button--ghost"
                type="button"
                :disabled="backupRefreshing"
                @click="emit('refresh')"
              >
                <UiIcon name="refresh" :size="14" />
                {{ backupRefreshing ? t("system.main.refreshing") : t("system.main.refresh") }}
              </button>
              <button
                class="button button--primary"
                type="button"
                @click="emit('openPanel')"
              >
                <UiIcon name="plus" :size="14" />
                {{ t("system.main.addPolicy") }}
              </button>
            </div>
          </header>

          <section class="backup-recovery-card">
            <div class="backup-recovery-card__heading">
              <div>
                <strong>{{ t("system.main.disasterRecovery") }}</strong>
                <span>
                  {{ t("system.main.disasterRecoveryHint") }}
                </span>
              </div>
              <span class="status-pill">{{ t("system.main.restoreHostOnly") }}</span>
            </div>

            <SystemRecoveryKitPanel
              :policies="backupPolicies"
            />

            <div class="backup-recovery-commands">
              <div>
                <span>{{ t("system.main.listSnapshots") }}</span>
                <code>./deploy.sh restore list</code>
                <button
                  class="button button--ghost button--compact"
                  type="button"
                  @click="emit('copyCommand', './deploy.sh restore list')"
                >
                  {{ t("system.main.copy") }}
                </button>
              </div>

              <div>
                <span>{{ t("system.main.restoreLatest") }}</span>
                <code>./deploy.sh restore latest --force</code>
                <button
                  class="button button--ghost button--compact"
                  type="button"
                  @click="
                    emit('copyCommand', './deploy.sh restore latest --force')
                  "
                >
                  {{ t("system.main.copy") }}
                </button>
              </div>

              <div>
                <span>{{ t("system.main.exportRecoveryKit") }}</span>
                <code>./deploy.sh recovery-kit export</code>
                <button
                  class="button button--ghost button--compact"
                  type="button"
                  @click="
                    emit('copyCommand', './deploy.sh recovery-kit export')
                  "
                >
                  {{ t("system.main.copy") }}
                </button>
              </div>

              <div>
                <span>{{ t("system.main.decryptKit") }}</span>
                <code>./deploy.sh recovery-kit decrypt /path/to/kit.znrk ./recovery-kit-restored</code>
                <button
                  class="button button--ghost button--compact"
                  type="button"
                  @click="
                    emit('copyCommand', './deploy.sh recovery-kit decrypt /path/to/kit.znrk ./recovery-kit-restored')
                  "
                >
                  {{ t("system.main.copy") }}
                </button>
              </div>
            </div>

            <div class="storage-notice">
              <UiIcon name="warning" :size="14" />
              <span>
                {{ t("system.main.restoreWarning") }}
              </span>
            </div>
          </section>

          <section
            v-if="configImportValidation"
            class="backup-policy-card"
          >
            <div class="backup-policy-card__top">
              <div>
                <strong>{{ t("system.main.configPreflight") }}</strong>
                <span>
                  {{
                    configImportFileName
                      ? `${configImportFileName} · ready to merge`
                      : t("system.main.readyMerge")
                  }}
                </span>
              </div>
              <span class="status-pill status-pill--ok">
                {{ t("system.main.valid") }}
              </span>
            </div>

            <div class="system-summary-grid">
              <div>
                <span>{{ t("system.main.format") }}</span>
                <strong>
                  {{ configImportValidation.format }} v{{
                    configImportValidation.format_version
                  }}
                </strong>
              </div>
              <div>
                <span>{{ t("system.main.sourceVersion") }}</span>
                <strong>
                  {{
                    configImportValidation.source_application_version ||
                    t("system.main.unknown")
                  }}
                </strong>
              </div>
              <div>
                <span>{{ t("system.main.credentialsRequired") }}</span>
                <strong>
                  {{
                    configImportValidation.credentials_required.length
                  }}
                </strong>
              </div>
            </div>

            <div class="system-table-wrap">
              <table class="system-table">
                <thead>
                  <tr>
                    <th>{{ t("system.main.section") }}</th>
                    <th>{{ t("system.main.resources") }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="(count, sectionName) in configImportValidation.section_counts"
                    :key="sectionName"
                  >
                    <td>{{ pretty(String(sectionName)) }}</td>
                    <td>{{ count }}</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div
              v-if="configImportValidation.credentials_required.length"
              class="system-table-wrap"
            >
              <table class="system-table">
                <thead>
                  <tr>
                    <th>{{ t("system.main.credentialReenter") }}</th>
                    <th>{{ t("system.main.resource") }}</th>
                    <th>{{ t("system.main.section") }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="(item, index) in configImportValidation.credentials_required"
                    :key="`${item.section}-${item.resource_id || index}-${item.credential}`"
                  >
                    <td>{{ pretty(item.credential) }}</td>
                    <td>
                      <strong>
                        {{ item.name || pretty(item.resource_type) }}
                      </strong>
                      <small v-if="item.resource_id">
                        {{ item.resource_id }}
                      </small>
                    </td>
                    <td>{{ pretty(item.section) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div
              v-for="warning in configImportValidation.warnings"
              :key="warning"
              class="storage-notice"
            >
              <UiIcon name="warning" :size="14" />
              <span>{{ warning }}</span>
            </div>

            <div class="storage-notice">
              <UiIcon name="check" :size="14" />
              <span>
                {{ t("system.main.preflightHint") }}
              </span>
            </div>

            <div
              v-if="!configImportApplyResult"
              class="system-form-actions"
            >
              <button
                class="button button--ghost"
                type="button"
                :disabled="configImportApplying"
                @click="emit('configDiscard')"
              >
                {{ t("system.main.discard") }}
              </button>
              <button
                class="button button--primary"
                type="button"
                :disabled="
                  configImportApplying ||
                  !configImportBundle ||
                  !canManage
                "
                @click="emit('configApply')"
              >
                {{
                  configImportApplying
                    ? t("system.main.applying")
                    : t("system.main.applyConfigMerge")
                }}
              </button>
            </div>

            <div
              v-else
              class="configuration-import-result"
            >
              <div class="system-summary-grid">
                <div>
                  <span>{{ t("system.main.applied") }}</span>
                  <strong>
                    {{ configImportApplyResult.applied_count }}
                  </strong>
                </div>
                <div>
                  <span>{{ t("system.main.skipped") }}</span>
                  <strong>
                    {{ configImportApplyResult.skipped_count }}
                  </strong>
                </div>
                <div>
                  <span>{{ t("system.main.mode") }}</span>
                  <strong>{{ pretty(configImportApplyResult.mode) }}</strong>
                </div>
              </div>

              <div
                v-if="configImportApplyResult.applied.length"
                class="system-table-wrap"
              >
                <table class="system-table">
                  <thead>
                    <tr>
                      <th>{{ t("system.main.appliedResource") }}</th>
                      <th>{{ t("system.main.section") }}</th>
                      <th>{{ t("system.main.action") }}</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr
                      v-for="(item, index) in configImportApplyResult.applied"
                      :key="`applied-${item.section}-${item.target_id || item.source_id || index}`"
                    >
                      <td>
                        <strong>
                          {{ item.name || pretty(item.resource_type) }}
                        </strong>
                        <small v-if="item.target_id">
                          {{ item.target_id }}
                        </small>
                      </td>
                      <td>{{ pretty(item.section) }}</td>
                      <td>
                        <span class="status-pill status-pill--ok">
                          {{ pretty(item.action) }}
                        </span>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>

              <div
                v-if="configImportApplyResult.skipped.length"
                class="system-table-wrap"
              >
                <table class="system-table">
                  <thead>
                    <tr>
                      <th>{{ t("system.main.skippedResource") }}</th>
                      <th>{{ t("system.main.section") }}</th>
                      <th>{{ t("system.main.reason") }}</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr
                      v-for="(item, index) in configImportApplyResult.skipped"
                      :key="`skipped-${item.section}-${item.source_id || index}`"
                    >
                      <td>
                        <strong>
                          {{ item.name || pretty(item.resource_type) }}
                        </strong>
                      </td>
                      <td>{{ pretty(item.section) }}</td>
                      <td>
                        {{ pretty(item.reason || "skipped") }}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>

              <div
                v-for="warning in configImportApplyResult.warnings"
                :key="`applied-${warning}`"
                class="storage-notice"
              >
                <UiIcon name="warning" :size="14" />
                <span>{{ warning }}</span>
              </div>

              <div class="system-form-actions">
                <button
                  class="button button--ghost"
                  type="button"
                  @click="emit('configDiscard')"
                >
                  {{ t("system.main.closeResult") }}
                </button>
              </div>
            </div>
          </section>

          <div class="backup-policy-grid">
            <article
              v-for="policy in backupPolicies"
              :key="policy.id"
              class="backup-policy-card"
            >
              <div class="backup-policy-card__top">
                <div>
                  <strong>{{ policy.name }}</strong>
                  <span>
                    {{
                      policy.schedule.cron
                        ? String(policy.schedule.cron)
                        : t("system.main.manualOnly")
                    }}
                  </span>
                </div>
                <span
                  class="status-pill"
                  :class="policy.enabled ? 'status-pill--ok' : 'status-pill--muted'"
                >
                  {{ policy.enabled ? t("system.main.enabled") : t("system.main.disabled") }}
                </span>
              </div>
              <dl>
                <div>
                  <dt>{{ t("system.main.database") }}</dt>
                  <dd>{{ policy.database_backend }}</dd>
                </div>
                <div>
                  <dt>{{ t("system.main.verify") }}</dt>
                  <dd>{{ policy.verify_after_backup ? t("system.main.afterEveryRun") : t("system.main.manual") }}</dd>
                </div>
                <div>
                  <dt>{{ t("system.main.lastRun") }}</dt>
                  <dd>
                    {{
                      latestBackupByPolicy.get(policy.id)
                        ? formatTime(latestBackupByPolicy.get(policy.id)!.started_at)
                        : t("system.main.never")
                    }}
                  </dd>
                </div>
              </dl>
              <div
                v-if="canManage"
                class="system-form-actions"
              >
                <button
                  class="button button--ghost"
                  type="button"
                  @click="emit('editPolicy', policy)"
                >
                  <UiIcon name="settings" :size="14" />
                  {{ t("system.main.edit") }}
                </button>
                <button
                  class="button button--ghost"
                  type="button"
                  :disabled="runningBackupId === policy.id"
                  @click="emit('runPolicy', policy)"
                >
                  <UiIcon name="backup" :size="14" />
                  {{ runningBackupId === policy.id ? t("system.main.starting") : t("system.main.runNow") }}
                </button>
              </div>
            </article>
          </div>

          <div class="system-section">
            <div class="system-section__heading">
              <strong>{{ t("system.main.backupHistory") }}</strong>
              <span>{{ t("system.main.backupHistoryHint") }}</span>
            </div>
            <div class="system-table-wrap">
              <table class="system-table">
                <thead>
                  <tr>
                    <th>{{ t("system.main.backup") }}</th>
                    <th>{{ t("system.main.state") }}</th>
                    <th>{{ t("system.main.size") }}</th>
                    <th>{{ t("system.main.verification") }}</th>
                    <th>{{ t("system.main.version") }}</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="item in backups" :key="item.id">
                    <td>
                      <strong>
                        {{ backupPolicyName(item.backup_policy_id) }}
                      </strong>
                      <small>
                        {{ formatTime(item.started_at) }} ·
                        {{ pretty(item.reason) }}
                      </small>
                      <small v-if="item.error_code">
                        {{ pretty(item.error_code) }}
                        <template v-if="item.sanitized_error">
                          · {{ item.sanitized_error }}
                        </template>
                      </small>
                    </td>
                    <td>
                      <StatusPill :variant="statusVariant(item.state)">
                        {{ stateLabel(item.state) }}
                      </StatusPill>
                    </td>
                    <td>{{ formatBytes(item.size_bytes) }}</td>
                    <td>{{ stateLabel(item.verification_state) }}</td>
                    <td>{{ item.app_version }}</td>
                    <td class="system-table__actions">
                      <button
                        v-if="canManage && item.state === 'COMPLETED'"
                        class="button button--ghost button--compact"
                        type="button"
                        :disabled="verifyingBackupId === item.id"
                        @click="emit('verifySet', item)"
                      >
                        {{ verifyingBackupId === item.id ? t("system.main.queuing") : t("system.main.verify") }}
                      </button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <aside v-if="backupPanelOpen" class="system-drawer">
            <header class="storage-editor__header">
              <div>
                <strong>
                  {{
                    editingBackupPolicy
                      ? t("system.main.editBackupPolicy")
                      : t("system.main.addBackupPolicy")
                  }}
                </strong>
                <span>{{ t("system.main.resticRepository") }}</span>
              </div>
              <button class="icon-button" type="button" @click="emit('closePanel')">
                <UiIcon name="close" :size="16" />
              </button>
            </header>
            <form class="storage-editor__form" @submit.prevent="emit('savePolicy')">
              <label>
                <span>{{ t("system.main.name") }}</span>
                <input v-model="backupForm.name" required />
              </label>
              <label>
                <span>{{ t("system.main.repository") }}</span>
                <input
                  v-model="backupForm.repository"
                  :required="!editingBackupPolicy"
                  :placeholder="
                    editingBackupPolicy
                      ? t('system.main.leaveRepo')
                      : '/backups/zero-nvr or s3:...'
                  "
                />
                <small v-if="editingBackupPolicy">
                  {{ t("system.main.repositoryKeepHint") }}
                </small>
              </label>
              <label>
                <span>{{ t("system.main.resticPassword") }}</span>
                <input
                  v-model="backupForm.password"
                  type="password"
                  :required="!editingBackupPolicy"
                  autocomplete="new-password"
                />
                <small v-if="editingBackupPolicy">
                  {{ t("system.main.passwordKeepHint") }}
                </small>
              </label>
              <label>
                <span>{{ t("system.main.repoEnvCredentials") }}</span>
                <textarea
                  v-model="backupForm.environmentCredentials"
                  rows="5"
                  spellcheck="false"
                  placeholder="AWS_ACCESS_KEY_ID=…&#10;AWS_SECRET_ACCESS_KEY=…"
                />
                <small>
                  {{ t("system.main.repoEnvHint") }}
                  {{
                    editingBackupPolicy
                      ? t("system.main.leaveEnv")
                      : t("system.main.envBackendHint")
                  }}
                </small>
              </label>
              <label
                v-if="!editingBackupPolicy"
                class="storage-check"
              >
                <input v-model="backupForm.initializeIfMissing" type="checkbox" />
                <span>{{ t("system.main.initRepository") }}</span>
              </label>
              <label class="storage-check">
                <input v-model="backupForm.enabled" type="checkbox" />
                <span>{{ t("system.main.policyEnabled") }}</span>
              </label>
              <label class="storage-check">
                <input v-model="backupForm.scheduled" type="checkbox" />
                <span>{{ t("system.main.scheduled") }}</span>
              </label>
              <label v-if="backupForm.scheduled">
                <span>{{ t("system.main.cron") }}</span>
                <input v-model="backupForm.cron" placeholder="0 3 * * *" />
                <small>{{ t("system.main.cronTimezone") }} {{ settings?.general.display_timezone || "UTC" }}</small>
              </label>
              <div class="retention-days-grid">
                <label>
                  <span>{{ t("system.main.keepLast") }}</span>
                  <input v-model.number="backupForm.keepLast" type="number" min="0" />
                </label>
                <label>
                  <span>{{ t("system.main.daily") }}</span>
                  <input v-model.number="backupForm.keepDaily" type="number" min="0" />
                </label>
                <label>
                  <span>{{ t("system.main.weekly") }}</span>
                  <input v-model.number="backupForm.keepWeekly" type="number" min="0" />
                </label>
                <label>
                  <span>{{ t("system.main.monthly") }}</span>
                  <input v-model.number="backupForm.keepMonthly" type="number" min="0" />
                </label>
              </div>
              <label class="storage-check">
                <input v-model="backupForm.verifyAfter" type="checkbox" />
                <span>{{ t("system.main.verifyAfter") }}</span>
              </label>
              <label class="storage-check">
                <input v-model="backupForm.includeDeploymentConfig" type="checkbox" />
                <span>{{ t("system.main.includeDeployment") }}</span>
              </label>
              <div class="storage-editor__actions">
                <button class="button button--ghost" type="button" @click="emit('closePanel')">
                  {{ t("system.main.cancel") }}
                </button>
                <button class="button button--primary" type="submit" :disabled="backupSaving">
                  {{
                    backupSaving
                      ? t("system.main.saving")
                      : editingBackupPolicy
                        ? t("system.main.saveBackupPolicy")
                        : t("system.main.createBackupPolicy")
                  }}
                </button>
              </div>
            </form>
          </aside>
</template>

<style scoped>
.backup-recovery-card {
  display: grid;
  gap: 12px;
  margin-bottom: 14px;
  padding: 16px;
  border: 1px solid var(--uf-border);
  border-radius: 14px;
  background: var(--uf-bg-card);
}

.backup-recovery-card__heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
}

.backup-recovery-card__heading strong,
.backup-recovery-card__heading span {
  display: block;
}

.backup-recovery-card__heading strong {
  font-size: 13px;
  font-weight: 600;
  color: var(--uf-text-primary);
}

.backup-recovery-card__heading div > span {
  max-width: 680px;
  margin-top: 2px;
  color: var(--uf-text-muted);
  font-size: 11px;
  line-height: 1.5;
}
</style>
