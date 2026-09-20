# Spec 0011 — Authentication, Camera-Scoped Authorization, and Audit

Status: **accepted**

## Goal

Provide secure local authentication, camera-scoped RBAC, password recovery, API tokens, optional OIDC, and audit without building an identity platform.

Core rule:

> Role/permission says what a user may do. Camera scope says which cameras the user may do it to.

## Local users

Conceptual User:

~~~text
id
username
display_name
email
password_hash
enabled
last_login_at
created_at
updated_at
~~~

Use a mature password library with Argon2id.

Never store reversible local passwords.

Anonymous access is disabled by default.

First-run setup explicitly creates the first Administrator; no universal default password is shipped.

## Browser authentication

For the same-origin Vue + FastAPI product, prefer secure server-managed browser sessions/cookies:

- HttpOnly;
- Secure under HTTPS;
- appropriate SameSite;
- CSRF protection for state-changing requests where required;
- server-side revocation.

Do not require browser localStorage to hold long-lived bearer credentials.

Exact session implementation may use a signed opaque/session token plus a persisted UserSession row.

## UserSession

~~~text
id
user_id
created_at
last_seen_at
expires_at
revoked_at
client_info
~~~

Disabling a user or resetting/changing a password revokes prior sessions by default.

## Roles and permissions

Built-in roles:

~~~text
Administrator
Operator
Viewer
~~~

Administrators may define additional roles if the UI supports it.

Conceptual:

~~~text
Role
RolePermission
UserRole
~~~

Suggested action-oriented permission groups:

~~~text
camera.view
camera.control
camera.configure

recording.view
recording.export
recording.protect
recording.delete

event.view
alert.acknowledge
alert.manage

storage.manage
system.view
system.manage
user.manage
integration.manage
audit.view
~~~

Viewing footage does not imply export/delete/PTZ/configuration.

## Camera scope

Authorization combines permission plus camera scope.

Scope may be:

- all cameras;
- selected CameraGroups;
- selected Cameras;
- none.

CameraGroup may be hierarchical if useful, but the permission engine should remain understandable.

Backend enforcement is authoritative; frontend hidden buttons are only UX.

## Media authorization

Live/playback APIs check user/session, permission, and camera scope before returning a short-lived media descriptor/token.

Never expose camera RTSP credentials or permanent privileged ZLM administration URLs.

Export/download/protection/delete are independently authorized.

## Personal API Tokens

For Home Assistant/scripts/automation, users may create scoped Personal API Tokens.

Conceptual:

~~~text
id
user_id
name
token_hash
permissions/scope
created_at
expires_at
last_used_at
revoked_at
~~~

Plaintext token is shown only once at creation. Only a verifier/hash is stored.

Token permissions cannot silently exceed the issuing user's allowed policy without an explicit administrative service-account model.

## Password reset

V1 supports three recovery paths.

### Self-service email reset

1. accept username/email without revealing account existence;
2. generate a high-entropy one-time token;
3. store only token hash plus expiry/used state;
4. send via configured SMTP;
5. atomically consume token when password changes;
6. revoke previous sessions;
7. audit the reset result.

Conceptual PasswordResetToken:

~~~text
id
user_id
token_hash
requested_at
expires_at
used_at
request_metadata
created_by
~~~

### Administrator-issued reset

An authorized administrator may issue an expiring one-time reset flow without learning the old password.

### Host-local break-glass recovery

Deployment interface provides a host-only path such as:

~~~text
./deploy.sh admin reset-password
~~~

or an interactive equivalent.

Do not expose an unauthenticated remote administrator-reset endpoint.

## SMTP dependency

SMTP is a V1 capability because self-service password reset may require it.

If SMTP is broken:

- self-service email reset may fail;
- administrator-issued reset remains;
- host-local deploy.sh recovery remains.

SMTP failure must never permanently lock out an operator who has host access.

## OIDC

OIDC is the only external identity protocol zero-nvr needs to implement directly for V1.

External Authentik/Authelia/Keycloak/etc. may handle LDAP/SAML/social providers and expose OIDC.

OIDC identity maps to the same User/Role/CameraScope authorization model.

Conceptual ExternalIdentity:

~~~text
id
user_id
issuer
subject
email
created_at
last_login_at
~~~

Local Administrator/break-glass access remains available.

Do not build a custom IdP, LDAP server/client matrix, or SAML SP unless later justified.

## MFA

TOTP MFA is a useful optional enhancement but does not block V1 core completeness.

If implemented, use a mature OTP library, store the TOTP secret through SecretStore, hash recovery codes, and audit enrollment/reset.

Do not let MFA complexity delay local auth/password recovery/RBAC.

## Login protection

V1 should include simple brute-force protection:

- rate-limit repeated login/reset attempts;
- temporary per-account/IP backoff where reasonable;
- non-enumerating reset/login error design where appropriate;
- security Event/Audit recording for meaningful abuse conditions.

Do not build a SIEM.

## AuditEvent

Actor-driven sensitive changes are append-oriented.

Conceptual fields:

~~~text
id
actor_user_id / token identity
action
resource_type
resource_id
camera_id
result
source_ip
client_info
correlation_id
sanitized metadata
created_at
~~~

Audit examples:

- login/security changes;
- user/role changes;
- camera/storage/settings changes;
- PTZ/manual recording/protection/delete/export actions;
- notification/integration changes;
- backup/restore/upgrade actions.

Automated high-frequency runtime telemetry does not belong in AuditEvent.

## Secret handling

Camera passwords, SMTP/OIDC/rclone credentials and similar recoverable values are referenced through SecretStore.

Password hashes/API token hashes/reset-token hashes are verifier-only.

See [Spec 0012](0012-config-secrets-key-management.md).

## UI

System administration includes:

- Users;
- Roles;
- Camera access;
- Sessions;
- Personal API Tokens;
- optional OIDC configuration;
- audit search.

Normal users can manage their own password/sessions/tokens subject to policy.

## Acceptance tests

1. First run has no default password and creates an explicit Administrator.
2. Viewer can view allowed cameras but cannot configure/delete/export when permission is absent.
3. Camera scope blocks hidden cameras at API level.
4. User disable/password reset revokes existing sessions.
5. Password-reset token is single-use, expiring, and only hashed in DB.
6. SMTP failure leaves host-local/admin recovery available.
7. Personal API Token plaintext is shown only at creation and stored hashed.
8. OIDC user still passes normal RBAC/camera scope checks.
9. Media descriptor never exposes camera credentials.
10. Sensitive actions produce sanitized AuditEvent rows.

## Invariants

1. Local accounts remain available for bootstrap/break-glass use.
2. Passwords/tokens that need only verification are one-way hashed.
3. Role permission and camera scope are both required for camera-scoped actions.
4. Frontend visibility never grants authorization.
5. Viewing never implicitly grants export/delete/control/manage.
6. Password recovery cannot reveal old passwords.
7. Disabling/resetting a user revokes prior interactive sessions by default.
8. OIDC never bypasses zero-nvr authorization.
9. Personal API Token plaintext is not persisted.
10. AuditEvent records actor accountability without storing secret plaintext.
11. zero-nvr does not become a general-purpose IdP.
