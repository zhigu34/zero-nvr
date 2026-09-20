import { apiRequest } from "./client"

export interface SystemInfo {
  name: string
  version: string
  environment: string
  database_backend: string
}

export interface HealthComponent {
  status: "OK" | "DEGRADED" | "ERROR" | "DISABLED"
  message: string | null
  details: Record<string, unknown>
}

export interface SystemHealth {
  status: "OK" | "DEGRADED" | "ERROR" | "DISABLED"
  components: Record<string, HealthComponent>
}

export interface SystemSettings {
  general: {
    system_name: string
    display_timezone: string
    camera_ntp_servers: string[]
  }
}

export interface CameraNtpDeviceResult {
  device_id: string
  name: string
  status: "UPDATED" | "FAILED"
  error_code: string | null
}

export interface CameraNtpApplyResult {
  mode: "manual" | "dhcp"
  total_devices: number
  updated: number
  failed: number
  results: CameraNtpDeviceResult[]
}

export interface SystemUpdateInfo {
  current_version: string
  latest_version: string | null
  status: "unknown" | "current" | "update_available"
  deployment_method: "deploy.sh"
  automatic_host_mutation: false
  update_command: string
}

export interface RoleSummary {
  id: string
  name: string
  description: string | null
  built_in: boolean
}

export interface Role extends RoleSummary {
  permissions: string[]
}

export interface AdminUser {
  id: string
  username: string
  display_name: string
  email: string | null
  enabled: boolean
  roles: RoleSummary[]
}

export interface CameraScope {
  mode: "inherit" | "all" | "selected" | "none"
  camera_ids: string[]
  camera_group_ids: string[]
}

export interface NotificationTarget {
  id: string
  name: string
  kind: "apprise"
  enabled: boolean
  config: Record<string, unknown>
  url_configured: boolean
}

export interface NotificationDelivery {
  id: string
  alert_id: string
  notification_target_id: string
  state: "PENDING" | "SENDING" | "SENT" | "FAILED" | "SKIPPED"
  attempts: number
  title: string
  body: string
  last_attempt_at: string | null
  delivered_at: string | null
  last_error_code: string | null
  created_at: string
}

export interface FrigateCameraMapping {
  frigate_camera: string
  camera_id: string
}

export interface FrigateProvider {
  configured: boolean
  enabled: boolean
  mode: "managed" | "external"
  instance_id: string
  base_url: string
  camera_map: FrigateCameraMapping[]
  mqtt_enabled: boolean
  mqtt_host: string | null
  mqtt_port: number
  mqtt_topic_prefix: string
  mqtt_tls: boolean
  credentials_configured: boolean
}

export interface FrigateProviderPut {
  enabled: boolean
  mode: "managed" | "external"
  base_url: string
  camera_map: FrigateCameraMapping[]
  mqtt_enabled: boolean
  mqtt_host: string | null
  mqtt_port: number
  mqtt_topic_prefix: string
  mqtt_tls: boolean
  credentials?: {
    http_bearer_token?: string | null
    http_username?: string | null
    http_password?: string | null
    mqtt_username?: string | null
    mqtt_password?: string | null
  } | null
  replace_credentials: boolean
}

export interface BackupPolicy {
  id: string
  name: string
  enabled: boolean
  database_backend: string
  schedule: Record<string, unknown>
  retention: Record<string, unknown>
  verify_after_backup: boolean
  repository_check_schedule: Record<string, unknown>
  include_deployment_config: boolean
  repository_configured: boolean
  credentials_configured: boolean
}

export interface BackupSet {
  id: string
  backup_policy_id: string
  state: string
  reason: string
  started_at: string
  completed_at: string | null
  app_version: string
  schema_revision: string
  database_engine: string
  restic_snapshot_id: string | null
  size_bytes: number | null
  verification_state: string
  last_verified_at: string | null
  error_code: string | null
  sanitized_error: string | null
  created_at: string
}

export interface BackupPage {
  items: BackupSet[]
  next_cursor: string | null
}

export interface AuditEvent {
  id: string
  occurred_at: string
  actor_type: string
  actor_id: string | null
  action: string
  resource_type: string
  resource_id: string | null
  camera_id: string | null
  request_id: string | null
  correlation_id: string | null
  source_ip: string | null
  client_info: Record<string, unknown> | null
  result: string
  reason: string | null
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
  metadata: Record<string, unknown> | null
}

