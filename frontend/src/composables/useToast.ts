/**
 * Transient operator feedback ("toast") shared by the views that show one.
 *
 * Four views had grown their own copy of the same three-part pattern: a
 * `toastMessage` ref, a `showToast` that arms a `setTimeout`, and a template
 * block. Three of the four never cleared that timeout, so the callback wrote to
 * a ref belonging to an unmounted component.
 *
 * The state lives at module scope rather than inside the composable's caller.
 * That is what removes the leak class outright: the timer now writes to a
 * module-level ref, which outlives any component, instead of to a destroyed
 * component's ref. Arming a new message always cancels the previous timer, so a
 * stale timer can never clear a message that replaced it.
 *
 * Markup and CSS deliberately stay in each view for now: the four surfaces
 * position themselves differently (bottom-centre pill, bottom-right banner,
 * top-right with an icon) and their styles are scoped to the view, so
 * promoting them into one host is a CSS move that needs visual verification.
 * That belongs to the stylesheet-consolidation pass.
 */

import { readonly, ref } from "vue"

/** The single active message, or `null` when nothing is showing. */
const message = ref<string | null>(null)

let timer: number | null = null

function clearTimer(): void {
  if (timer !== null) {
    clearTimeout(timer)
    timer = null
  }
}

/**
 * Show a transient message, replacing any message already showing.
 *
 * `durationMs` stays a parameter because each surface has its own historical
 * dwell time (the file manager is terser than the schedule editor).
 */
export function showToast(text: string, durationMs = 3000): void {
  message.value = text
  clearTimer()
  timer = window.setTimeout(() => {
    timer = null
    message.value = null
  }, durationMs)
}

/** Clear the message and cancel any pending timer. */
export function dismissToast(): void {
  clearTimer()
  message.value = null
}

export function useToast(defaultDurationMs = 3000) {
  return {
    message: readonly(message),
    showToast: (text: string, durationMs = defaultDurationMs) =>
      showToast(text, durationMs),
    dismissToast
  }
}
