<script setup lang="ts">
/**
 * The overlay shell shared by the slide-over editors.
 *
 * Every drawer in the app repeated the same three behaviours by hand: a
 * full-screen backdrop, a click on that backdrop dismissing the drawer, and a
 * close control inside the header. The backdrop class name had already drifted
 * across six spellings, and the close button had six different treatments.
 *
 * The panel is a *slot* rather than something this component renders. That is
 * the whole point: a view's scoped CSS reaches a child component's root element
 * but nothing nested inside it, so the backdrop can live here while the panel
 * (`aside.unifi-drawer`, `aside.system-drawer`, …) stays the caller's own
 * element with its own scoped rules. Rendering the panel here would strip
 * `.unifi-drawer` and every `.unifi-drawer__header strong` rule with it.
 *
 * `dismiss` is emitted for a backdrop click and for Escape; the caller decides
 * what closing means (usually clearing its `open` flag and its edit target).
 */
import { onBeforeUnmount, watch } from "vue"

const props = withDefaults(
  defineProps<{
    /** Root backdrop class, e.g. `unifi-drawer-backdrop`. */
    backdropClass: string
    /**
     * Whether the drawer is currently shown.
     *
     * Optional: a caller that needs the template type-narrowing a truthy `v-if`
     * gives (to pass a non-null edit target into the slot) can put the `v-if` on
     * this component instead and leave `open` unset.
     */
    open?: boolean
    /** Allow clicking the backdrop to dismiss. Defaults to true. */
    closeOnBackdrop?: boolean
    /** Allow Escape to dismiss. Defaults to true. */
    closeOnEscape?: boolean
  }>(),
  { open: true, closeOnBackdrop: true, closeOnEscape: true }
)

const emit = defineEmits<{ dismiss: [] }>()

function onKeydown(event: KeyboardEvent): void {
  if (!props.open || !props.closeOnEscape) return
  if (event.key === "Escape") {
    emit("dismiss")
  }
}

function onBackdropClick(): void {
  if (props.closeOnBackdrop) {
    emit("dismiss")
  }
}

// The listener is only attached while the drawer is open, so a closed drawer
// cannot swallow Escape from whatever the operator is actually looking at.
// `immediate` also covers the case where the drawer starts open.
watch(
  () => props.open,
  (open) => {
    if (open) {
      window.addEventListener("keydown", onKeydown)
      return
    }
    window.removeEventListener("keydown", onKeydown)
  },
  { immediate: true }
)

onBeforeUnmount(() => {
  window.removeEventListener("keydown", onKeydown)
})
</script>

<template>
  <div v-if="open" :class="backdropClass" @click.self="onBackdropClick">
    <slot />
  </div>
</template>
