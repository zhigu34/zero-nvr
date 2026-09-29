<script setup lang="ts">
import type { CameraFormFactor } from "../../api/cameras"

withDefaults(
  defineProps<{
    formFactor?: CameraFormFactor
  }>(),
  {
    formFactor: "unknown"
  }
)
</script>

<template>
  <svg class="camera-device-glyph" viewBox="0 0 64 64" aria-hidden="true">
    <g v-if="formFactor === 'bullet'">
      <path d="M12 30h8l4-7h21l7 6v9l-7 6H24l-4-7h-8z" />
      <circle cx="43" cy="33.5" r="5.5" />
      <path d="M24 44l-7 9M31 44l-1 8" />
    </g>

    <g v-else-if="formFactor === 'dome'">
      <path d="M14 34c1-13 9-21 18-21s17 8 18 21z" />
      <path d="M11 34h42v5H11z" />
      <circle cx="32" cy="29" r="6" />
      <path d="M23 40h18" />
    </g>

    <g v-else-if="formFactor === 'turret'">
      <path d="M15 23h34l4 8-5 17H16l-5-17z" />
      <circle cx="32" cy="34" r="9" />
      <circle cx="32" cy="34" r="3.5" />
      <path d="M21 20h22" />
    </g>

    <g v-else-if="formFactor === 'ptz'">
      <path d="M18 15h28l4 7v7H14v-7z" />
      <path d="M17 29h30v6c0 10-7 18-15 18s-15-8-15-18z" />
      <circle cx="32" cy="38" r="7" />
      <circle cx="32" cy="38" r="3" />
    </g>

    <g v-else-if="formFactor === 'panoramic'">
      <ellipse cx="32" cy="31" rx="22" ry="13" />
      <ellipse cx="32" cy="31" rx="9" ry="9" />
      <circle cx="32" cy="31" r="3" />
      <path d="M16 42c4 5 10 8 16 8s12-3 16-8" />
      <path d="M14 23c4-5 10-8 18-8s14 3 18 8" />
    </g>

    <g v-else-if="formFactor === 'doorbell'">
      <rect x="22" y="8" width="20" height="48" rx="7" />
      <circle cx="32" cy="24" r="6" />
      <circle cx="32" cy="43" r="4" />
      <path d="M28 13h8" />
    </g>

    <g v-else-if="formFactor === 'indoor'">
      <rect x="17" y="13" width="30" height="28" rx="9" />
      <circle cx="32" cy="27" r="8" />
      <circle cx="32" cy="27" r="3" />
      <path d="M26 41v7M38 41v7M22 50h20" />
    </g>

    <g v-else>
      <rect x="12" y="20" width="40" height="28" rx="8" />
      <circle cx="32" cy="34" r="10" />
      <circle cx="32" cy="34" r="4" />
      <path d="M21 20l4-6h14l4 6" />
    </g>
  </svg>
</template>

<style scoped>
.camera-device-glyph {
  width: 100%;
  height: 100%;
  fill: none;
  stroke: currentColor;
  stroke-width: 2.4;
  stroke-linecap: round;
  stroke-linejoin: round;
  vector-effect: non-scaling-stroke;
}
</style>
