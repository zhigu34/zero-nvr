# Spec 0011 — Authentication, Camera-Scoped Authorization, and Audit

Status: **accepted**

## Goal

Define a secure but manageable access-control model for zero-nvr covering:

- local user authentication;
- roles and permissions;
- camera/group visibility scope;
- live view and historical playback authorization;
- manual recording and camera control;
- recording export/download, lock, and delete;
- system/storage/integration administration;
- session revocation;
- audit records for sensitive actions.

Core rule:

> Roles define what a principal may do. Resource scope defines which cameras/resources the principal may do it to.

## Initial authentication model

Initial V2 provides local zero-nvr accounts.

The first production release supports both local accounts and OIDC/SSO behind the same Principal/Role/Permission model. Local accounts remain available for bootstrap and break-glass administration.

Anonymous access is disabled by default.

First-run setup creates the first administrator explicitly. Do not ship a universal/default administrator password.

## User

Conceptual model:

```text
User
  id
  username
  display_name
  email
  email_verified_at
  password_hash
  enabled
  must_change_password
  last_login_at
  created_at
  updated_at
```

Passwords are stored only as a modern password hash.

Initial recommendation:

```text
Argon2id
```

Never store plaintext or reversible passwords.

Password policy should reject obviously unsafe credentials while avoiding arbitrary composition rules that harm usability. Minimum length and known-compromised-password checks may be added at implementation time.

## Principal abstraction

Authorization code should reason about a Principal rather than assume every caller is an interactive local user.

Conceptually:

```text
Principal
  kind = user | service
  id
```

This allows future API/service identities without bypassing ACL checks.

External integrations do not inherit administrator access implicitly.

## Role + permission model

A Role contains permissions.

```text
Role
  id
  name
  description
  built_in
  created_at
  updated_at
```

```text
RolePermission
  role_id
  permission
```

A User may have one or more roles.

```text
UserRole
  user_id
  role_id
```

Effective permissions are the union of enabled assigned roles.

No implicit deny/allow ordering is required in initial V2. Keep the model understandable.

## Initial permissions

Permissions are action-oriented.

### Camera / live

```text
camera.view
live.view
camera.manage
camera.ptz
```

### Recording

```text
recording.view
recording.manual
recording.settings
recording.export
recording.download
recording.lock
recording.delete
```

### Events / alerts

```text
event.view
alert.view
alert.acknowledge
alert.manage
notification.view
notification.manage
```

### Storage

```text
storage.view
storage.manage
```

### System / security

```text
system.view
system.manage
user.manage
role.manage
audit.view
integration.manage
backup.view
backup.manage
backup.restore
backup.export
update.view
update.manage
database.migrate
```

Permissions may be refined later only when a real security boundary requires it. Avoid creating dozens of nearly identical permissions prematurely.

## Built-in roles

Initial V2 provides three understandable built-in roles.

### Administrator

Full system authority:

```text
all permissions
all camera scope
```

Administrator may manage users, roles, system settings, storage, integrations, cameras, recordings, and audit viewing.

### Operator

Operational NVR use without security/system administration.

Recommended permissions:

```text
camera.view
live.view
camera.ptz

recording.view
recording.manual
recording.export
recording.download
recording.lock

event.view
alert.view
alert.acknowledge
notification.view
storage.view
system.view
```

Operator does not receive by default:

```text
user.manage
role.manage
system.manage
storage.manage
integration.manage
recording.delete
recording.settings
camera.manage
```

### Viewer

Read-oriented use:

```text
camera.view
live.view
recording.view
event.view
alert.view
```

No recording mutation, export/download, lock, delete, PTZ, or administration by default.

Built-in role definitions may be copied into custom roles if more precise policy is needed. Built-in roles themselves should not be silently mutated into unrelated semantics.

## Why delete is separate from lock/export

These actions have different risk:

```text
view
export/download
lock
delete
```

A user allowed to view footage should not automatically be able to extract or destroy it.

Therefore:

- playback requires recording.view;
- creating an export requires recording.export;
- downloading an already-authorized export requires recording.download;
- indefinite retention lock/unlock requires recording.lock;
- destructive media deletion requires recording.delete.

## Camera access scope

Permissions alone do not make all cameras visible.

Camera scope is evaluated separately.

Initial scope modes:

```text
all
selected_groups
selected_cameras
none
```

Conceptual assignment:

```text
PrincipalCameraScope
  principal_type
  principal_id
  scope_mode
  created_at
  updated_at
```

Selected resources are represented through scope entries.

