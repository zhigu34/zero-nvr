export interface ApiErrorBody {
  error?: {
    code?: string
    message?: string
    details?: Record<string, unknown>
    request_id?: string | null
  }
}

export class ApiClientError extends Error {
  readonly status: number
  readonly code: string
  readonly details: Record<string, unknown>
  readonly requestId: string | null

  constructor(
    status: number,
    code: string,
    message: string,
    details: Record<string, unknown> = {},
    requestId: string | null = null
  ) {
    super(message)
    this.name = "ApiClientError"
    this.status = status
    this.code = code
    this.details = details
    this.requestId = requestId
  }
}

interface ApiRequestOptions extends Omit<RequestInit, "body"> {
  json?: unknown
}

export async function apiRequest<T>(
  path: string,
  options: ApiRequestOptions = {}
): Promise<T> {
  const headers = new Headers(options.headers)
  headers.set("Accept", "application/json")

  let body: BodyInit | undefined
  if (options.json !== undefined) {
    headers.set("Content-Type", "application/json")
    body = JSON.stringify(options.json)
  }

  const response = await fetch(
    path.startsWith("/api/") ? path : `/api/v1${path}`,
    {
      ...options,
      headers,
      body,
      credentials: "same-origin"
    }
  )

  if (response.status === 204) {
    return undefined as T
  }

  const contentType = response.headers.get("content-type") ?? ""
  const payload = contentType.includes("application/json")
    ? ((await response.json()) as ApiErrorBody & T)
    : undefined

  if (!response.ok) {
    const error = payload?.error
    throw new ApiClientError(
      response.status,
      error?.code ?? "http_error",
      error?.message ?? `Request failed with status ${response.status}`,
      error?.details ?? {},
      error?.request_id ?? response.headers.get("x-request-id")
    )
  }

  return payload as T
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Unexpected error."
}
