<script setup lang="ts">
import { computed } from "vue"

const props = withDefaults(
  defineProps<{
    name: string
    size?: number
  }>(),
  {
    size: 18
  }
)

const icons: Record<string, string> = {
  dashboard:
    '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  live:
    '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M8 9.5h8M8 14.5h5"/><circle cx="17" cy="14.5" r="1"/>',
  playback:
    '<circle cx="12" cy="12" r="9"/><path d="m10 8 6 4-6 4Z"/>',
  events:
    '<path d="M5 3v18M19 3v18M8 7h8M8 12h8M8 17h5"/>',
  cameras:
    '<path d="M4 8.5A2.5 2.5 0 0 1 6.5 6h7A2.5 2.5 0 0 1 16 8.5v7A2.5 2.5 0 0 1 13.5 18h-7A2.5 2.5 0 0 1 4 15.5Z"/><path d="m16 10 4-2v8l-4-2Z"/>',
  storage:
    '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v7c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 12v7c0 1.7 3.6 3 8 3s8-1.3 8-3v-7"/>',
  system:
    '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-4V21a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1A1.7 1.7 0 0 0 4.6 15 1.7 1.7 0 0 0 3 14H2.8v-4H3a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-1.6v-.2h4V3a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2v4H21a1.7 1.7 0 0 0-1.6 1Z"/>',
  menu:
    '<path d="M4 7h16M4 12h16M4 17h16"/>',
  collapse:
    '<path d="M9 4H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h4M14 8l4 4-4 4M18 12H8"/>',
  expand:
    '<path d="M15 4h4a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-4M10 8l-4 4 4 4M6 12h10"/>',
  sun:
    '<circle cx="12" cy="12" r="3.5"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  moon:
    '<path d="M20 15.2A8.5 8.5 0 0 1 8.8 4 8.5 8.5 0 1 0 20 15.2Z"/>',
  monitor:
    '<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8M12 17v4"/>',
  check:
    '<path d="m5 12 4 4L19 6"/>',
  logout:
    '<path d="M10 4H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h5M14 8l4 4-4 4M18 12H9"/>',
  chevron:
    '<path d="m8 10 4 4 4-4"/>',
  activity:
    '<path d="M3 12h4l2.2-5 4.3 10 2.2-5H21"/>',
  search:
    '<circle cx="11" cy="11" r="6"/><path d="m16 16 4 4"/>',
  refresh:
    '<path d="M20 7v5h-5M4 17v-5h5"/><path d="M6.1 8.5A7 7 0 0 1 18.8 7L20 12M4 12l1.2 5A7 7 0 0 0 17.9 15.5"/>',
  maximize:
    '<path d="M8 3H3v5M16 3h5v5M8 21H3v-5M16 21h5v-5"/>',
  minimize:
    '<path d="M8 8H3V3M16 8h5V3M8 16H3v5M16 16h5v5"/>',
  volume:
    '<path d="M11 5 6.5 9H3v6h3.5L11 19Z"/><path d="M15 9a4 4 0 0 1 0 6M17.5 6.5a8 8 0 0 1 0 11"/>',
  "volume-off":
    '<path d="M11 5 6.5 9H3v6h3.5L11 19Z"/><path d="m16 10 5 5M21 10l-5 5"/>',
  focus:
    '<path d="M8 3H3v5M16 3h5v5M8 21H3v-5M16 21h5v-5"/><circle cx="12" cy="12" r="2"/>',
  panel:
    '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/>',
  grid1:
    '<rect x="4" y="4" width="16" height="16" rx="2"/>',
  grid4:
    '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  grid9:
    '<path d="M3 3h5v5H3zM9.5 3h5v5h-5zM16 3h5v5h-5zM3 9.5h5v5H3zM9.5 9.5h5v5h-5zM16 9.5h5v5h-5zM3 16h5v5H3zM9.5 16h5v5h-5zM16 16h5v5h-5z"/>',
  warning:
    '<path d="M12 3 2.8 20h18.4Z"/><path d="M12 9v4M12 17h.01"/>',
  play:
    '<path d="m9 7 8 5-8 5Z"/>',
  pause:
    '<path d="M9 7v10M15 7v10"/>',
  previous:
    '<path d="M6 6v12M18 7l-8 5 8 5Z"/>',
  next:
    '<path d="M18 6v12M6 7l8 5-8 5Z"/>',
  calendar:
    '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4M17 3v4M3 10h18"/>',
  "chevron-right":
    '<path d="m9 6 6 6-6 6"/>',
  close:
    '<path d="m6 6 12 12M18 6 6 18"/>',
  zone:
    '<path d="M12 21s6-4.7 6-11a6 6 0 1 0-12 0c0 6.3 6 11 6 11Z"/><circle cx="12" cy="10" r="2"/>',
  plus:
    '<path d="M12 5v14M5 12h14"/>',
  trash:
    '<path d="M4 7h16M9 7V4h6v3M7 7l1 13h8l1-13M10 11v5M14 11v5"/>',
  drive:
    '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M6 15h.01M10 15h.01"/><path d="M3 12h18"/>',
  cloud:
    '<path d="M7 18h10a4 4 0 0 0 .7-7.9A6 6 0 0 0 6.4 8.4 4.5 4.5 0 0 0 7 18Z"/>',
  shield:
    '<path d="M12 3 5 6v5c0 4.8 2.9 8 7 10 4.1-2 7-5.2 7-10V6Z"/><path d="m9 12 2 2 4-4"/>',
  users:
    '<path d="M16 20v-1.5a4.5 4.5 0 0 0-4.5-4.5h-4A4.5 4.5 0 0 0 3 18.5V20"/><circle cx="9.5" cy="7" r="4"/><path d="M17 11a3.5 3.5 0 0 1 4 3.5V20"/>',
  bell:
    '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9"/><path d="M10 21h4"/>',
  brain:
    '<path d="M9.5 4.5A3.5 3.5 0 0 0 6 8v1a3.5 3.5 0 0 0-1 6.85A3.5 3.5 0 0 0 9.5 20H12V4.5Z"/><path d="M14.5 4.5A3.5 3.5 0 0 1 18 8v1a3.5 3.5 0 0 1 1 6.85A3.5 3.5 0 0 1 14.5 20H12V4.5Z"/><path d="M8 10h4M12 14h4"/>',
  backup:
    '<path d="M4 7v13h16V7l-3-3H7Z"/><path d="M8 4v6h8V4M8 16h8"/>',
  audit:
    '<path d="M6 3h12v18H6Z"/><path d="M9 7h6M9 11h6M9 15h4"/>',
  export:
    '<path d="M12 3v12M8 7l4-4 4 4"/><path d="M5 13v7h14v-7"/>',
  download:
    '<path d="M12 3v12M8 11l4 4 4-4"/><path d="M5 20h14"/>'
}

const content = computed(() => icons[props.name] ?? icons.activity)
</script>

<template>
  <svg
    class="ui-icon"
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.75"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <g v-html="content" />
  </svg>
</template>
