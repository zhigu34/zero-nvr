import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5273,
    // Same shape as frontend/vite.config.ts. Proxying (rather than pointing
    // the client at an absolute origin) is what keeps the session cookie
    // first-party: the cookie is HttpOnly + SameSite=Lax, so a cross-origin
    // XHR to :8000 would not carry it at all.
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
      "/internal": "http://127.0.0.1:8000",
      "/zlm": "http://127.0.0.1:8000",
    },
  },
})
