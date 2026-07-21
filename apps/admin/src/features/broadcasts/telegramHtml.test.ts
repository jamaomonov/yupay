import { describe, expect, test } from "vitest";

import {
  ALLOWED_TAGS,
  MAX_TEXT,
  MAX_WITH_MEDIA,
  previewHtml,
  serialize,
  visibleLength,
} from "./telegramHtml";

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

  test("neutralizes a <script> injection attempt", () => {
    const out = previewHtml("<script>alert(1)</script>");
    expect(out.toLowerCase()).not.toContain("<script");
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
