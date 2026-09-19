# Spec 0012 — Configuration, Secret Storage, Key Rotation, and Backup

Status: **accepted**

## Goal

Define how zero-nvr stores ordinary configuration and sensitive credentials, how services access secrets, how encryption keys are bootstrapped and rotated, and how backup/restore avoids leaking plaintext credentials.

Core rule:

> Business configuration may live in PostgreSQL. Recoverable secrets live behind SecretStore. The key that protects SecretStore never lives in the same database as the ciphertext.

## Configuration classes

zero-nvr separates three classes.

### 1. Ordinary configuration

Examples:

```text
recording segment duration
pre/post-roll
retention days
recording timezone
NTP server hostnames
StoragePool policy
camera display name
schedule
UI preferences
```

These may be stored normally in PostgreSQL.

### 2. Recoverable managed secrets

The backend must be able to recover these values to connect to external systems.

Examples:

```text
camera username/password
RTSP credentials
ONVIF credentials
S3 access key / secret key
rclone/OpenList tokens
outbound webhook bearer/basic credentials
SMTP/notification credentials
OAuth refresh tokens
integration shared secrets when plaintext key material is required
```

These are stored through SecretStore and referenced by opaque secret_ref values.

### 3. Verifier-only credentials

When zero-nvr only needs to verify a presented credential, store a one-way verifier rather than reversible plaintext.

Examples:

```text
local user passwords
service/API tokens that zero-nvr only authenticates
password-reset/bootstrap one-time tokens
```

Use modern password/token hashing appropriate to the credential.

A secret that does not need to be recovered must not be made recoverable merely for convenience.

## Secret references

Business/domain rows hold references, not secret plaintext.

Examples:

```text
CameraConnection
  credentials_ref

StorageTarget
  credential_secret_ref

Integration
  credential_secret_ref
```

Public API responses may expose:

```text
credentials_configured = true
```

but never the secret value.

Do not return a masked fake value such as "********" in a field that clients might later submit back as the new password.

## SecretStore contract

Application/domain code depends on a SecretStore abstraction.

Conceptual operations:

```text
create(kind, owner, payload)
read(secret_ref, purpose_context)
replace(secret_ref, payload)
delete(secret_ref)
metadata(secret_ref)
rotate_wrapping_key(...)
```

Initial implementation:

```text
EncryptedDatabaseSecretStore
```

Future implementations may use Vault, cloud KMS/secret managers, or hardware-backed providers without changing Camera/Storage/Integration domain contracts.

## SecretRecord

Conceptual encrypted record:

```text
SecretRecord
  id
  kind
  owner_type
  owner_id

  algorithm
  encrypted_payload
  payload_nonce

  wrapped_data_key
  wrap_nonce
  wrapping_key_id

  version
  created_at
  updated_at
  last_used_at
```

SecretRecord metadata must not contain plaintext credentials.

## Envelope encryption

Initial V2 uses envelope encryption.

For every SecretRecord:

```text
random 256-bit DEK
      ↓
encrypt secret payload with DEK
      ↓
ciphertext stored in PostgreSQL

active KEK
      ↓
wrap/encrypt DEK
      ↓
wrapped DEK stored beside ciphertext
```

Terminology:

```text
DEK = data-encryption key, unique per SecretRecord
KEK = key-encryption/wrapping key, external to PostgreSQL
```

Initial authenticated-encryption primitive:

```text
AES-256-GCM
```

Requirements:

- cryptographically random key material;
- unique random nonce for every encryption operation;
- authenticated additional data binds ciphertext to SecretRecord identity/type/version where practical;
- authentication failure is a hard secret-read failure, never ignored;
- secret plaintext is held in memory only for the shortest necessary operation.

Envelope encryption allows KEK rotation by re-wrapping DEKs without rewriting every underlying secret payload.

## Master / wrapping key location

The active KEK/keyring must not be stored in PostgreSQL.

Preferred production sources:

```text
Docker/Compose secret file
systemd credential / protected host file
external secret/KMS provider
future orchestrator secret mount
```

