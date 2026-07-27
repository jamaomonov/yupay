import path from "node:path";

import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  // apps/web's tsconfig sets `jsx: "preserve"` (Next.js compiles JSX itself
  // via SWC); Vite/esbuild reads that as "classic" and needs `React` in
  // scope unless told to use the automatic runtime here.
  esbuild: { jsx: "automatic" },
  test: { environment: "node", globals: true, include: ["src/**/*.test.{ts,tsx}"] },
});
