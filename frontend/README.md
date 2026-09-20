# Frontend

The frontend is the Vue 3 + TypeScript zero-nvr management and playback UI.

## Toolchain

- Vue 3
- TypeScript
- Vite
- Vue Router
- Pinia

The browser talks only to the same-origin zero-nvr `/api/v1` surface. It never receives source-camera credentials and never directly administers ZLMediaKit, Frigate, rclone, OpenList, or the database.

## Development

Run the backend on port 8000, then:

~~~bash
cd frontend
npm install
npm run dev
~~~

The Vite dev server proxies `/api`, `/health`, and `/internal` to the local FastAPI process.

Validation:

~~~bash
npm run typecheck
npm run build
~~~

## Production packaging

`backend/Dockerfile` builds this app in a Node build stage and copies only `frontend/dist` into the final zero-nvr Python image.

FastAPI mounts that static bundle only when it exists, so local backend development and backend tests do not require Node.

This preserves the frozen Core deployment boundary:

~~~text
Image: zero-nvr
  ├─ zero-nvr API + web assets
  └─ zero-nvr worker

Image: ZLMediaKit
  └─ zlmediakit
~~~

No dedicated frontend container is introduced.

## Current UI slice

The first frontend slice includes:

- first-run administrator creation;
- local session login/logout;
- protected-route bootstrap;
- responsive application shell;
- Dashboard capability health and camera inventory;
- Camera inventory plus guided ONVIF discovery/test/import and manual RTSP test/create;
- authenticated SSE refresh hints;
- route placeholders for Live, Playback, Events, Storage and System.

The remaining workspaces should be implemented against existing `/api/v1` contracts rather than bypassing the control plane.
