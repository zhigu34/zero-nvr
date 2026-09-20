# ADR 0005 — deploy.sh Is the V1 Deployment and Upgrade Authority

Status: **accepted**

## Context

An earlier design proposed an application-managed UpgradePlan/UpgradeHistory subsystem with scheduled self-updates, maintenance orchestration, and host/container mutation from the product.

The deployment baseline already uses:

```text
deploy.sh + .env + Docker Compose Profiles
```

The web application should not need unrestricted Docker-socket access, and the user prefers direct script-based deployment/operations.

## Decision

V1 host mutation is performed through `deploy.sh`.

Expected direction:

```text
./deploy.sh install
./deploy.sh update [version]
./deploy.sh status
./deploy.sh doctor
./deploy.sh feature enable <name>
./deploy.sh feature disable <name>
./deploy.sh backup
./deploy.sh restore
./deploy.sh rollback [version]
./deploy.sh admin reset-password
```

The script delegates to mature tools:

- Docker Compose;
- Alembic;
- SQLite Online Backup / pg_dump;
- restic;
- application health/readiness checks.

The UI may display current/available versions, migration impact, compatibility, and the command to run, but it does not need to control Docker or implement a second deployment engine.

Scheduled automatic self-update and a heavyweight persisted UpgradePlan subsystem are not V1 requirements.

## Consequences

Positive:

- matches the established deployment workflow;
- avoids Docker-socket privilege in the web application;
- disaster recovery remains possible when the web UI is broken;
- fewer long-lived orchestration states/tables;
- easier debugging and manual rollback.

Trade-off:

- upgrades are operator-initiated from the host rather than a one-click browser action in V1.

A browser-driven update mechanism may be added later only if it can preserve the same security and rollback guarantees without weakening this boundary.
