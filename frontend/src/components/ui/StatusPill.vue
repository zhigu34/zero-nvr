<script setup lang="ts">
/**
 * A small status chip.
 *
 * The call sites all wrote `<span class="status-pill" :class="…">`, repeating
 * the base class and passing the variant as an untyped string. That is how the
 * `--warning` and `--danger` variants came to be referenced while no rule
 * defined them: an unstyled chip looks like a styling choice rather than a bug.
 *
 * The variant is a closed union, so a name with no definition fails to compile
 * instead of silently rendering the base style. Every variant here has a
 * matching rule in `styles.css`, or in the owning view's scoped styles — those
 * still apply because this component's root carries the caller's scope id.
 *
 * `variant` is optional: some call sites deliberately render the bare chip and
 * must not gain `status-pill--muted`'s reduced opacity.
 */
export type StatusVariant =
  | "ok"
  | "muted"
  | "warning"
  | "danger"
  | "error"
  | "online"
  | "offline"
  | "maintenance"
  | "disabled"
  | "retired"

withDefaults(
  defineProps<{ variant?: StatusVariant }>(),
  { variant: undefined }
)
</script>

<template>
  <span
    class="status-pill"
    :class="variant ? `status-pill--${variant}` : undefined"
  >
    <slot />
  </span>
</template>
