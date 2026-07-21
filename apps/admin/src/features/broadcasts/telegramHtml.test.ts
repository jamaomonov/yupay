import { describe, expect, test } from "vitest";

import {
  ALLOWED_TAGS,
  type AllowedHtmlRenderers,
  MAX_TEXT,
  MAX_WITH_MEDIA,
  previewHtml,
  sanitizeToAllowedHtml,
  serialize,
  visibleLength,
} from "./telegramHtml";

/** Editor-style renderers (mirrors `TelegramEditor.tsx`'s `EDITABLE_RENDERERS`): the literal
 * `tg-spoiler` element and a bare `href`, as opposed to `previewHtml`'s span/target/rel. Used
 * to prove the shared sanitizer behind both call sites can't drift — see the "unify" fix. */
const EDITOR_RENDERERS: AllowedHtmlRenderers = {
  renderSpoiler: (inner) => `<tg-spoiler>${inner}</tg-spoiler>`,
  renderAnchor: (href, inner) => `<a href="${href}">${inner}</a>`,
};

describe("constants", () => {
  test("length ceilings mirror Telegram's caption/message limits", () => {
    expect(MAX_WITH_MEDIA).toBe(1024);
    expect(MAX_TEXT).toBe(4096);
  });

  test("ALLOWED_TAGS mirrors the backend validator's whitelist exactly", () => {
    expect([...ALLOWED_TAGS].sort()).toEqual(
      ["a", "b", "blockquote", "code", "i", "pre", "s", "tg-spoiler", "u"].sort(),
    );
  });
});

describe("serialize", () => {
  test("wraps a <b> mark", () => {
    const root = document.createElement("div");
    const b = document.createElement("b");
    b.textContent = "hi";
    root.appendChild(b);
    expect(serialize(root)).toBe("<b>hi</b>");
  });

  test("wraps every inline mark tag (i/u/s/code)", () => {
    const root = document.createElement("div");
    for (const tag of ["i", "u", "s", "code"]) {
      const el = document.createElement(tag);
      el.textContent = tag;
      root.appendChild(el);
    }
    expect(serialize(root)).toBe("<i>i</i><u>u</u><s>s</s><code>code</code>");
  });

  test("wraps a spoiler mark", () => {
    const root = document.createElement("div");
    const spoiler = document.createElement("tg-spoiler");
    spoiler.textContent = "secret";
    root.appendChild(spoiler);
    expect(serialize(root)).toBe("<tg-spoiler>secret</tg-spoiler>");
  });

  test("nests marks in document order", () => {
    const root = document.createElement("div");
    const b = document.createElement("b");
    const i = document.createElement("i");
    i.textContent = "hi";
    b.appendChild(i);
    root.appendChild(b);
    expect(serialize(root)).toBe("<b><i>hi</i></b>");
  });

  test("two block elements become newline-separated lines", () => {
    const root = document.createElement("div");
    const line1 = document.createElement("div");
    line1.textContent = "a";
    const line2 = document.createElement("div");
    line2.textContent = "b";
    root.append(line1, line2);
    expect(serialize(root)).toBe("a\nb");
  });

  test("a <br> becomes a newline", () => {
    const root = document.createElement("div");
    root.append("a", document.createElement("br"), "b");
    expect(serialize(root)).toBe("a\nb");
  });

  test("block followed by a bare inline text sibling still gets a boundary", () => {
    // Regression: the boundary check only looked at the *upcoming* child being a block, so a
    // block followed by a plain text node (no wrapping element) missed the boundary entirely
    // and produced "ab".
    const root = document.createElement("div");
    const line = document.createElement("div");
    line.textContent = "a";
    root.append(line, "b");
    expect(serialize(root)).toBe("a\nb");
  });

  test("bare inline text followed by a block gets a boundary", () => {
    const root = document.createElement("div");
    const line = document.createElement("div");
    line.textContent = "b";
    root.append("a", line);
    expect(serialize(root)).toBe("a\nb");
  });

  test("an interior blank line (empty <div><br></div>) is preserved as one extra newline", () => {
    const root = document.createElement("div");
    const first = document.createElement("div");
    first.textContent = "a";
    const blank = document.createElement("div");
    blank.appendChild(document.createElement("br"));
    const last = document.createElement("div");
    last.textContent = "b";
    root.append(first, blank, last);
    expect(serialize(root)).toBe("a\n\nb");
  });

  test("a trailing blank line (contenteditable's caret placeholder) is trimmed, not doubled", () => {
    // The standard "pressed Enter at the end" DOM: two content lines, then an empty
    // <div><br></div> marking where the caret currently sits on a blank final line. That
    // trailing artifact should disappear entirely, not surface as an extra "\n\n".
    const root = document.createElement("div");
    const line1 = document.createElement("div");
    line1.textContent = "line1";
    const line2 = document.createElement("div");
    line2.textContent = "line2";
    const trailingBlank = document.createElement("div");
    trailingBlank.appendChild(document.createElement("br"));
    root.append(line1, line2, trailingBlank);
    expect(serialize(root)).toBe("line1\nline2");
  });

  test("escapes <, >, and & in a bare text node", () => {
    const root = document.createElement("div");
    root.appendChild(document.createTextNode("1 < 2 & 3 > 0"));
    expect(serialize(root)).toBe("1 &lt; 2 &amp; 3 &gt; 0");
  });

  test("keeps an anchor with an allowed http(s) href", () => {
    const root = document.createElement("div");
    const a = document.createElement("a");
    a.setAttribute("href", "https://yupay.uz/x?a=1&b=2");
    a.textContent = "link";
    root.appendChild(a);
    expect(serialize(root)).toBe('<a href="https://yupay.uz/x?a=1&amp;b=2">link</a>');
  });

  test("keeps an anchor with a tg:// deep-link href", () => {
    const root = document.createElement("div");
    const a = document.createElement("a");
    a.setAttribute("href", "tg://resolve?domain=yupay");
    a.textContent = "open";
    root.appendChild(a);
    expect(serialize(root)).toBe('<a href="tg://resolve?domain=yupay">open</a>');
  });

  test("drops an anchor with a disallowed scheme but keeps its text", () => {
    const root = document.createElement("div");
    const a = document.createElement("a");
    a.setAttribute("href", "javascript:alert(1)");
    a.textContent = "click";
    root.appendChild(a);
    expect(serialize(root)).toBe("click");
  });

  test("unwraps a plain <span> (no allowed tag) but keeps its text", () => {
    const root = document.createElement("div");
    const span = document.createElement("span");
    span.textContent = "plain";
    root.appendChild(span);
    expect(serialize(root)).toBe("plain");
  });
});