Initial Compose-friendly path may be:

```text
/run/secrets/zero_nvr_master_key
```

or another configured read-only secret path.

The application supports an explicit bootstrap setting:

```text
ZERO_NVR_MASTER_KEY_FILE
```

Environment-variable key injection may exist for development/compatibility, but production should prefer a secret file/credential provider because environment values are easier to expose through process/container inspection.

## First-run key generation

For simple self-hosted deployments, zero-nvr may generate a KEK automatically only when all are true:

- no external key was supplied;
- no existing encrypted SecretRecords require another key;
- the configured private key directory is persistent and writable.

Example persistent private location:

```text
/var/lib/zero-nvr/keys/
```

Generated key files must:

- use cryptographically secure randomness;
- be owner-readable only (for example mode 0600);
- live on persistent storage;
- never be committed to Git;
- never be written to application logs.

Docker Compose deployment should persist this directory/key material separately from ephemeral container filesystem.

If an encrypted database already exists but the required KEK is missing, zero-nvr must fail secret-dependent startup/readiness clearly rather than generating a different key and pretending credentials are empty.

## Keyring and key IDs

Support key versioning from the start.

Conceptually:

```text
WrappingKeyRing
  active_key_id
  available key_id -> key material
```

SecretRecord stores wrapping_key_id.

During rotation, old keys remain temporarily available until all DEKs are rewrapped.

Do not identify keys solely by file modification time or array position.

## KEK rotation

Safe rotation:

```text
add new KEK
    ↓
mark new key active for new secrets
    ↓
batch rewrap existing DEKs
    ↓
verify every SecretRecord decrypts
    ↓
retire old KEK
```

Because payloads use per-record DEKs, normal rotation does not need to decrypt/re-encrypt every secret payload.

Rotation is resumable/idempotent.

Never delete the old KEK until zero-nvr proves no live SecretRecord depends on it and required backups have been considered.

Administrative key rotation is audited.

## Secret payload format

A SecretRecord may hold a small structured encrypted object instead of one isolated password.

Example camera credential payload:

```json
{
  "username": "admin",
  "password": "<secret>"
}
```

Example S3 credential payload:

```json
{
  "access_key_id": "<secret>",
  "secret_access_key": "<secret>",
  "session_token": null
}
```

The entire payload is encrypted.

Do not put secret username/password fragments into cleartext metadata merely to simplify UI.

Non-secret endpoint information such as camera host, S3 endpoint, bucket, region, or OpenList URL remains ordinary configuration.

## Secret access boundary

Only backend components that actually need a secret may request it.

Conceptually:

```text
Camera domain
   -> credentials_ref
   -> DeviceAdapter asks SecretStore when connecting

StorageTarget
   -> credential_secret_ref
   -> StorageBackend asks SecretStore when creating client
```

Frontend never receives SecretStore plaintext.

Worker processes that need secrets should obtain them through a narrow internal service/library boundary, not by copying all secrets into global process environment.

## Update semantics

Secret update APIs use explicit semantics.

Recommended request behavior:

```text
field omitted
  -> keep existing secret

replace_secret supplied
  -> create/replace encrypted secret

clear_secret = true
  -> explicitly remove credential, if domain allows
```

Never interpret a masked UI placeholder as a real replacement secret.

Where possible, connection/config updates follow:

```text
create new SecretRecord/version
      ↓
validate new external connection
      ↓
atomically switch business secret_ref
      ↓
retire old secret
```

This avoids destroying working credentials before new credentials are verified.

## Read API behavior

Read responses expose only non-sensitive state.

Example:

```json
{
  "host": "192.168.1.20",
  "username_configured": true,
  "password_configured": true,
  "credential_last_updated_at": "..."
}
```

Even administrators do not receive stored secret plaintext back through normal product APIs.

A user who forgot a camera/S3 password replaces it; zero-nvr does not provide a "show saved password" feature by default.

## Logs, errors, and tracing

Secret redaction is mandatory.

