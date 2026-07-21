import path from "node:path";

import { defineConfig } from "vitest/config";

export default defineConfig({
  // Mirrors the "@/..." alias in vite.config.ts. Needed once a test imports
  // a module (or a transitive dependency of one) via that path alias —
  // vitest.config.ts is a separate Vite config and doesn't inherit it.
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  test: { environment: "jsdom", globals: true, include: ["src/**/*.test.{ts,tsx}"] },
});
