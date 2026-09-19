# ADR-0001 — Runtime Boundaries and Container Policy

Status: **Accepted**

## Decision

Container boundaries follow runtime-service boundaries, not feature/module boundaries.

Small libraries and CLI tools are integrated into the zero-nvr image when practical. Independent daemons/services retain separate containers.

Integrated toolchain includes FFmpeg/ffprobe, rclone, restic, Apprise, ONVIF/WS-Discovery libraries, and auth/OIDC libraries.

Independent services include ZLMediaKit and optional managed Frigate/OpenList/PostgreSQL/Mosquitto.

The zero-nvr API and Huey worker use the same image but run as separate containers/processes.

## Rationale

This preserves fault/resource separation between API work and background jobs without multiplying image layers and operational services.

It also keeps the default stack lightweight:

- 2 images;
- 3 containers.

## Consequences

- normal remote archive does not require an rclone sidecar;
- enabling SMTP/OIDC/ONVIF/backup/export does not add containers;
- optional service images are not pulled when disabled;
- future components need an explicit reason to become a new long-running service.
