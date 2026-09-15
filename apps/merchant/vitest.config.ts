import path from "node:path";

import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  // Same reason apps/web states: the tsconfig leaves JSX to Next's compiler,
  // so esbuild needs to be told to use the automatic runtime.
  esbuild: { jsx: "automatic" },
  test: { environment: "node", globals: true, include: ["src/**/*.test.{ts,tsx}"] },
});