Never log:

- passwords;
- Authorization headers;
- API tokens;
- camera RTSP URLs containing credentials;
- S3/OpenList/rclone secrets;
- decrypted SecretRecord payloads;
- master/wrapping keys.

Logging helpers should redact common secret fields and URI userinfo.

Exceptions/errors from adapters must be sanitized before structured logging/EventLog/AuditEvent.

Correlation IDs are safe; credentials are not.

## Audit behavior

AuditEvent records that secret configuration changed, but not the value.

Example:

```text
action = camera.credentials_updated
before = { credentials_configured: true }
after  = { credentials_configured: true }
```

Useful metadata may include secret_ref changed, credential kind, validation result, and actor, but never ciphertext/key material/plaintext.

Secret reads performed automatically by runtime services are not individually written as high-volume AuditEvents.

## Bootstrap secrets

Some secrets are required before PostgreSQL/SecretStore is available.

Examples:

```text
PostgreSQL password
SecretStore KEK/keyring
optional TLS private-key path/passphrase
```

These are bootstrap/deployment secrets and must come from Docker secrets, protected files, system credentials, or equivalent deployment mechanism.

They are not recursively stored inside the SecretStore they are needed to unlock.

Prefer conventional *_FILE configuration for bootstrap secrets when practical.

## Session/media/API signing secrets

Where possible, use opaque random tokens whose server-side database representation is hashed so no reversible signing secret is needed.

If an internal signing/encryption key is required for short-lived media/session tokens:

- give it a dedicated purpose/key ID;
- derive or store it separately from external-service credentials;
- support rotation;
- never reuse the camera/storage SecretStore DEK directly.

One cryptographic key must not be reused for unrelated purposes.

## Backup classes

zero-nvr distinguishes normal data backup from portable secret export.

### Database backup

A PostgreSQL backup contains:

- ordinary configuration;
- SecretRecord ciphertext;
- wrapped DEKs;
- business metadata.

It does not contain the external KEK/keyring.

Therefore a database-only restore cannot recover managed secrets unless the matching keyring is also restored.

### Keyring backup

The KEK/keyring is critical recovery material.

Operational backup must store it separately and securely from the normal database dump where practical.

It must never be placed unencrypted in an ordinary downloadable support/config export.

### Portable encrypted system backup

An explicit administrator workflow may create a portable backup that includes recoverable secrets.

Requirements:

- explicit "include secrets" choice;
- administrator/system.manage authorization;
- re-authentication or equivalent high-risk confirmation;
- operator supplies an export passphrase/recovery key;
- use a memory-hard KDF such as Argon2id to derive a backup encryption key;
- encrypt the complete secret/key package with authenticated encryption;
- never create an intermediate plaintext archive on disk;
- audit creation/download/restore.

The portable backup must not depend on the source machine's KEK after successful export.

## Configuration export

Normal configuration/support export excludes secret values.

Example exported camera:

```json
{
  "name": "Front Door",
  "host": "192.168.1.20",
  "credentials_configured": true
}
```

Not:

```json
{
  "username": "admin",
  "password": "..."
}
```

## Restore behavior

Restore must distinguish:

```text
configuration restored
secret available
secret unavailable
secret decryption failed
```

Missing secrets are not silently converted into blank credentials.

Affected Camera/StorageTarget/Integration resources enter an explicit credential/configuration error state until repaired.

If ciphertext exists but the keyring is wrong/missing, zero-nvr surfaces a critical secrets/keyring error.

## Secret deletion

Deleting/replacing a domain object may orphan a SecretRecord.

Use explicit reference/lifecycle handling:

```text
domain ref removed
      ↓
secret becomes unreferenced
      ↓
short safety/grace period if needed
      ↓
secure logical deletion from SecretStore
```

Do not garbage-collect secrets solely by age.

For database-backed encrypted secrets, deleting ciphertext/key material is the primary logical destruction mechanism; claims about guaranteed physical erasure on SSD/database backups must not be overstated.

## Credential validation

