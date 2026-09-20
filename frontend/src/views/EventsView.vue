<script setup lang="ts">
import {
  computed,
  onBeforeUnmount,
  onMounted,
  ref
} from "vue"
import { useRouter } from "vue-router"

import {
  listCameras,
  type CameraSummary
} from "../api/cameras"
import { errorMessage } from "../api/client"
import {
  eventSnapshotUrl,
  listEvents,
  type EventItem
} from "../api/events"
import UiIcon from "../components/ui/UiIcon.vue"
import { useAuthStore } from "../stores/auth"

type Period = "24h" | "7d" | "30d" | "all"

const router = useRouter()
const auth = useAuthStore()

const cameras = ref<CameraSummary[]>([])
const events = ref<EventItem[]>([])
const selectedEvent = ref<EventItem | null>(null)
const nextCursor = ref<string | null>(null)
const period = ref<Period>("24h")
const cameraId = ref("")
const category = ref("")
const label = ref("")
const loading = ref(false)
const loadingMore = ref(false)
const error = ref<string | null>(null)
const snapshotFailures = ref(new Set<string>())

const cameraMap = computed(() =>
  new Map(cameras.value.map((camera) => [camera.id, camera]))
)

const categories = computed(() =>
  Array.from(
    new Set(events.value.map((item) => item.category).filter(Boolean))
  ).sort()
)

const activeFilterCount = computed(() =>
  [
    period.value !== "24h",
    Boolean(cameraId.value),
    Boolean(category.value),
    Boolean(label.value.trim())
  ].filter(Boolean).length
)

function periodRange(): [Date | null, Date | null] {
  if (period.value === "all") return [null, null]

  const now = new Date()
  const hours =
    period.value === "24h"
      ? 24
      : period.value === "7d"
        ? 24 * 7
        : 24 * 30

  return [
    new Date(now.getTime() - hours * 60 * 60 * 1000),
    now
  ]
}

function cameraName(item: EventItem): string {
  if (!item.camera_id) return "System"
  return cameraMap.value.get(item.camera_id)?.name ?? "Unknown camera"
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric"
  }).format(new Date(value))
}

function formatTime(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false
  }).format(new Date(value))
}

function formatDuration(item: EventItem): string | null {
  if (!item.ended_at) return null
  const seconds = Math.max(
    0,
    Math.round(
      (new Date(item.ended_at).getTime() -
        new Date(item.started_at).getTime()) /
        1000
    )
  )
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  const remaining = seconds % 60
  return remaining ? `${minutes}m ${remaining}s` : `${minutes}m`
}

function confidenceLabel(value: number | null): string | null {
  return value === null ? null : `${Math.round(value * 100)}%`
}

function pretty(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (match) =>
    match.toUpperCase()
  )
}

function metadataRows(item: EventItem): Array<[string, string]> {
  const rows: Array<[string, string]> = []
  const metadata = item.metadata ?? {}

  const description = metadata.description
  if (typeof description === "string" && description.trim()) {
    rows.push(["Description", description.trim()])
  }

  const plate = metadata.recognized_license_plate
  if (typeof plate === "string" && plate.trim()) {
    rows.push(["Plate", plate.trim()])
  }

  const speed = metadata.average_estimated_speed
  if (typeof speed === "number" || typeof speed === "string") {
    rows.push(["Estimated speed", String(speed)])
  }

  const zones = metadata.zones
  if (Array.isArray(zones) && zones.length) {
    rows.push([
      "Zones",
      zones.filter((value) => typeof value === "string").join(", ")
    ])
  }

  return rows
}

async function refresh(): Promise<void> {
  if (!auth.hasPermission("event.view")) return

  const [from, to] = periodRange()
  loading.value = true
  error.value = null

  try {
    const page = await listEvents({
      cameraId: cameraId.value || null,
      from,
      to,
      category: category.value || null,
      label: label.value.trim() || null,
      limit: 48
    })
    events.value = page.items
    nextCursor.value = page.next_cursor

    if (
      selectedEvent.value &&
      !events.value.some((item) => item.id === selectedEvent.value?.id)
    ) {
      selectedEvent.value = null
    }
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    loading.value = false
  }
}

