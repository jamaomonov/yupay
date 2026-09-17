import { readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * `index.html` is the one file in this app that runs before the app does, and
 * the failure it caused is not the kind a component test can see.
 *
 * Telegram's bridge used to load as a blocking `<script>` from
 * `https://telegram.org/js/telegram-web-app.js`. Some Uzbek carriers drop that
 * domain — the Telegram *app* is unaffected, it talks to its own data centres —
 * and a blocking script in `<head>` that never answers stops the parser before
 * `<body>` exists. Measured against the real site with the domain dropped: our
 * HTML arrived in 184 ms, then nothing painted for 25 s. Telegram's webview
 * calls that a failed load and tells the user the mini app is broken.
 *
 * So: nothing in the critical path may come from a host we do not serve, and
 * the page must carry something to paint on its own.
 */

const ROOT = join(__dirname, "..");
const HTML = readFileSync(join(ROOT, "index.html"), "utf8");

describe("index.html", () => {
  it("loads no script from a third-party origin", () => {
    const external = [...HTML.matchAll(/<script[^>]*\ssrc=["'](https?:)?\/\/[^"']+["']/gi)].map(
      (m) => m[0],
    );
    expect(external).toEqual([]);
  });

  it("takes Telegram's bridge from our own origin, deferred", () => {
    const tag = /<script([^>]*)src=["']\/js\/telegram-web-app\.js["']([^>]*)>/i.exec(HTML);
    expect(tag, "the bridge must be served from /js/telegram-web-app.js").not.toBeNull();
    // Deferred, not blocking: execution order against the module below is
    // preserved, and the parser never waits for the file.
    expect(`${tag?.[1] ?? ""}${tag?.[2] ?? ""}`).toMatch(/\bdefer\b/);
  });

  it("ships the bridge it points at", () => {
    const vendored = join(ROOT, "public/js/telegram-web-app.js");
    const source = readFileSync(vendored, "utf8");
    // Big enough to be the real thing rather than a stub or an error page,
    // and it must define the object the app reads (`lib/telegram.ts`).
    expect(statSync(vendored).size).toBeGreaterThan(50_000);
    expect(source).toContain("window.Telegram");
    expect(source).toContain("WebApp");
  });

  it("paints something before the bundle arrives", () => {
    const root = /<div id="root">([\s\S]*?)<\/div>\s*<style>/.exec(HTML);
    expect(root, "#root must carry the boot screen").not.toBeNull();
    // The words the user sees while 220 KB of JS is still in flight, and the
    // way out if it never lands. React's `createRoot` clears all of it on the
    // first commit, so nothing here needs removing by hand.
    expect(root?.[1]).toContain("Загружаем…");
    expect(HTML).toContain('id="boot-retry"');
    expect(HTML).toContain("location.reload()");
  });
});
