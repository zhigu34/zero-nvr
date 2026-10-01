/**
 * Ask the operator to confirm a destructive action.
 *
 * Fifteen call sites used `window.confirm`, which blocks the main thread, cannot
 * be styled or translated, and in some browsers is suppressed entirely — in
 * which case the check silently passes and the action proceeds unconfirmed.
 *
 * The prompt state lives at module scope so a single `<ConfirmDialog>` (mounted
 * once in `AppShell`) can serve every caller, and callers only need
 * `await confirm({ message })`. When no dialog host is mounted — a component
 * exercised in isolation by a test — this falls back to the browser prompt
 * rather than assuming consent, because assuming consent would turn an
 * unanswered question into a destructive action.
 */

import { onBeforeUnmount, readonly, ref } from "vue"

export interface ConfirmOptions {
  /** Question shown to the operator. Should name the object being acted on. */
  message: string
  /** Optional heading; omit for a single-question prompt. */
  title?: string
  confirmLabel?: string
  cancelLabel?: string
  /** Style the confirm action as destructive. */
  danger?: boolean
}

interface ConfirmState {
  open: boolean
  message: string
  title: string
  confirmLabel: string
  cancelLabel: string
  danger: boolean
}

const CLOSED: ConfirmState = {
  open: false,
  message: "",
  title: "",
  confirmLabel: "",
  cancelLabel: "",
  danger: false
}

const state = ref<ConfirmState>({ ...CLOSED })

let resolvePending: ((confirmed: boolean) => void) | null = null
let hostCount = 0

function settle(confirmed: boolean): void {
  const pending = resolvePending
  resolvePending = null
  state.value = { ...CLOSED }
  pending?.(confirmed)
}

/**
 * Open the confirmation dialog. Resolves `true` only on explicit confirmation.
 */
export function confirmAction(options: ConfirmOptions): Promise<boolean> {
  if (hostCount === 0) {
    return Promise.resolve(window.confirm(options.message))
  }

  // A prompt opened while another is pending supersedes it. The superseded
  // caller resolves `false` so it cannot act on an answer never given.
  settle(false)

  state.value = {
    open: true,
    message: options.message,
    title: options.title ?? "",
    confirmLabel: options.confirmLabel ?? "",
    cancelLabel: options.cancelLabel ?? "",
    danger: options.danger ?? false
  }

  return new Promise<boolean>((resolve) => {
    resolvePending = resolve
  })
}

/** Caller-facing handle. Exists so call sites read as `useConfirm()`. */
export function useConfirm(): { confirm: typeof confirmAction } {
  return { confirm: confirmAction }
}

/** Used by the single dialog host to own the prompt lifecycle. */
export function useConfirmDialog(): {
  state: Readonly<typeof state>
  accept: () => void
  dismiss: () => void
} {
  hostCount += 1
  onBeforeUnmount(() => {
    hostCount -= 1
    // Never leave a caller waiting on a dialog that no longer exists.
    settle(false)
  })

  return {
    state: readonly(state),
    accept: () => settle(true),
    dismiss: () => settle(false)
  }
}
