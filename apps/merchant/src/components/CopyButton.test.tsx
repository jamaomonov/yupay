import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { CopyButton } from "./CopyButton";

/**
 * A page translator and React disagree about who owns a text node.
 *
 * Chrome's translator replaces the text in place; React later tries to update
 * or remove that node, finds it is no longer its child, and throws
 * `NotFoundError: Failed to execute 'removeChild' on 'Node'` — which in this
 * cabinet means the whole page drops to its error boundary. A merchant
 * reading the Russian cabinet through the translator hit exactly that on
 * 2026-09-21, on Настройки, which by then had a copy button per API key.
 *
 * This button is the most exposed thing on the page: its label swaps to
 * «Скопировано» and back on a two-second timer. `translate="no"` is what
 * keeps the translator off it, and an attribute is the easiest thing in the
 * file to lose in a refactor — hence a test rather than a comment.
 *
 * Server-rendered to a string: this suite runs under `environment: "node"`,
 * and the attribute is in the markup either way.
 */
describe("CopyButton", () => {
  it("is marked untranslatable, because its label changes under the user", () => {
    const html = renderToStaticMarkup(
      <CopyButton value="ypm_abc" label="Скопировать" done="Скопировано" />,
    );

    expect(html).toContain('translate="no"');
  });

  it("still renders the label it was given", () => {
    const html = renderToStaticMarkup(
      <CopyButton value="ypm_abc" label="Скопировать" done="Скопировано" />,
    );

    expect(html).toContain("Скопировать");
  });
});