```text
PrincipalCameraScopeEntry
  principal_type
  principal_id
  camera_id nullable
  camera_group_id nullable
```

A user with camera.view but scope=none sees no cameras.

## CameraGroup

CameraGroup provides manageable resource grouping.

```text
CameraGroup
  id
  name
  description
  created_at
  updated_at
```

```text
CameraGroupMember
  camera_group_id
  camera_id
```

Examples:

```text
Home
Office
Warehouse
Floor 1
Public Areas
Restricted
```

A camera may belong to multiple groups.

Camera groups are authorization/organization metadata and do not change Camera identity or storage paths.

## Effective authorization

A camera-scoped request is permitted only when both are true:

```text
required permission exists
AND
camera is inside effective scope
```

Example:

```text
recording.download permission = yes
camera scope includes Front Door = yes
    -> download allowed

recording.download permission = yes
camera scope excludes Warehouse = yes
    -> download denied
```

Do not infer camera access from frontend visibility alone. Backend authorization is authoritative.

## System-wide permissions

Some permissions are not camera-scoped, for example:

```text
user.manage
role.manage
system.manage
storage.manage
integration.manage
audit.view
```

These are checked globally.

Camera scope does not grant system administration.

## API enforcement

Authorization occurs in the control plane before business operations.

Conceptual request flow:

```text
authenticate principal
      ↓
resolve effective permissions
      ↓
resolve resource scope
      ↓
authorize action
      ↓
execute domain operation
      ↓
write audit record when required
```

Business services should receive an authorized Actor/Principal context rather than repeatedly trusting user-supplied IDs.

Never rely on frontend button hiding as security.

## WebSocket and live media authorization

Live-view authorization must survive beyond the initial REST call.

Flow:

```text
authenticated request
   ↓
camera.view + live.view + camera scope
   ↓
issue short-lived media session/token
   ↓
ZLM/proxy/playback endpoint validates token/session
```

A media URL must not become a permanent bearer credential.

Tokens should be:

- short lived;
- camera/session scoped;
- revocable where practical;
- free of camera credentials.

Direct camera RTSP credentials are never exposed to normal users.

## Historical playback authorization

Timeline queries require:

```text
camera.view
recording.view
camera in scope
```

PlaybackResolver must re-check authorization when issuing playable media access, especially for remote/signed URLs.

A user who loses camera scope must not retain indefinite access through a previously copied long-lived playback URL.

## Export and download authorization

Export is an asynchronous derived-media job.

Creating an export requires:

```text
recording.export
AND
scope to every included camera
```

The export stores actor/request metadata.

Downloading the generated artifact requires recording.download and authorization to the export/job/resource.

Exports should use expiring authenticated/signed delivery rather than public permanent URLs by default.

## Recording lock authorization

Lock/unlock uses recording.lock.

Every lock/unlock operation records:

- actor;
- affected camera/segments/session/event/range;
- previous lock state;
- new lock state;
- reason if supplied.

A user cannot lock footage outside camera scope.

## Recording deletion authorization

Deletion is high risk.

Required:

```text
recording.delete
AND
camera scope
```

Deletion should be explicit and auditable.

Recommended UX:

- show affected time range/camera;
- show whether another verified copy exists;
- show whether footage is user-locked;
- require deliberate confirmation;
- do not overload ordinary "remove from view" actions with physical deletion.

A normal delete request must not silently bypass user locks. If administrator override of a lock is supported, it is a separate explicit destructive path and is audited as such.

## Camera management vs viewing

camera.manage covers changes such as:

- create/remove Camera configuration;
- modify connection URI/credentials reference;
- change stream/profile selection;
- change device-specific management options.

camera.view alone must never reveal stored credentials.

camera.ptz is separate because physical camera movement can be more sensitive than passive viewing.

## Recording settings authorization

recording.settings covers:

- recording mode;
- schedules;
- pre/post-roll;
- segment duration;
- retention policy assignment;
- recording StoragePool selection.

recording.manual covers only explicit start/stop of the manual RecordingIntent.

A user who may start manual recording does not automatically gain permission to change persistent recording policy.

## Storage administration

storage.view allows health/capacity/status viewing.

storage.manage is required for:

- create/update StorageTarget;
- create/update StoragePool;
- drain target;
- enable/disable write target;
- archive credentials/configuration;
- destructive storage-target removal/migration choices.

Unique-media safety rules from Spec 0010 still apply even to administrators.

Authorization never bypasses domain safety invariants.

## Integration identities

