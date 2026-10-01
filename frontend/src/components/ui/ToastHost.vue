<script setup lang="ts">
/**
 * Renders the active toast for whichever surface owns it.
 *
 * Four views each kept their own `v-if="toastMessage"` block around a
 * differently-positioned wrapper. The wrapper class stays a prop, and the
 * *contents* stay a slot, for one reason: the styling of these surfaces is
 * scoped to the owning view. Vue stamps a parent's scope id onto a child
 * component's root element but not onto elements nested inside it, so a
 * `.toast-dot` or icon rendered here would lose its styling. Keeping the
 * children in the caller means every element except the root remains the view's
 * own, and the root still matches the view's scoped wrapper rule.
 *
 * The message itself comes from `useToast`, which owns the timer.
 */
import { useToast } from "../../composables/useToast"

defineProps<{ surfaceClass: string }>()

const { message } = useToast()
</script>

<template>
  <div v-if="message" :class="surfaceClass">
    <slot :message="message">{{ message }}</slot>
  </div>
</template>
