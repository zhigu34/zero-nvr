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


export type LiveLayoutSlots = 1 | 4 | 9 | 16

export interface LiveViewLayoutState {
  slots: LiveLayoutSlots
  camera_ids: string[]
  camera_panel_open: boolean
}

export interface LiveViewLayout {
  id: string
  name: string
  is_default: boolean
  layout: LiveViewLayoutState
  created_at: string
  updated_at: string
}

export function listLiveViewLayouts(): Promise<LiveViewLayout[]> {
  return apiRequest<LiveViewLayout[]>("/live-layouts")
}

export function createLiveViewLayout(input: {
  name: string
  is_default?: boolean
  layout: LiveViewLayoutState
}): Promise<LiveViewLayout> {
  return apiRequest<LiveViewLayout>("/live-layouts", {
    method: "POST",
    json: input
  })
}

export function updateLiveViewLayout(
  layoutId: string,
  changes: {
    name?: string
    is_default?: boolean
    layout?: LiveViewLayoutState
  }
): Promise<LiveViewLayout> {
  return apiRequest<LiveViewLayout>(
    `/live-layouts/${encodeURIComponent(layoutId)}`,
    {
      method: "PATCH",
      json: changes
    }
  )
}

export function deleteLiveViewLayout(
  layoutId: string
): Promise<void> {
  return apiRequest<void>(
    `/live-layouts/${encodeURIComponent(layoutId)}`,
    { method: "DELETE" }
  )
}