Home Assistant, MQTT, webhook, and future service integrations should use dedicated service credentials/principals rather than an administrator's browser session.

A service principal receives only required permissions and camera scope.

Example:

```text
Home Assistant service principal
  camera scope: Front Door + Garage
  permission:
    camera.view
    recording.manual
    event.view
```

Compromise of one integration should not imply full NVR administration.

## UserSession

Interactive login sessions are persisted/revocable.

Conceptual model:

```text
UserSession
  id
  user_id
  created_at
  last_seen_at
  expires_at
  revoked_at
  client_info
```

Recommended token model:

- short-lived access token/session proof;
- longer-lived refresh/session record;
- server-side revocation through UserSession.

Exact token format is implementation-specific.

Disabling a user revokes active sessions.

Password change should allow revoking other sessions.


## Password reset and account recovery

The first production release includes SMTP-backed self-service password reset, administrator-issued reset tokens, and host-local emergency recovery.

### Self-service email reset

Public reset request behavior is non-enumerating:

```text
If an eligible account exists, reset instructions have been sent.
```

For an eligible enabled local account with a usable email address:

1. generate a high-entropy one-time token;
2. store only a token hash;
3. persist user_id, expires_at, used_at, requested_at, and safe request metadata;
4. enqueue an SMTP reset email;
5. user presents token and new password;
6. atomically mark token used;
7. replace Argon2id password hash;
8. revoke prior sessions by default;
9. write AuditEvent.

Conceptual model:

```text
PasswordResetToken
  id
  user_id
  token_hash
  requested_at
  expires_at
  used_at
  requested_ip
  created_by_actor_id nullable
```

A short configurable lifetime such as 15 minutes is the initial default.

### Administrator-issued reset

A user administrator may create an expiring one-time reset token for an account. The administrator never sees the old password and does not receive any reversible password representation.

### Host-local emergency recovery

If all administrators are locked out, zero-nvr exposes a local CLI/break-glass workflow requiring host/container shell access.

Conceptual command:

```text
zero-nvr admin create-password-reset <username>
```

or an interactive reset that reads the new password from a TTY rather than process arguments.

No unauthenticated remote administrator-reset endpoint is provided by default.

## SMTP dependency for account recovery

SMTP configuration is a first-production-release platform capability rather than future work.

Password reset email requires a configured/healthy SMTP channel. If SMTP is unavailable, administrators can still use administrator-issued or host-local recovery methods.

SMTP credentials are stored through SecretStore. SMTP delivery and retry semantics are shared with the notification subsystem.

## Multi-factor authentication

The first production release supports TOTP MFA for local interactive users.

Conceptual fields/models:

```text
UserMfa
  user_id
  enabled
  totp_secret_ref
  enrolled_at
  last_verified_at

MfaRecoveryCode
  id
  user_id
  code_hash
  used_at
  created_at
```

Rules:

- TOTP secret is recoverable secret material and is stored through SecretStore;
- recovery codes are one-way hashed and shown only at creation/regeneration;
- enabling/disabling MFA is audited;
- administrators cannot retrieve a user's TOTP secret through normal APIs;
- high-risk account/security changes may require recent re-authentication/MFA.

## OIDC / SSO

The first production release supports OIDC login as an optional-to-enable deployment capability.

OIDC identity maps into the existing User/Principal authorization model and never bypasses Role/Permission/CameraScope checks.

Conceptual identity link:

```text
ExternalIdentity
  id
  user_id
  provider
  issuer
  subject
  email
  created_at
  last_login_at
```

Local break-glass administration remains available even when OIDC is configured.

## CSRF / browser security

If browser authentication uses cookies:

- use HttpOnly;
- use Secure when served over HTTPS;
- use appropriate SameSite policy;
- protect state-changing requests against CSRF.

If bearer tokens are used, avoid persistent insecure browser storage patterns.

Implementation choice must be documented before authentication code is finalized.

## Secrets and credentials

Sensitive values include:

- camera passwords;
- S3 secrets;
- OpenList/rclone credentials/tokens;
- webhook secrets;
- signing keys;
- service-principal secrets.

Rules:

- never expose through ordinary read APIs;
- never place plaintext secret values into AuditEvent before/after snapshots;
- return masked/presence status where UI requires it;
- store through the project's secrets/configuration model.

## AuditEvent

AuditEvent records actor-driven administrative/destructive/security-relevant actions.

Conceptual fields:

```text
id
occurred_at
actor_type
actor_id
actor_display
action
resource_type
resource_id
camera_id
request_id
correlation_id
source_ip
client_info
result
reason
before
after
metadata
created_at
```