describe("visibleLength", () => {
  test("strips tags before counting", () => {
    expect(visibleLength("<b>ab</b>")).toBe(2);
  });

  test("decodes an entity exactly once", () => {
    expect(visibleLength("a &amp; b")).toBe("a & b".length);
  });

  test("counts a literal newline as one visible character", () => {
    expect(visibleLength("a\nb")).toBe(3);
  });
});

describe("previewHtml", () => {
  test("turns tg-spoiler into a whitelisted span, never emitting the raw tag", () => {
    const out = previewHtml("<tg-spoiler>x</tg-spoiler>");
    expect(out).toContain('class="spoiler"');
    expect(out).not.toContain("tg-spoiler");
  });

  test("turns a literal newline into <br>", () => {
    expect(previewHtml("a\nb")).toBe("a<br>b");
  });

  test("passes an allowed mark straight through", () => {
    expect(previewHtml("<b>hi</b>")).toBe("<b>hi</b>");
  });

  test("neutralizes a <script> injection attempt mid-body", () => {
    // A *lone* "<script>...</script>" with no surrounding text gets parsed into `doc.head` by
    // the HTML parser (nothing yet forced "in body" insertion mode), so a test using only that
    // string would pass even without the DROP_CONTENT_TAGS check — previewHtml only ever walks
    // `doc.body`. Surrounding text forces the parser into body mode first, so the <script>
    // actually lands where previewHtml has to deal with it.
    const out = previewHtml("before <script>alert(1)</script> after");
    expect(out.toLowerCase()).not.toContain("<script");
    expect(out).not.toContain("alert(1)");
    expect(out).toContain("before");
    expect(out).toContain("after");
  });

  test("strips an onclick attribute from an otherwise-allowed tag", () => {
    const out = previewHtml('<b onclick="alert(1)">y</b>');
    expect(out).toBe("<b>y</b>");
    expect(out).not.toContain("onclick");
  });

  test("strips an event-handler attribute smuggled on an unknown tag", () => {
    const out = previewHtml('<img src="x" onerror="alert(1)">');
    expect(out).not.toContain("onerror");
    expect(out).not.toContain("<img");
  });

  test("drops a disallowed href scheme instead of emitting a live link", () => {
    const out = previewHtml('<a href="javascript:alert(1)">click</a>');
    expect(out).not.toContain("javascript:");
    expect(out).toContain("click");
  });
});

describe("sanitizeToAllowedHtml (shared by previewHtml and TelegramEditor's hydration)", () => {
  test("editor-style renderers keep the literal tg-spoiler element", () => {
    const out = sanitizeToAllowedHtml("<tg-spoiler>x</tg-spoiler>", EDITOR_RENDERERS);
    expect(out).toBe("<tg-spoiler>x</tg-spoiler>");
  });

  test("editor-style renderers keep a bare href with no target/rel", () => {
    const out = sanitizeToAllowedHtml('<a href="https://yupay.uz">link</a>', EDITOR_RENDERERS);
    expect(out).toBe('<a href="https://yupay.uz">link</a>');
  });

  test("drops <script> content for the editor's hydration too, not just the preview bubble", () => {
    // This is the exact regression the coordinator flagged: a second, hand-rolled whitelist
    // walker in TelegramEditor.tsx had drifted and no longer dropped script/style content, so
    // `toEditableHtml('hello <script>alert(1)</script> world')` used to leak "alert(1)" as
    // literal visible editor text. Now both call sites share this one walker.
    const out = sanitizeToAllowedHtml("hello <script>alert(1)</script> world", EDITOR_RENDERERS);
    expect(out.toLowerCase()).not.toContain("<script");
    expect(out).not.toContain("alert(1)");
  });
});