export interface AuditPage {
  items: AuditEvent[]
  next_cursor: string | null
}

export function getSystemInfo(): Promise<SystemInfo> {
  return apiRequest<SystemInfo>("/system/info")
}

export function getSystemHealth(): Promise<SystemHealth> {
  return apiRequest<SystemHealth>("/system/health")
}

export function getSystemSettings(): Promise<SystemSettings> {
  return apiRequest<SystemSettings>("/system/settings")
}

export function patchSystemSettings(
  general: Partial<SystemSettings["general"]>
): Promise<SystemSettings> {
  return apiRequest<SystemSettings>("/system/settings", {
    method: "PATCH",
    json: { general }
  })
}

export function applyCameraNtpSettings(): Promise<CameraNtpApplyResult> {
  return apiRequest<CameraNtpApplyResult>(
    "/system/settings/camera-ntp/apply",
    { method: "POST" }
  )
}

export function getUpdateInfo(): Promise<SystemUpdateInfo> {
  return apiRequest<SystemUpdateInfo>("/system/update-info")
}

export function listUsers(): Promise<AdminUser[]> {
  return apiRequest<AdminUser[]>("/users")
}

export function listPermissions(): Promise<string[]> {
  return apiRequest<string[]>("/permissions")
}

export function listRoles(): Promise<Role[]> {
  return apiRequest<Role[]>("/roles")
}

export function createRole(body: {
  name: string
  description: string | null
  permissions: string[]
}): Promise<Role> {
  return apiRequest<Role>("/roles", {
    method: "POST",
    json: body
  })
}

export function updateRole(
  roleId: string,
  changes: {
    name?: string
    description?: string | null
    permissions?: string[]
  }
): Promise<Role> {
  return apiRequest<Role>(
    `/roles/${encodeURIComponent(roleId)}`,
    {
      method: "PATCH",
      json: changes
    }
  )
}

export function createUser(body: {
  username: string
  display_name: string
  email: string | null
  password: string
  role_ids: string[]
}): Promise<AdminUser> {
  return apiRequest<AdminUser>("/users", {
    method: "POST",
    json: body
  })
}

export function updateUser(
  userId: string,
  changes: {
    display_name?: string
    email?: string | null
    role_ids?: string[]
  }
): Promise<AdminUser> {
  return apiRequest<AdminUser>(
    `/users/${encodeURIComponent(userId)}`,
    {
      method: "PATCH",
      json: changes
    }
  )
}

export function getUserCameraScope(
  userId: string
): Promise<CameraScope> {
  return apiRequest<CameraScope>(
    `/users/${encodeURIComponent(userId)}/camera-scope`
  )
}

export function setUserCameraScope(
  userId: string,
  scope: CameraScope
): Promise<CameraScope> {
  return apiRequest<CameraScope>(
    `/users/${encodeURIComponent(userId)}/camera-scope`,
    {
      method: "PUT",
      json: scope
    }
  )
}

export function getRoleCameraScope(
  roleId: string
): Promise<CameraScope> {
  return apiRequest<CameraScope>(
    `/roles/${encodeURIComponent(roleId)}/camera-scope`
  )
}

export function setRoleCameraScope(
  roleId: string,
  scope: Omit<CameraScope, "mode"> & {
    mode: "all" | "selected" | "none"
  }
): Promise<CameraScope> {
  return apiRequest<CameraScope>(
    `/roles/${encodeURIComponent(roleId)}/camera-scope`,
    {
      method: "PUT",
      json: scope
    }
  )
}

export function resetUserPassword(
  userId: string,
  newPassword: string
): Promise<AdminUser> {
  return apiRequest<AdminUser>(
    `/users/${encodeURIComponent(userId)}/reset-password`,
    {
      method: "POST",
      json: { new_password: newPassword }
    }
  )
}

export function setUserEnabled(
  userId: string,
  enabled: boolean
): Promise<AdminUser> {
  return apiRequest<AdminUser>(
    `/users/${encodeURIComponent(userId)}/${enabled ? "enable" : "disable"}`,
    { method: "POST" }
  )
}