Sensitive fields in before/after/metadata are redacted.

AuditEvent is distinct from EventLog:

```text
EventLog
  -> recording/runtime/business behavior

AuditEvent
  -> who changed/did what
```

## Actions that must be audited

At minimum:

```text
auth.login_success
auth.login_failure
auth.logout
auth.session_revoked
auth.password_reset_requested
auth.password_reset_completed
auth.mfa_enabled
auth.mfa_disabled
auth.mfa_recovery_used
auth.oidc_login

user.created
user.updated
user.disabled
user.password_reset

role.created
role.updated
role.deleted
scope.updated

camera.created
camera.updated
camera.deleted_or_archived
camera.ptz_control          # may be sampled/coalesced for continuous movement

recording.manual_started
recording.manual_stopped
recording.policy_changed
recording.locked
recording.unlocked
recording.delete_requested
recording.deleted
recording.export_created
recording.downloaded

storage.target_created
storage.target_updated
storage.target_draining
storage.target_removed
storage.pool_changed

system.settings_changed
system.time_settings_changed

integration.created
integration.updated
integration.disabled

device.time_sync_requested
device.time_sync_completed
```

High-frequency passive actions such as every timeline seek or every video frame are not normal audit events.

## Audit durability

Audit records are append-oriented.

Normal users must not be able to edit existing AuditEvents.

Initial V2 should not expose ordinary delete/edit endpoints for AuditEvent.

Long-term audit retention/export policy may be added separately.

Database administrators can still alter database contents operationally; zero-nvr audit is application accountability, not a cryptographic immutable ledger.

## Audit failure behavior

For high-risk destructive/security changes:

- domain mutation and audit persistence should be transactionally coupled where practical;
- if required audit persistence fails, the destructive mutation should normally fail rather than proceed invisibly.

For lower-risk telemetry-like records, failure may be handled without blocking the main operation.

The classification must be explicit in implementation.

## Authorization failure behavior

Denied API requests return a generic authorization failure without revealing resources outside the caller's scope.

For scoped resources, prefer behavior that does not allow easy enumeration of hidden cameras.

Security logs may retain the internal reason.

## UI behavior

### User management

Administrator UI:

```text
Users
  George
    Enabled
    Roles: Operator
    Camera access:
      Home
      Front Door
```

### Role management

```text
Role: Security Viewer
  Live View       ✓
  Playback        ✓
  Export          ✓
  Download        ✓
  Manual Record   ✗
  Delete          ✗
  Settings        ✗
```

### Camera access

Prefer group selection with optional individual-camera adjustments.

Do not require administrators to tick hundreds of cameras one by one when groups can express the scope.

### Hidden actions

Frontend hides/disables unauthorized actions for usability, but backend enforcement remains authoritative.

## Bootstrap and recovery

First-run setup:

1. detect that no administrator exists;
2. expose one-time bootstrap flow only;
3. create first administrator;
4. close bootstrap path permanently once initialization succeeds.

Do not create a predictable default admin/password.

Administrative account recovery must be an explicit local/operations procedure and must not expose a remote unauthenticated reset endpoint by default.

## Acceptance tests

1. Viewer scoped to Camera A:
   - can live/playback A;
   - cannot discover/play B;

2. Operator without recording.delete:
   - can export/download/lock authorized footage;
   - cannot physically delete it;

3. User with recording.download but no scope to Camera B:
   - cannot download B export/media;

4. scope removed during active session:
   - new timeline/media authorization fails;
   - short-lived previously issued token expires promptly;

5. disabled user:
   - active sessions are revoked;

6. service integration:
   - can perform only granted actions against its camera scope;

7. storage administrator:
   - may request target removal but domain rules still block unique-media loss;

8. recording deletion:
   - requires permission/scope;
   - writes AuditEvent with affected resource and result;

9. secret change:
   - AuditEvent shows that a credential changed without recording plaintext secret;

10. first boot:
   - no default password exists;
   - bootstrap can run only before an administrator exists.

11. SMTP password reset:
   - public request does not enumerate accounts;
   - token is one-time, expiring, and stored only as a hash;
   - successful reset revokes prior sessions and writes audit.

12. administrator/local recovery:
   - administrator can issue one-time reset without learning old password;
   - host-local recovery works without SMTP;
   - no remote unauthenticated admin-reset backdoor exists.

13. TOTP MFA:
   - enrollment secret is protected by SecretStore;
   - recovery codes are one-way hashed and single-use.

