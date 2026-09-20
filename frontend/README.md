# Frontend

The frontend is the Vue 3 zero-nvr management and playback UI.

## Top-level information architecture

~~~text
Dashboard
Live
Playback
Events
Cameras
Storage
System
~~~

Alerts are available through the global bell/drawer and contextual views rather than needing another permanent top-level section.

Users/RBAC, notifications, AI, integrations, backup, health and audit live under System.

## Trust boundary

The browser calls only:

~~~text
/api/v1
~~~

It never receives camera credentials and never directly administers:

- ZLMediaKit;
- Frigate;
- rclone;
- OpenList;
- PostgreSQL/SQLite.

Live and historical playback use short-lived descriptors returned after zero-nvr authorization.

## State management

Pinia should hold small client/UI state such as:

- authenticated-user/session summary;
- work-context tabs;
- live layout;
- UI preferences;
- small cached settings.

Do not clone the entire backend database into one global store.

## Player boundary

Player adapters may include:

- WebRTC/ZLM;
- native browser MP4/fMP4/HLS;
- Jessibuca or another mature compatibility player.

The backend PlaybackResolver / live resolver determines the descriptor and storage/media path.

See [V1 API / Module Freeze](../docs/plans/03-v1-api-module-freeze.md).
