/**
 * Close a popover when the user clicks outside it or presses Escape.
 *
 * The theme and language controls in the top bar carried byte-equivalent copies
 * of this behaviour (outside-pointer check plus Escape check, wired and unwired
 * in `onMounted`/`onBeforeUnmount`), which is roughly thirty duplicated lines for
 * one interaction. Nothing else in the app had it at all, so the popovers that
 * lacked it stayed open until their trigger was clicked again.
 *
 * Uses `pointerdown` rather than `click` so the popover closes as the press
 * lands, matching the behaviour the two controls already had.
 */

import { onBeforeUnmount, onMounted, type Ref } from "vue"

export function useDismissable(
  open: Ref<boolean>,
  root: Ref<HTMLElement | null>
): void {
  function closeOnOutside(event: PointerEvent): void {
    if (!open.value || root.value?.contains(event.target as Node)) return
    open.value = false
  }

  function closeOnEscape(event: KeyboardEvent): void {
    if (event.key === "Escape") open.value = false
  }

  onMounted(() => {
    window.addEventListener("pointerdown", closeOnOutside)
    window.addEventListener("keydown", closeOnEscape)
  })

  onBeforeUnmount(() => {
    window.removeEventListener("pointerdown", closeOnOutside)
    window.removeEventListener("keydown", closeOnEscape)
  })
}
