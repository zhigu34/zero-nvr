# Spec 0012 — Configuration and Secret Storage

Status: **accepted**

## Goal

Define a secure, lightweight way to store product configuration and recoverable credentials without turning zero-nvr into a secret-management platform.

Core rule:

> Use mature authenticated-encryption/password-hashing libraries. Recoverable secrets are encrypted outside normal business fields, and the master key is not stored in the same database as the ciphertext.

## Configuration classes

### Ordinary product configuration

Examples:

~~~text
camera display/configuration
recording policy
retention policy
timezone
NTP settings
notification policy
storage target non-secret metadata
UI/product settings
~~~

These live in the normal SQLite/PostgreSQL database.

### Recoverable secrets

Values zero-nvr must recover to connect outward:

~~~text
camera/ONVIF/RTSP password
SMTP password
OIDC client secret
rclone remote credential material
MQTT credential
webhook/shared secret
Frigate/OpenList external credential
~~~

Business rows reference an opaque secret_ref.

### Verifier-only credentials

When plaintext recovery is unnecessary, store only a verifier/hash:

~~~text
local user password
Personal API Token
password-reset token
one-time bootstrap/reset token
~~~

Do not make verifier-only credentials reversibly encrypted for convenience.

## SecretStore

Application code uses a small SecretStore boundary:

~~~text
create(kind, owner, plaintext)
read(secret_ref)
replace(secret_ref, plaintext)
delete(secret_ref)
metadata(secret_ref)
~~~

The initial implementation is an encrypted database SecretRecord.

Future Vault/KMS integration may implement the same boundary if a real deployment requires it; it is not a V1 dependency.

## SecretRecord

Conceptual model:

~~~text
id
kind
owner_type
owner_id
key_id
encrypted_payload
version
created_at
updated_at
~~~

The encrypted payload contains any nonce/version/authentication information produced by the selected mature library.

Do not hand-roll cryptographic framing.

## Encryption library

V1 should use the Python cryptography package or an equivalently mature audited library.

A practical implementation is Fernet/MultiFernet:

- authenticated encryption;
- random IV/nonces handled by the library;
- simple key rotation;
- no custom envelope-encryption protocol required.

AES-GCM through cryptography is also acceptable if the implementation remains small and uses library-managed primitives correctly.

Do not implement custom AES modes, MAC composition, nonce construction, or key wrapping.

## Master key

The active encryption key is deployment/bootstrap state, not database state.

Supported bootstrap direction:

~~~text
ZERO_NVR_SECRET_KEY
ZERO_NVR_SECRET_KEY_FILE
~~~

Production documentation should prefer a protected file/Compose secret where practical.

The key must be stable across container recreation and upgrades.

Automatically generating a new key every start is forbidden.

## Key rotation

Rotation should remain simple.

With MultiFernet or equivalent:

~~~text
new key becomes active
old key remains readable
background/admin rotation re-encrypts existing SecretRecords
old key is removed only after verification and backup
~~~

A per-record DEK/KEK envelope hierarchy is not required for V1.

If a future external KMS/HSM deployment needs envelope encryption, add it behind SecretStore with an ADR rather than making every small installation pay the complexity cost.

## Passwords and tokens

Local passwords use a modern password hashing library, preferably Argon2id through pwdlib/passlib-compatible mature tooling.

Personal API Tokens and password-reset tokens:

- generate high-entropy random plaintext;
- show/send plaintext only at creation/use;
- store only a strong hash/verifier;
- support expiry/revocation as appropriate.

## API behavior

Normal APIs never return secret plaintext.

Use explicit state such as:

~~~text
credentials_configured: true
~~~

When editing a resource, secret mutation is explicit. Field-specific update actions use:

~~~text
keep
replace
clear
~~~

Rules:

- `keep` preserves the current SecretStore reference and does not accept a new secret value;
- `replace` requires a new secret value and replaces or creates the referenced secret;
- `clear` does not accept a replacement value and removes the optional SecretStore reference plus its SecretRecord;
- omitted optional secret action defaults to `keep`;
- resources whose secret is structurally required may reject `clear` rather than silently storing an empty value.

Do not infer replacement or clearing from empty strings, nulls, masked placeholders, or whether a secret-looking field happens to be present. Do not send fake masked strings such as ******** back and forth as if they were credentials.

## Logging / errors / audit

Never put secret plaintext into:

- application logs;
- exception messages;
- Event metadata;
- AuditEvent before/after;
- tracing attributes;
- support/config exports.

Audit may record that a secret was created/replaced/deleted, but not its value.

## Backup and RecoveryKit

Database ciphertext alone is insufficient for disaster recovery.

The RecoveryKit/backup instructions must preserve:

- active/required historical zero-nvr secret key(s);
- restic repository bootstrap material;
- deployment/version metadata required for restore.

The master key must not be casually placed inside the same unprotected backup payload it decrypts.

RecoveryKit handling should be explicit and operator-controlled.

## Restore

Restore sequence:

~~~text
restore/provide secret key material
-> restore database
-> start zero-nvr
-> SecretStore self-test
-> validate representative configured credentials/integrations
~~~

Missing/wrong key is a critical explicit error. Do not silently replace encrypted credentials with blanks.

## Configuration export

Normal configuration export excludes secret plaintext.

It may include:

- resource IDs/names;
- non-secret settings;
- credentials_configured flags;
- provider/remote names.

Portable disaster backup is a different workflow and may include encrypted SecretRecords plus separately protected RecoveryKit material.

## External secrets

A future advanced deployment may source selected secrets from Vault/KMS/platform secret providers.

This is optional and must not make the default Compose/SQLite deployment heavier.

## Health

SecretStore health should distinguish:

~~~text
OK
KEY_MISSING
DECRYPTION_FAILED
READ_ONLY/DB_ERROR
~~~

A broken SecretStore degrades capabilities requiring credentials but does not delete their configuration.

## Acceptance tests

1. Camera credential:
   - stored encrypted;
   - plaintext absent from normal DB business fields/API/logs.
2. Restart:
   - same configured key decrypts existing secrets.
3. Wrong key:
   - startup/health reports explicit critical failure rather than blanking secrets.
4. Rotation:
   - old and new encrypted records remain readable during transition;
   - re-encryption completes before old key removal.
5. Password/API token:
   - only one-way verifiers are stored.
6. Backup/restore:
   - clean-host restore with RecoveryKit can decrypt configured credentials.
7. Config export:
   - contains no secret plaintext.
8. Optional integration failure:
   - a bad external credential does not affect unrelated recording.

## Invariants

1. Recoverable secret plaintext is not stored directly in business tables.
2. Verifier-only credentials are never reversibly encrypted.
3. The master encryption key is not stored inside the active product database.
4. zero-nvr uses mature crypto libraries and does not design its own cryptographic protocol.
5. Key material survives upgrade/container recreation through explicit deployment bootstrap.
6. Secret loss/decryption failure is explicit, never silently converted to empty credentials.
7. Normal APIs/logs/audit/config exports never expose secret plaintext.
8. Disaster recovery preserves the key material required to decrypt restored data.
