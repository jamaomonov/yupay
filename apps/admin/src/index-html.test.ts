import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const ROOT = join(__dirname, "..");
const HTML = readFileSync(join(ROOT, "index.html"), "utf8");

/**
 * The CSP on this site (infra/caddy/Caddyfile.prod) allows inline scripts by
 * hash only, so editing one without updating the header silently stops it
 * running in production. Hashes never cover inline handlers (`onclick=`).
 */
describe("Content-Security-Policy", () => {
  const caddy = readFileSync(join(ROOT, "../../infra/caddy/Caddyfile.prod"), "utf8");
  const inline = [...HTML.matchAll(/<script(?![^>]*\ssrc=)[^>]*>([\s\S]*?)<\/script>/gi)].map(
    (m) => m[1] ?? "",
  );

  it("allows every inline script by its hash", () => {
    expect(inline.length).toBeGreaterThan(0);
    for (const body of inline) {
      const hash = `sha256-${createHash("sha256").update(body).digest("base64")}`;
      expect(caddy, `add '${hash}' to the CSP in Caddyfile.prod`).toContain(hash);
    }
  });

  it("has no inline event handlers", () => {
    expect(HTML).not.toMatch(/<[^>]+\son[a-z]+\s*=/i);
  });
});
