/**
 * Fullscreen enter/exit plus the state sync that goes with it.
 *
 * Three components implemented the request/exit pair and the
 * `fullscreenchange` listener separately. Two of them differed on what "active"
 * means — the live grid and the playback stage only care that *something* is
 * fullscreen, while a single camera tile only cares whether *it* is the
 * fullscreen element — so the predicate is injectable rather than assumed.
 *
 * Some browsers reject `requestFullscreen()` when the call is not user-initiated
 * and the promise rejects; callers that care can await it, callers that do not
 * are unaffected because the state is driven by the `fullscreenchange` event
 * rather than by the request succeeding.
 */

import { onBeforeUnmount, onMounted, type Ref } from "vue"

interface FullscreenOptions {
  /**
   * Decide whether the tracked element counts as fullscreen.
   *
   * Defaults to "any element is fullscreen", which is what a page-level
   * workspace wants. A per-tile view should pass an identity comparison.
   */
  isActive?: (element: HTMLElement | null) => boolean
}

export function useFullscreen(
  element: Ref<HTMLElement | null>,
  active: Ref<boolean>,
  { isActive }: FullscreenOptions = {}
): {
  enter: () => Promise<void>
  exit: () => Promise<void>
  toggle: () => Promise<void>
  sync: () => void
} {
  const predicate =
    isActive ?? (() => Boolean(document.fullscreenElement))

  function sync(): void {
    active.value = predicate(element.value)
  }

  async function enter(): Promise<void> {
    await element.value?.requestFullscreen?.()
  }

  async function exit(): Promise<void> {
    await document.exitFullscreen()
  }

  async function toggle(): Promise<void> {
    if (document.fullscreenElement) {
      await exit()
      return
    }
    await enter()
  }

  onMounted(() => {
    document.addEventListener("fullscreenchange", sync)
  })

  onBeforeUnmount(() => {
    document.removeEventListener("fullscreenchange", sync)
  })

  return { enter, exit, toggle, sync }
}
