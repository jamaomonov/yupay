import { expect, test } from "@playwright/test";

/**
 * A <dl> whose direct children aren't <dt>/<dd> groups (or the <div>, <script>,
 * <template> wrappers the spec allows) is dropped from the accessibility tree
 * as a list — screen readers and agent crawlers lose the term/value pairing,
 * while the page still looks perfectly fine. That is exactly how a stray <p>
 * of explanatory prose reached production inside the Steam rate/fee/limit list.
 */
const PAGES = ["/", "/store", "/store/steam", "/store/pubg-mobile", "/store/pubg-mobile/how-to"];

const ALLOWED_CHILDREN = ["DT", "DD", "DIV", "SCRIPT", "TEMPLATE"];

for (const path of PAGES) {
  test(`description lists are well-formed on ${path}`, async ({ page }) => {
    await page.goto(path);

    const offenders = await page.evaluate(
      (allowed) =>
        [...document.querySelectorAll("dl")].flatMap((dl) =>
          [...dl.children]
            .filter((child) => !allowed.includes(child.tagName))
            .map((child) => `<${child.tagName.toLowerCase()}> in dl.${dl.className}`),
        ),
      ALLOWED_CHILDREN,
    );

    expect(offenders).toEqual([]);
  });
}
