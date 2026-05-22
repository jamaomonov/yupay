import path from "node:path";

import tailwind from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Where the FastAPI container can be reached from inside Docker. When `vite
// dev` runs on the host (no compose), fall back to localhost. Override via
// VITE_DEV_API_TARGET if you proxy to a different backend.
const apiTarget =
  process.env.VITE_DEV_API_TARGET ??
  (process.env.DOCKER_CONTAINER ? "http://api:8000" : "http://localhost:8000");

// Public host the browser uses to reach this dev server — required for HMR
// over a reverse proxy on HTTPS. Leave unset for plain ``localhost:3002``.
const hmrHost = process.env.VITE_HMR_HOST?.trim() || null;
const hmrProtocol = process.env.VITE_HMR_PROTOCOL?.trim() || "wss";
const hmrClientPort = Number(process.env.VITE_HMR_CLIENT_PORT ?? 443);

export default defineConfig({
  plugins: [react(), tailwind()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
    strictPort: true,
    // Accept any Host header so requests proxied through Caddy / ngrok aren't
    // rejected by Vite's host-check. Safe in dev — admin only ever sits
    // behind an intentional reverse proxy.
    allowedHosts: true,
    // Docker Desktop bind-mounts don't reliably emit inotify events on
    // macOS/Windows; polling is the only safe default for dev hot-reload.
    watch: {
      usePolling: true,
      interval: 200,
    },
    ...(hmrHost
      ? {
          hmr: {
            host: hmrHost,
            protocol: hmrProtocol,
            clientPort: hmrClientPort,
          },
        }
      : {}),
    proxy: {
      "/api": {
        target: apiTarget,
        changeOrigin: true,
        ws: true,
      },
      "/webhooks": {
        target: apiTarget,
        changeOrigin: true,
      },
    },
  },
  preview: {
    host: "0.0.0.0",
    port: 4173,
  },
  build: { sourcemap: true },
});
