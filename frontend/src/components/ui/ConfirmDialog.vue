<script setup lang="ts">
/**
 * The single confirmation dialog, mounted once in `AppShell`.
 *
 * Labels default to the shared `common.*` keys so callers only supply the
 * question. `role="alertdialog"` is used rather than `role="dialog"` because the
 * prompt interrupts a destructive flow and needs an explicit response.
 */
import { computed } from "vue"
import { useI18n } from "vue-i18n"

import { useConfirmDialog } from "../../composables/useConfirm"

const { state, accept, dismiss } = useConfirmDialog()
const { t } = useI18n({ useScope: "global" })

const confirmLabel = computed(() => state.value.confirmLabel || t("common.confirm"))
const cancelLabel = computed(() => state.value.cancelLabel || t("common.cancel"))
</script>

<template>
  <div
    v-if="state.open"
    class="confirm-backdrop"
    @click.self="dismiss"
    @keydown.esc="dismiss"
  >
    <div
      class="confirm-dialog"
      role="alertdialog"
      aria-modal="true"
      :aria-label="state.title || state.message"
    >
      <strong v-if="state.title" class="confirm-dialog__title">
        {{ state.title }}
      </strong>
      <p class="confirm-dialog__message">{{ state.message }}</p>
      <div class="confirm-dialog__actions">
        <button
          type="button"
          class="button button--ghost button--compact"
          @click="dismiss"
        >
          {{ cancelLabel }}
        </button>
        <button
          type="button"
          class="button button--compact"
          :class="state.danger ? 'button--danger' : 'button--primary'"
          @click="accept"
        >
          {{ confirmLabel }}
        </button>
      </div>
    </div>
  </div>
</template>