export function listNotificationTargets(): Promise<NotificationTarget[]> {
  return apiRequest<NotificationTarget[]>("/notification-targets")
}

export function createNotificationTarget(
  name: string,
  url: string
): Promise<NotificationTarget> {
  return apiRequest<NotificationTarget>("/notification-targets", {
    method: "POST",
    json: {
      name,
      enabled: true,
      config: {},
      url
    }
  })
}

export function updateNotificationTarget(
  targetId: string,
  changes: Record<string, unknown>
): Promise<NotificationTarget> {
  return apiRequest<NotificationTarget>(
    `/notification-targets/${encodeURIComponent(targetId)}`,
    {
      method: "PATCH",
      json: changes
    }
  )
}

export function deleteNotificationTarget(
  targetId: string
): Promise<void> {
  return apiRequest<void>(
    `/notification-targets/${encodeURIComponent(targetId)}`,
    { method: "DELETE" }
  )
}

export function testNotificationTarget(
  targetId: string
): Promise<{ ok: true }> {
  return apiRequest<{ ok: true }>(
    `/notification-targets/${encodeURIComponent(targetId)}/test`,
    { method: "POST" }
  )
}

export function listNotificationDeliveries(): Promise<NotificationDelivery[]> {
  return apiRequest<NotificationDelivery[]>(
    "/notification-deliveries?limit=30"
  )
}

export function getFrigateProvider(): Promise<FrigateProvider> {
  return apiRequest<FrigateProvider>("/system/integrations/frigate")
}

export function putFrigateProvider(
  body: FrigateProviderPut
): Promise<FrigateProvider> {
  return apiRequest<FrigateProvider>(
    "/system/integrations/frigate",
    {
      method: "PUT",
      json: body
    }
  )
}

export function testFrigateProvider(): Promise<{
  ok: true
  version: string | null
}> {
  return apiRequest(
    "/system/integrations/frigate/test",
    { method: "POST" }
  )
}

export function backfillFrigate(
  lookbackSeconds = 600
): Promise<{ queued: true; lookback_seconds: number }> {
  return apiRequest(
    "/system/integrations/frigate/backfill",
    {
      method: "POST",
      json: { lookback_seconds: lookbackSeconds }
    }
  )
}

export function listBackupPolicies(): Promise<BackupPolicy[]> {
  return apiRequest<BackupPolicy[]>("/backups/policies")
}

export function createBackupPolicy(body: {
  name: string
  enabled: boolean
  repository: string
  credentials: {
    password: string
    environment: Record<string, string>
  }
  initialize_if_missing: boolean
  database_backend: string
  schedule: Record<string, unknown>
  retention: Record<string, unknown>
  verify_after_backup: boolean
  repository_check_schedule: Record<string, unknown>
  include_deployment_config: boolean
}): Promise<BackupPolicy> {
  return apiRequest<BackupPolicy>("/backups/policies", {
    method: "POST",
    json: body
  })
}

export function updateBackupPolicy(
  policyId: string,
  changes: {
    name?: string
    enabled?: boolean
    repository?: string
    credentials?: {
      password?: string
      environment?: Record<string, string>
    }
    initialize_if_missing?: boolean
    schedule?: Record<string, unknown>
    retention?: Record<string, unknown>
    verify_after_backup?: boolean
    repository_check_schedule?: Record<string, unknown>
    include_deployment_config?: boolean
  }
): Promise<BackupPolicy> {
  return apiRequest<BackupPolicy>(
    `/backups/policies/${encodeURIComponent(policyId)}`,
    {
      method: "PATCH",
      json: changes
    }
  )
}

export function listBackups(): Promise<BackupPage> {
  return apiRequest<BackupPage>("/backups?limit=50")
}

export function runBackup(policyId: string): Promise<BackupSet> {
  return apiRequest<BackupSet>("/backups/run", {
    method: "POST",
    json: {
      policy_id: policyId,
      reason: "manual"
    }
  })
}

export function verifyBackup(backupId: string): Promise<BackupSet> {
  return apiRequest<BackupSet>(
    `/backups/${encodeURIComponent(backupId)}/verify`,
    { method: "POST" }
  )
}

export function listAuditEvents(): Promise<AuditPage> {
  return apiRequest<AuditPage>("/audit?limit=100")
}
