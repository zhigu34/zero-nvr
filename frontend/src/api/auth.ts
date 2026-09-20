import { apiRequest } from "./client"

export interface SessionSummary {
  id: string
  created_at: string
  last_seen_at: string
  expires_at: string
  current: boolean
  client_info: Record<string, unknown> | null
}

export function listSessions(): Promise<SessionSummary[]> {
  return apiRequest<SessionSummary[]>("/sessions")
}

export function revokeSession(sessionId: string): Promise<void> {
  return apiRequest<void>(
    `/sessions/${encodeURIComponent(sessionId)}`,
    { method: "DELETE" }
  )
}


export function requestPasswordReset(
  identifier: string
): Promise<{ accepted: true }> {
  return apiRequest<{ accepted: true }>(
    "/auth/password-reset/request",
    {
      method: "POST",
      json: { identifier }
    }
  )
}

export function completePasswordReset(
  token: string,
  newPassword: string
): Promise<{ ok: true }> {
  return apiRequest<{ ok: true }>(
    "/auth/password-reset/complete",
    {
      method: "POST",
      json: {
        token,
        new_password: newPassword
      }
    }
  )
}
