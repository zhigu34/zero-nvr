# Frontend

The frontend is the zero-nvr management and playback UI.

Planned product areas:

- Device Center
- Live Monitor
- Recording Timeline
- Event Center
- Alert Center
- Storage Center
- System Health
- Settings / Integrations

The browser should consume stable zero-nvr APIs. It should not depend directly on vendor-device APIs.

Live media may be delivered by the Media Plane, but session authorization and stream selection are issued by the zero-nvr control plane.
