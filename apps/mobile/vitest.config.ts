import { defineConfig } from "vitest/config";

// Unit tests cover plain-TS logic only (formatting, mapping); screens are checked on device.
export default defineConfig({
  test: { include: ["src/**/*.test.ts"], environment: "node" },
});
