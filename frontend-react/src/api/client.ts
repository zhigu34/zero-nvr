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
  /**
   * Extra headers. Added for `Idempotency-Key` on export creation, which is a
   * property of the request rather than of its payload — growing the body
   * shape to carry it would put a transport concern in the wire contract.
   */
  headers?: Record<string, string>
}

const BASE = "/api/v1"

/** A non-JSON success body: bytes plus the filename the server suggested. */
export interface BinaryResponse {
  blob: Blob
  /**
   * From `Content-Disposition`, or `null`.
   *
   * The recovery kit sets `attachment; filename="….znrk"`; without this a
   * browser saves it as `download`. Null when the header is absent — the caller
   * then supplies its own name rather than inventing one silently.
   */
  filename: string | null
}

function filenameFromDisposition(header: string | null): string | null {
  if (!header) return null
  const quoted = header.match(/filename="([^"]*)"/)
  if (quoted?.[1]) return quoted[1]
  const bare = header.match(/filename=([^;]+)/)
  return bare?.[1]?.trim() || null
}

export async function request<T>(
  path: string,
  { method, body, signal, headers }: RequestOptions = {},
): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    method: method ?? "GET",
    credentials: "include",
    headers: {
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      ...headers,
    },
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
  postWithHeaders: <T,>(
    path: string,
    body: unknown,
    headers: Record<string, string>,
  ) => request<T>(path, { method: "POST", body, headers }),

  /**
   * A POST whose success body is not JSON.
   *
   * The recovery kit is exactly this: an authenticated POST with a JSON body
   * that answers with `application/octet-stream`. It cannot be a navigation —
   * an `<a href>` or `window.open` issues a GET — so the client has to fetch
   * the bytes and hand them to a blob download.
   */
  postBlob: async (
    path: string,
    body: unknown,
    signal?: AbortSignal,
  ): Promise<BinaryResponse> => {
    const response = await fetch(`${BASE}${path}`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    })
    if (!response.ok) throw await toApiError(response)
    return {
      blob: await response.blob(),
      filename: filenameFromDisposition(
        response.headers.get("Content-Disposition"),
      ),
    }
  },
}