When a credential can be tested safely:

- validate before committing destructive replacement;
- use bounded timeout;
- do not log the credential;
- return a sanitized error;
- audit success/failure of the administrative change.

Examples:

```text
camera credential probe
S3 List/Head test
OpenList health/auth test
webhook test action
```

A temporary external outage must not automatically erase the last known working SecretRecord.

## UI behavior

### Camera credential form

```text
Username: [configured]
Password: [configured]

[Replace credentials]
```

No normal "show password" control.

### Storage credential form

```text
S3 endpoint: ...
Bucket: ...
Credentials: Configured
Last verified: ...

[Test]
[Replace credentials]
```

### System security / backup

```text
Secrets
  SecretStore: Healthy
  Active key id: key-2026-01
  Encrypted records: ...
  Key rotation: Healthy

Backups
  Export configuration (no secrets)
  Create encrypted portable backup (includes secrets)
```

Do not display raw key material in the UI.

## Health/readiness

SecretStore health should include:

```text
keyring_loaded
active_key_available
decrypt_self_test
undecryptable_secret_count
rotation_state
```

If the system cannot decrypt credentials required for core recording:

- surface critical health;
- affected cameras/storage integrations fail explicitly;
- do not silently rewrite or clear credentials.

A missing optional integration secret should not necessarily stop unrelated cameras from recording.

Readiness may distinguish core/bootstrap failure from resource-specific credential failure.

## Acceptance tests

1. database dump without keyring:
   - no recoverable secret plaintext is present;
   - restored system reports missing keyring instead of blank credentials;

2. camera read API:
   - shows configured state;
   - never returns camera password;

3. secret update:
   - omitted credential fields preserve existing secret;
   - explicit replacement validates and atomically switches;

4. wrong/tampered ciphertext:
   - authenticated decryption fails;
   - secret is not returned as corrupted plaintext;

5. key rotation:
   - new writes use new KEK;
   - existing DEKs are rewrapped;
   - old key is retained until migration verification completes;

6. logs/audit:
   - no plaintext credentials/Authorization headers/credential-bearing RTSP URLs appear;

7. S3 outage during credential edit:
   - old working SecretRecord is not destroyed solely because validation is temporarily unavailable;

8. normal config export:
   - excludes secrets;

9. portable secret backup:
   - requires explicit privileged action;
   - output is encrypted with export passphrase/recovery key;
   - restore works without source host KEK;

10. lost keyring:
   - ciphertext remains but secrets are unrecoverable;
   - system reports critical keyring/secrets health;

11. user password / verification-only API token:
   - stored as one-way verifier rather than encrypted recoverable secret.

## Invariants

1. Ordinary configuration and recoverable secrets are separate storage concerns.
2. Domain rows reference secrets by opaque secret_ref; they do not embed plaintext credentials.
3. Verifier-only credentials use one-way hashing, not reversible encryption.
4. Recoverable managed secrets are encrypted with authenticated encryption.
5. Secret payload encryption uses per-record DEKs; DEKs are wrapped by a KEK external to PostgreSQL.
6. The KEK/keyring is never stored beside SecretRecord ciphertext in the database.
7. Production bootstrap prefers secret files/credential providers over plaintext environment variables.
8. Existing encrypted data plus missing KEK is an error; zero-nvr never silently generates a replacement key.
9. Normal read APIs never reveal stored secret plaintext, including to administrators.
10. Secret replacement is explicit and should preserve the last working credential until the replacement is committed.
11. Logs, traces, EventLog, and AuditEvent must redact secrets and credential-bearing URIs.
12. Normal configuration exports exclude secret values.
13. Portable backups containing secrets are explicitly requested and strongly encrypted.
14. Key rotation is versioned, resumable, and does not retire old key material before verification.
15. Missing/decryption-failed secrets remain observable resource errors and are not converted into empty values.
16. Cryptographic keys are separated by purpose.
17. Non-obvious encryption/key-rotation/secret-lifecycle behavior requires comments per Development Guidelines.
