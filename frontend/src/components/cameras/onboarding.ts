/**
 * Shared vocabulary for the camera onboarding panel and the mode-specific flows
 * it renders.
 *
 * These live here rather than in the panel because a child component needs them
 * too: duplicating the union is how the two copies drift apart, and TypeScript
 * then reports the mismatch as "two different types with this name exist".
 */

export type OnboardingMode = "onvif" | "rtsp" | "batch_file"

/** Which async action is in flight, or null when idle. */
export type OnboardingWorkingAction =
  | "discover"
  | "inspect"
  | "import"
  | "batch"
  | "file-batch"
  | "test"
  | "create"
  | null

/** Outcome of one device inside a batch import run. */
export type BatchResultState =
  | "pending"
  | "running"
  | "success"
  | "partial"
  | "review"
  | "failed"

export interface BatchResult {
  candidate_id: string
  label: string
  state: BatchResultState
  message: string
  camera_ids: string[]
}

/** Per-device credential override collected before a batch import. */
export interface BatchCredentialOverride {
  username: string
  password: string
}

/** How a batch import should treat the cameras' clocks. */
export type BatchTimeSyncMode = "monitor" | "manage_ntp" | "ignore"

/** A CSV row can describe either an ONVIF device or a plain RTSP camera. */
export type FileImportKind = "onvif" | "rtsp"

export interface FileImportRow {
  line: number
  kind: FileImportKind | null
  name: string
  host: string
  onvif_port: number
  rtsp_port: number
  username: string
  password: string
  main_path: string
  sub_path: string
  main_url: string
  sub_url: string
  location: string
  storage_label: string
  errors: string[]
}

export interface FileBatchResult {
  line: number
  label: string
  state: BatchResultState
  message: string
  camera_ids: string[]
}
