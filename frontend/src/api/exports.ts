import { apiRequest } from "./client"

export interface ExportJob {
  id: string
  camera_id: string
  requested_by: string | null
  start_at: string
  end_at: string
  requested_duration_ms: number
  format: string
  codec_mode: string
  gap_policy: string
  state: string
  size_bytes: number | null
  actual_duration_ms: number | null
  selected_segment_count: number | null
  metadata: Record<string, unknown>
  error_code: string | null
  expires_at: string
  started_at: string | null
  completed_at: string | null
  created_at: string
}

export interface ExportPage {
  items: ExportJob[]
  next_cursor: string | null
}

export function createExport(body: {
  camera_id: string
  start_at: string
  end_at: string
  format: "mp4"
  codec_mode: "auto" | "copy" | "h264"
  gap_policy: "skip" | "fail"
}): Promise<ExportJob> {
  return apiRequest<ExportJob>("/exports", {
    method: "POST",
    headers: {
      "Idempotency-Key": crypto.randomUUID()
    },
    json: body
  })
}

export function getExport(exportId: string): Promise<ExportJob> {
  return apiRequest<ExportJob>(
    `/exports/${encodeURIComponent(exportId)}`
  )
}

export function listExports(): Promise<ExportPage> {
  return apiRequest<ExportPage>("/exports?limit=50")
}

export function deleteExport(exportId: string): Promise<void> {
  return apiRequest<void>(
    `/exports/${encodeURIComponent(exportId)}`,
    { method: "DELETE" }
  )
}

export function exportDownloadUrl(exportId: string): string {
  return `/api/v1/exports/${encodeURIComponent(exportId)}/download`
}
