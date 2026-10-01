/**
 * Bind a handler to the application-wide refresh signal.
 *
 * `AppShell` dispatches `zero-nvr:refresh` when its event stream reports a
 * change, and eight views hand-wired the same
 * `addEventListener`/`removeEventListener` pair around it. Two of them used a
 * bespoke wrapper purely to satisfy the listener signature.
 *
 * This registers the listener *only*. It deliberately does not perform an
 * initial load: most callers gate their first fetch on other state (an active
 * camera, a resolved route param) and several run other work in the same
 * `onMounted`, so folding the initial call in here would either duplicate it or
 * ignore those conditions.
 */

import { onBeforeUnmount, onMounted } from "vue"

type RefreshHandler = () => void | Promise<void>

export function useGlobalRefresh(handler: RefreshHandler): void {
  // The DOM passes an Event; the handler does not want it. `void` documents
  // that a rejected promise is reported by the handler itself, not re-thrown
  // into the event dispatch.
  const listener = (): void => {
    void handler()
  }

  onMounted(() => {
    window.addEventListener("zero-nvr:refresh", listener)
  })

  onBeforeUnmount(() => {
    window.removeEventListener("zero-nvr:refresh", listener)
  })
}
