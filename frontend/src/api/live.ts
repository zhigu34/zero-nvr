import { apiRequest } from "./client"

export type LiveQuality = "auto" | "high" | "low"

export interface CameraLiveStream {
  camera_id: string
  profile_id: string
  purpose: "LIVE_HIGH" | "LIVE_LOW" | "RECORD"
  transport: "hls"
  hls_url: string
  expires_at: string
  codec: string | null
  width: number | null
  height: number | null
  fps: number | null
  has_audio: boolean
}

export function getCameraLiveStream(
  cameraId: string,
  quality: LiveQuality
): Promise<CameraLiveStream> {
  const params = new URLSearchParams({ quality })
  return apiRequest<CameraLiveStream>(
    `/cameras/${encodeURIComponent(cameraId)}/live?${params}`
  )
}


export function cameraSnapshotUrl(cameraId: string): string {
  return `/api/v1/cameras/${encodeURIComponent(cameraId)}/snapshot`
}