async function loadMore(): Promise<void> {
  if (!nextCursor.value || loadingMore.value) return

  const [from, to] = periodRange()
  loadingMore.value = true
  try {
    const page = await listEvents({
      cameraId: cameraId.value || null,
      from,
      to,
      category: category.value || null,
      label: label.value.trim() || null,
      cursor: nextCursor.value,
      limit: 48
    })
    const known = new Set(events.value.map((item) => item.id))
    events.value.push(
      ...page.items.filter((item) => !known.has(item.id))
    )
    nextCursor.value = page.next_cursor
  } catch (caught) {
    error.value = errorMessage(caught)
  } finally {
    loadingMore.value = false
  }
}

function resetFilters(): void {
  period.value = "24h"
  cameraId.value = ""
  category.value = ""
  label.value = ""
  void refresh()
}

function selectEvent(item: EventItem): void {
  selectedEvent.value = item
}

function snapshotFailed(eventId: string): void {
  const next = new Set(snapshotFailures.value)
  next.add(eventId)
  snapshotFailures.value = next
}

function canShowSnapshot(item: EventItem): boolean {
  return Boolean(
    item.snapshot_ref && !snapshotFailures.value.has(item.id)
  )
}

function viewRecording(item: EventItem): void {
  if (!item.camera_id) return
  void router.push({
    name: "playback",
    query: {
      camera: item.camera_id,
      at: item.started_at
    }
  })
}

async function loadInitial(): Promise<void> {
  error.value = null
  try {
    if (auth.hasPermission("camera.view")) {
      cameras.value = await listCameras()
    }
  } catch (caught) {
    error.value = errorMessage(caught)
  }
  await refresh()
}

function handleRefreshEvent(): void {
  void refresh()
}

onMounted(() => {
  void loadInitial()
  window.addEventListener("zero-nvr:refresh", handleRefreshEvent)
})

onBeforeUnmount(() => {
  window.removeEventListener("zero-nvr:refresh", handleRefreshEvent)
})
</script>

