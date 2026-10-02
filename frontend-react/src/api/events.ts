/**
 * Event read contract. Mirrors `backend/app/modules/events/schemas.py`.
 *
 * `GET /events` is **cursor** paginated (`next_cursor`, limit 1–200), not
 * offset — so the table must not send `page=2`. Filters use the wire aliases
 * `from` / `to` / `confidence`, which differ from the Python parameter names.
 *
 * `EventView` carries `camera_id` but no camera name, so any list showing a
 * camera column has to join against `GET /cameras` on the client.
 */
import { api } from "./client"

export type EventView = {
  id: string
  source: string
  source_instance_id: string | null
  source_event_id: string | null
  camera_id: string | null
  category: string
  label: string | null
  started_at: string
  ended_at: string | null
  confidence: number | null
  severity: string | null
  zone: string | null
  snapshot_ref: string | null
  correlation_id: string | null
  metadata: Record<string, unknown>
  created_at: string
  updated_at: string
}

export type EventPage = {
  items: EventView[]
  next_cursor: string | null
}

export type EventFilters = {
  cameraId?: string
  from?: string
  to?: string
  source?: string
  category?: string
  label?: string
  zone?: string
  minConfidence?: number
  severity?: string
  cursor?: string
  limit?: number
}

export function listEvents(
  filters: EventFilters = {},
  signal?: AbortSignal,
) {
  const qs = new URLSearchParams()
  if (filters.cameraId) qs.set("camera_id", filters.cameraId)
  // Wire aliases, not the python parameter names.
  if (filters.from) qs.set("from", filters.from)
  if (filters.to) qs.set("to", filters.to)
  if (filters.source) qs.set("source", filters.source)
  if (filters.category) qs.set("category", filters.category)
  if (filters.label) qs.set("label", filters.label)
  if (filters.zone) qs.set("zone", filters.zone)
  if (filters.minConfidence !== undefined) {
    qs.set("confidence", String(filters.minConfidence))
  }
  if (filters.severity) qs.set("severity", filters.severity)
  if (filters.cursor) qs.set("cursor", filters.cursor)
  qs.set("limit", String(filters.limit ?? 50))
  return api.get<EventPage>(`/events?${qs}`, signal)
}

export function getEvent(id: string, signal?: AbortSignal) {
  return api.get<EventView>(`/events/${id}`, signal)
}

export const CATEGORY_LABEL: Record<string, string> = {
  person: "人员",
  vehicle: "车辆",
  animal: "动物",
  motion: "移动侦测",
  intrusion: "区域入侵",
  line: "越线",
}

export function categoryLabel(category: string): string {
  return CATEGORY_LABEL[category] ?? category
}
