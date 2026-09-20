import { apiRequest } from "./client"

export interface AlertItem {
  id: string
  policy_id: string | null
  event_id: string
  camera_id: string | null
  severity: string
  title: string
  message: string | null
  state: "OPEN" | "ACKNOWLEDGED" | "RESOLVED"
  acknowledged_at: string | null
  acknowledged_by: string | null
  resolved_at: string | null
  created_at: string
}

export interface AlertPage {
  items: AlertItem[]
  next_cursor: string | null
}

export function listAlerts(query: {
  state?: string | null
  limit?: number
} = {}): Promise<AlertPage> {
  const params = new URLSearchParams()
  if (query.state) params.set("state", query.state)
  params.set("limit", String(query.limit ?? 20))
  return apiRequest<AlertPage>(`/alerts?${params}`)
}

export function acknowledgeAlert(
  alertId: string
): Promise<AlertItem> {
  return apiRequest<AlertItem>(
    `/alerts/${encodeURIComponent(alertId)}/acknowledge`,
    { method: "POST" }
  )
}


export interface AlertPolicy {
  id: string
  name: string
  enabled: boolean
  severity: "info" | "warning" | "critical"
  match: Record<string, unknown>
  actions: Record<string, unknown>
  cooldown_seconds: number
  created_at: string
  updated_at: string
}

export function listAlertPolicies(): Promise<AlertPolicy[]> {
  return apiRequest<AlertPolicy[]>("/alert-policies")
}

export function createAlertPolicy(body: {
  name: string
  enabled: boolean
  severity: "info" | "warning" | "critical"
  match: Record<string, unknown>
  actions: Record<string, unknown>
  cooldown_seconds: number
}): Promise<AlertPolicy> {
  return apiRequest<AlertPolicy>("/alert-policies", {
    method: "POST",
    json: body
  })
}

export function updateAlertPolicy(
  policyId: string,
  changes: Record<string, unknown>
): Promise<AlertPolicy> {
  return apiRequest<AlertPolicy>(
    `/alert-policies/${encodeURIComponent(policyId)}`,
    {
      method: "PATCH",
      json: changes
    }
  )
}

export function deleteAlertPolicy(policyId: string): Promise<void> {
  return apiRequest<void>(
    `/alert-policies/${encodeURIComponent(policyId)}`,
    { method: "DELETE" }
  )
}
