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


export interface ExportShare {
  id: string
  export_id: string
  expires_at: string
  revoked_at: string | null
  max_downloads: number | null
  download_count: number
  last_download_at: string | null
  password_protected: boolean
  created_at: string
}

export interface ExportShareCreated extends ExportShare {
  token: string
  download_path: string
}

export function createExportShare(
  exportId: string,
  body: {
    password: string | null
    expires_in_hours: number
    max_downloads: number | null
  }
): Promise<ExportShareCreated> {
  return apiRequest<ExportShareCreated>(
    `/exports/${encodeURIComponent(exportId)}/shares`,
    {
      method: "POST",
      json: body
    }
  )
}

export function listExportShares(
  exportId: string
): Promise<ExportShare[]> {
  return apiRequest<ExportShare[]>(
    `/exports/${encodeURIComponent(exportId)}/shares`
  )
}

export function revokeExportShare(
  exportId: string,
  shareId: string
): Promise<void> {
  return apiRequest<void>(
    `/exports/${encodeURIComponent(exportId)}/shares/${encodeURIComponent(shareId)}`,
    { method: "DELETE" }
  )
}
