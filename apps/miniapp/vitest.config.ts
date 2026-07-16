import path from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  // Mirrors the alias set in vite.config.ts. Needed once a node test imports
  // a module (or a transitive dependency of one) via the "@/..." path alias
  // — vitest.config.ts is a separate Vite config and doesn't inherit it.
  resolve: {
    alias: {
      "@assets": path.resolve(__dirname, "src/assets"),
      "@": path.resolve(__dirname, "src"),
      "@yupay/i18n/locales": path.resolve(__dirname, "../../packages/i18n/locales"),
      "@yupay/i18n": path.resolve(__dirname, "../../packages/i18n/src/index.ts"),
    },
  },
  test: { environment: "node", globals: true, include: ["src/**/*.test.{ts,tsx}"] },
});
