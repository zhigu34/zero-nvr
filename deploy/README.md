# Deployment

Deployment definitions will live here.

Baseline service roles:

- zero-nvr-api
- zero-nvr-web
- zero-nvr-runtime
- zero-nvr-worker
- postgres
- zlmediakit

Optional integrations may include:

- hik-bridge
- frigate
- mosquitto
- openlist
- coturn
- wvp

The first deployment target is a single Linux Docker host. The architecture should allow later separation of control plane, workers and storage without changing the domain contracts.
