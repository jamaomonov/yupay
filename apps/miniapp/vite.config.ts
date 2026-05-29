import path from "node:path";
import { fileURLToPath } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Where the FastAPI container can be reached from inside Docker. When `vite
// dev` runs on the host (no compose), fall back to localhost. Override via
// VITE_DEV_API_TARGET if you proxy to a different backend.
const apiTarget =
  process.env.VITE_DEV_API_TARGET ??
  (process.env.DOCKER_CONTAINER ? "http://api:8000" : "http://localhost:8000");

// Public host the browser uses to reach this dev server — required for HMR
// over ngrok / Telegram, because the default `ws://localhost:5173` baked into
// the client wouldn't reach the dev server from a public HTTPS origin.
// Leave unset for plain `localhost:3001` browsing and HMR will use defaults.
const hmrHost = process.env.VITE_HMR_HOST?.trim() || null;
const hmrProtocol = process.env.VITE_HMR_PROTOCOL?.trim() || "wss";
const hmrClientPort = Number(process.env.VITE_HMR_CLIENT_PORT ?? 443);

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    // Order matters: `@yupay/i18n/locales` must precede `@yupay/i18n` so the
    // JSON-catalog subpath resolves to the package's `locales/` dir, not its
    // entry file. Vite has no tsconfig-paths plugin, so without these aliases
    // it resolves the workspace package only through the pnpm node_modules
    // symlink — which a stale Docker anon-volume (see docker-compose.yml) can
    // lack. Aliasing straight to the bind-mounted source makes it deterministic.
    alias: {
      "@assets": path.resolve(__dirname, "src/assets"),
      "@": path.resolve(__dirname, "src"),
      "@yupay/i18n/locales": path.resolve(__dirname, "../../packages/i18n/locales"),
      "@yupay/i18n": path.resolve(__dirname, "../../packages/i18n/src/index.ts"),
    },
    dedupe: ["react", "react-dom"],
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
    strictPort: true,
    // Accept any Host header so requests proxied through ngrok / Caddy / Telegram
    // aren't rejected by Vite's host-check. Safe in dev because the server is
    // never exposed publicly without an intentional tunnel.
    allowedHosts: true,
    // Bind-mounted source on macOS/Windows Docker Desktop doesn't reliably emit
    // inotify events; polling is the only safe default for dev hot-reload.
    watch: {
      usePolling: true,
      interval: 200,
    },
    // Hot Module Reload websocket. When the dev server sits behind ngrok we
    // need the client to dial the *public* host on 443/wss, not the in-app
    // default of localhost:5173. Set the three VITE_HMR_* env vars to enable.
    hmr: hmrHost
      ? {
          host: hmrHost,
          protocol: hmrProtocol,
          clientPort: hmrClientPort,
        }
      : undefined,
    // Mirror the production nginx routes: SPA owns everything except
    // `/api/*` and `/webhooks/*`, which proxy straight to the FastAPI
    // container. Keeps "same-origin" calls from the SPA working without
    // CORS or mixed-content surprises.
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
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: false,
  },
});
