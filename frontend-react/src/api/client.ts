/**
 * Minimal typed fetch wrapper over the existing `/api/v1` contract.
 *
 * Two things it must get right, both inherited from the Vue client:
 *
 * 1. `credentials: "include"` — the session cookie is HttpOnly, so every
 *    request depends on it. Requests go through the vite dev proxy rather
 *    than an absolute backend origin precisely so the cookie stays
 *    first-party.
 * 2. The error envelope. `ApiError` is serialised by
 *    `core/errors/api_error.py` as `{error:{code,message,details,request_id}}`,
 *    while FastAPI's own RequestValidationError emits `{detail:[...]}`. Both
 *    shapes have to surface as a usable message, and the `code` is what the
 *    UI branches on (e.g. `invalid_credentials`).
 */

export type ApiErrorBody = {
  error: {
    code: string
    message: string
    details?: Record<string, unknown> | null
    request_id?: string | null
  }
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: Record<string, unknown> | null
  readonly requestId: string | null

  constructor(
    status: number,
    code: string,
    message: string,
    details: Record<string, unknown> | null = null,
    requestId: string | null = null,
  ) {
    super(message)
    this.name = "ApiError"
    this.status = status
    this.code = code
    this.details = details
    this.requestId = requestId
  }

  /** 401/403 from a session check means "no usable session", not "wrong password". */
  get isAuthFailure() {
    return this.status === 401 || this.status === 403
  }
}

function flattenValidationDetail(body: unknown): string | null {
  if (!body || typeof body !== "object") return null
  const detail = (body as { detail?: unknown }).detail
  if (!Array.isArray(detail)) return null
  const parts: string[] = []
  for (const item of detail) {
    if (item && typeof item === "object" && "msg" in item) {
      const loc = (item as { loc?: unknown[] }).loc
      const field = Array.isArray(loc) ? loc.filter((l) => l !== "body").join(".") : ""
      const msg = String((item as { msg: unknown }).msg)
      parts.push(field ? `${field}: ${msg}` : msg)
    }
  }
  return parts.length ? parts.join("；") : null
}

async function toApiError(response: Response): Promise<ApiError> {
  let body: unknown = null
  try {
    body = await response.json()
  } catch {
    body = null
  }

  const envelope = (body as Partial<ApiErrorBody> | null)?.error
  if (envelope && typeof envelope.code === "string") {
    return new ApiError(
      response.status,
      envelope.code,
      envelope.message || response.statusText,
      (envelope.details as Record<string, unknown> | null) ?? null,
      envelope.request_id ?? null,
    )
  }

  const validation = flattenValidationDetail(body)
  return new ApiError(
    response.status,
    response.status === 422 ? "validation_error" : "http_error",
    validation || response.statusText || `HTTP ${response.status}`,
  )
}

type RequestOptions = {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE"
  body?: unknown
  signal?: AbortSignal
}

const BASE = "/api/v1"

export async function request<T>(
  path: string,
  { method = "GET", body, signal }: RequestOptions = {},
): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    method,
    credentials: "include",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  })

  if (!response.ok) throw await toApiError(response)
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export const api = {
  get: <T,>(path: string, signal?: AbortSignal) =>
    request<T>(path, { signal }),
  post: <T,>(path: string, body?: unknown, signal?: AbortSignal) =>
    request<T>(path, { method: "POST", body, signal }),
  put: <T,>(path: string, body?: unknown) =>
    request<T>(path, { method: "PUT", body }),
  patch: <T,>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body }),
  del: <T,>(path: string) => request<T>(path, { method: "DELETE" }),
}
