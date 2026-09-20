import { apiRequest } from "./client"

export interface EventItem {
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

export interface EventPage {
  items: EventItem[]
  next_cursor: string | null
}

export interface EventQuery {
  cameraId?: string | null
  from?: Date | null
  to?: Date | null
  source?: string | null
  category?: string | null
  label?: string | null
  zone?: string | null
  confidence?: number | null
  severity?: string | null
  cursor?: string | null
  limit?: number
}

export function listEvents(query: EventQuery = {}): Promise<EventPage> {
  const params = new URLSearchParams()

  if (query.cameraId) params.set("camera_id", query.cameraId)
  if (query.from) params.set("from", query.from.toISOString())
  if (query.to) params.set("to", query.to.toISOString())
  if (query.source) params.set("source", query.source)
  if (query.category) params.set("category", query.category)
  if (query.label) params.set("label", query.label)
  if (query.zone) params.set("zone", query.zone)
  if (query.confidence !== null && query.confidence !== undefined) {
    params.set("confidence", String(query.confidence))
  }
  if (query.severity) params.set("severity", query.severity)
  if (query.cursor) params.set("cursor", query.cursor)
  params.set("limit", String(query.limit ?? 48))

  return apiRequest<EventPage>(`/events?${params}`)
}

export function eventSnapshotUrl(eventId: string): string {
  return `/api/v1/events/${encodeURIComponent(eventId)}/snapshot`
}
