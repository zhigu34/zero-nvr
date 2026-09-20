# Spec 0001 — Initial Platform Architecture

Status: **superseded**

This document originally captured the first architecture pass for the zero-nvr rewrite.

It is intentionally no longer a normative implementation specification because several early assumptions were replaced during the V1 design audit, including:

- PostgreSQL-first deployment -> **SQLite default, PostgreSQL optional**;
- FFmpeg permanent recording -> **ZLMediaKit normal recording authority**;
- separate small-tool services -> **FFmpeg/rclone/restic/Apprise integrated into the zero-nvr/worker image where practical**;
- application-owned media reconnect/runtime -> **ZLM-owned media pull/reconnect with thin zero-nvr reconciliation**;
- product-managed multi-disk StoragePool -> **host-managed storage aggregation + StorageTarget**;
- remote FUSE playback baseline -> **rclone restore to bounded local playback cache**;
- heavy in-app upgrade orchestration -> **deploy.sh as V1 deployment/upgrade authority**;
- mandatory advanced integrations -> **complete core lifecycle with optional/post-V1 extensions**.

## Current normative sources

Use these documents instead:

1. [PROJECT_BASELINE.md](../PROJECT_BASELINE.md)
2. [ARCHITECTURE.md](../ARCHITECTURE.md)
3. [DOMAIN_MODEL.md](../DOMAIN_MODEL.md)
4. [TECH_STACK.md](../TECH_STACK.md)
5. [DEPLOYMENT.md](../DEPLOYMENT.md)
6. accepted [ADRs](../adr/)
7. current accepted specs in this directory

The current project state is:

```text
V1 Design Freeze Candidate
```

and the remaining architecture assumptions are validated through:

- [V1 Design-Freeze POC Plan](../plans/01-design-freeze-poc.md)

This file is retained only to explain the documentation history. New implementation work must not use it as a source of truth.