<template>
  <section class="events-workspace">
    <header class="events-header">
      <div class="events-header__copy">
        <strong>Events</strong>
        <span>
          Provider-neutral activity from cameras and AI integrations.
        </span>
      </div>

      <button
        class="button button--ghost"
        type="button"
        :disabled="loading"
        @click="refresh"
      >
        <UiIcon name="refresh" :size="15" />
        Refresh
      </button>
    </header>

    <div class="events-filters">
      <label class="events-filter">
        <span>Period</span>
        <select v-model="period" @change="refresh">
          <option value="24h">Last 24 hours</option>
          <option value="7d">Last 7 days</option>
          <option value="30d">Last 30 days</option>
          <option value="all">All time</option>
        </select>
      </label>

      <label class="events-filter">
        <span>Camera</span>
        <select v-model="cameraId" @change="refresh">
          <option value="">All cameras</option>
          <option
            v-for="camera in cameras"
            :key="camera.id"
            :value="camera.id"
          >
            {{ camera.name }}
          </option>
        </select>
      </label>

      <label class="events-filter">
        <span>Type</span>
        <select v-model="category" @change="refresh">
          <option value="">All types</option>
          <option
            v-for="item in categories"
            :key="item"
            :value="item"
          >
            {{ pretty(item) }}
          </option>
        </select>
      </label>

      <label class="events-filter events-filter--search">
        <span>Label</span>
        <div class="events-filter-search">
          <UiIcon name="search" :size="14" />
          <input
            v-model="label"
            type="search"
            placeholder="person, car…"
            @keydown.enter="refresh"
          />
        </div>
      </label>

      <button
        v-if="activeFilterCount"
        class="events-clear"
        type="button"
        @click="resetFilters"
      >
        Clear {{ activeFilterCount }}
      </button>
    </div>

    <div v-if="error" class="events-error">
      <UiIcon name="warning" :size="16" />
      <span>{{ error }}</span>
    </div>

    <div class="events-body">
      <div class="events-feed">
        <div v-if="loading && !events.length" class="events-empty">
          <UiIcon name="events" :size="30" />
          <strong>Loading events…</strong>
        </div>

        <div
          v-else-if="!events.length"
          class="events-empty"
        >
          <UiIcon name="events" :size="30" />
          <strong>No events found</strong>
          <span>Try a wider time range or clear the filters.</span>
        </div>

        <div v-else class="event-card-grid">
          <button
            v-for="item in events"
            :key="item.id"
            class="event-card"
            :class="{
              'event-card--selected':
                selectedEvent?.id === item.id
            }"
            type="button"
            @click="selectEvent(item)"
          >
            <div class="event-card__preview">
              <img
                v-if="canShowSnapshot(item)"
                :src="eventSnapshotUrl(item.id)"
                :alt="`${item.label || item.category} event`"
                loading="lazy"
                @error="snapshotFailed(item.id)"
              />
              <div v-else class="event-card__placeholder">
                <UiIcon name="events" :size="24" />
              </div>

              <span class="event-card__time">
                {{ formatTime(item.started_at) }}
              </span>

              <span
                v-if="confidenceLabel(item.confidence)"
                class="event-card__confidence"
              >
                {{ confidenceLabel(item.confidence) }}
              </span>
            </div>

            <div class="event-card__content">
              <div class="event-card__title">
                <strong>{{ item.label || pretty(item.category) }}</strong>
                <span>{{ formatDate(item.started_at) }}</span>
              </div>

              <div class="event-card__meta">
                <span>
                  <UiIcon name="cameras" :size="12" />
                  {{ cameraName(item) }}
                </span>
                <span v-if="item.zone">
                  <UiIcon name="zone" :size="12" />
                  {{ item.zone }}
                </span>
              </div>
            </div>
          </button>
        </div>

        <button
          v-if="nextCursor"
          class="events-load-more"
          type="button"
          :disabled="loadingMore"
          @click="loadMore"
        >
          {{ loadingMore ? "Loading…" : "Load more" }}
        </button>
      </div>

      <aside
        v-if="selectedEvent"
        class="event-detail"
      >
        <header class="event-detail__header">
          <div>
            <strong>
              {{ selectedEvent.label || pretty(selectedEvent.category) }}
            </strong>
            <span>{{ cameraName(selectedEvent) }}</span>
          </div>
          <button
            class="icon-button"
            type="button"
            aria-label="Close event details"
            title="Close"
            @click="selectedEvent = null"
          >
            <UiIcon name="close" :size="16" />
          </button>
        </header>

        <div class="event-detail__preview">
          <img
            v-if="canShowSnapshot(selectedEvent)"
            :src="eventSnapshotUrl(selectedEvent.id)"
            alt="Event snapshot"
            @error="snapshotFailed(selectedEvent.id)"
          />
          <div v-else class="event-detail__placeholder">
            <UiIcon name="events" :size="30" />
          </div>
        </div>

        <div class="event-detail__section">
          <div class="event-detail__time">
            <strong>{{ formatDate(selectedEvent.started_at) }}</strong>
            <span>{{ formatTime(selectedEvent.started_at) }}</span>
          </div>

          <dl class="event-detail__facts">
            <div>
              <dt>Type</dt>
              <dd>{{ pretty(selectedEvent.category) }}</dd>
            </div>
            <div>
              <dt>Source</dt>
              <dd>{{ pretty(selectedEvent.source) }}</dd>
            </div>
            <div v-if="selectedEvent.zone">
              <dt>Zone</dt>
              <dd>{{ selectedEvent.zone }}</dd>
            </div>
            <div v-if="confidenceLabel(selectedEvent.confidence)">
              <dt>Confidence</dt>
              <dd>{{ confidenceLabel(selectedEvent.confidence) }}</dd>
            </div>
            <div v-if="formatDuration(selectedEvent)">
              <dt>Duration</dt>
              <dd>{{ formatDuration(selectedEvent) }}</dd>
            </div>
            <div v-if="selectedEvent.severity">
              <dt>Severity</dt>
              <dd>{{ pretty(selectedEvent.severity) }}</dd>
            </div>
          </dl>
        </div>

        <div
          v-if="metadataRows(selectedEvent).length"
          class="event-detail__section"
        >
          <h3>Details</h3>
          <dl class="event-detail__facts">
            <div
              v-for="[key, value] in metadataRows(selectedEvent)"
              :key="key"
            >
              <dt>{{ key }}</dt>
              <dd>{{ value }}</dd>
            </div>
          </dl>
        </div>

        <div class="event-detail__actions">
          <button
            v-if="selectedEvent.camera_id"
            class="button button--primary"
            type="button"
            @click="viewRecording(selectedEvent)"
          >
            <UiIcon name="playback" :size="15" />
            View recording
          </button>
        </div>
      </aside>
    </div>
  </section>
</template>