14. OIDC:
   - external login maps to the same User/Role/CameraScope authorization path.

## Invariants

1. Backend authorization, not frontend visibility, is authoritative.
2. Roles define allowed actions; camera scope defines allowed camera resources.
3. Permission and scope are both required for camera-scoped actions.
4. Viewing does not imply export/download, lock, delete, PTZ, or management rights.
5. Destructive domain safety invariants still apply to administrators.
6. Media/playback access uses short-lived scoped authorization rather than permanent public URLs.
7. Camera/storage/integration secrets are never exposed through ordinary APIs or audit snapshots.
8. Disabled users cannot retain active sessions.
9. Service integrations use dedicated least-privilege principals.
10. Sensitive administrative/destructive operations create AuditEvents.
11. AuditEvent and EventLog are separate concerns.
12. Audit history is append-oriented and not normally editable/deletable through product APIs.
13. First-run bootstrap never depends on a universal default administrator password.
14. Authorization must avoid leaking hidden camera/resource existence where practical.
15. SMTP-backed self-service password reset is a first-production-release capability, with administrator and host-local recovery fallback.
16. Local-user TOTP MFA and one-time recovery codes are supported in the first production release.
17. OIDC/SSO authentication maps into the same authorization model and does not bypass camera scope.
18. Non-obvious authorization/session/audit/security behavior requires comments per Development Guidelines.

## Secret-management reference

Camera/storage/integration recoverable credentials are stored behind SecretStore and never exposed through normal read APIs. Local passwords and verifier-only API/service tokens use one-way hashing. AuditEvent records credential changes without plaintext/ciphertext/key material. See [Spec 0012 — Configuration, Secret Storage, Key Rotation, and Backup](0012-config-secrets-key-management.md).


## Alert and notification authorization

Alert/notification authorization follows [Spec 0014](0014-alerting-notification-and-escalation.md).

```text
alert.view
alert.acknowledge
alert.manage
notification.view
notification.manage
```

Camera-scoped incidents require both the permission and effective camera scope. Notification target configuration, recipient groups, templates, and channel tests require notification.manage. Secrets remain hidden even from notification.view.

Acknowledgement/resolution actions are audited and never alter source DetectionEvent/RecordingIntent semantics.


## Backup and recovery authorization

Backup/recovery uses:

```text
backup.view
backup.manage
backup.restore
backup.export
```

Full restore, PITR, RecoveryKit export, and portable encrypted system backup are high-risk operations. They require the corresponding permission, recent re-authentication, and MFA when enabled.

Recovery material and backup-target secrets are never exposed by backup.view.

See [Spec 0015 — Backup, Disaster Recovery, PITR, and System Migration](0015-backup-disaster-recovery-and-pitr.md).

## Upgrade and database-migration authorization

```text
update.view
update.manage
database.migrate
```

Installing/rolling back software, changing release channel, or performing SQLite ↔ PostgreSQL migration requires the corresponding permission, recent re-authentication, and MFA when enabled.

Update/database migration actions are audited. Backup/RecoveryKit secrets remain governed by backup/secret permissions and are never exposed through update.view.

See [Spec 0017 — Upgrade, Schema Migration, Database Migration, and Rollback](0017-upgrade-migration-and-rollback.md).


## Device discovery and onboarding authorization

Device discovery, manual endpoint probing, onboarding, credential replacement, endpoint changes, capability refresh, profile-role selection, and hardware replacement require `camera.manage`.

Operational PTZ remains separately gated by `camera.ptz`.

Discovery/probe endpoints are administrative and must not become generic server-side network fetch primitives. Credential-bearing RTSP/ONVIF/vendor URIs are redacted and never exposed through ordinary read APIs.

See [Spec 0018 — Camera Onboarding, Discovery, Capability Probe, and Stream Selection](0018-camera-onboarding-discovery-and-stream-selection.md).


## Device runtime administration authorization

`camera.manage` is required for Camera/Device enable/disable, maintenance mode, explicit reconnect/reprobe, endpoint or credential application, runtime profile-role changes, capability refresh, and identity-conflict resolution.

Automatic background reconnect/reconciliation does not represent a user-authorized administrative mutation and therefore does not create one AuditEvent per retry; it remains visible through health/runtime logs.

Operational PTZ remains independently gated by `camera.ptz`.

See [Spec 0019 — Device Runtime Lifecycle, Reconfiguration, and Capability Drift](0019-device-runtime-lifecycle-and-reconfiguration.md).
