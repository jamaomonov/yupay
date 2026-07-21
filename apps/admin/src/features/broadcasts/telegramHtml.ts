/**
 * Pure Telegram-HTML helpers shared by the broadcast composer.
 *
 * Telegram's "HTML" parse mode (https://core.telegram.org/bots/api#html-style) is a small
 * whitelist of inline marks — it has no block elements and no ``<br>``; every line break is a
 * literal ``\n`` character. ``ALLOWED_TAGS`` mirrors
 * ``apps/api/src/yupay/modules/broadcasts/sanitize.py::ALLOWED_TAGS`` exactly, so the admin
 * editor can never author a body the backend validator would then reject.
 *
 * - {@link serialize} walks a contenteditable ``HTMLElement`` (the live DOM the browser builds
 *   while the admin types) into that Telegram-HTML string.
 * - {@link previewHtml} goes the other way — Telegram-HTML → a safe HTML string for the admin's
 *   own preview bubble (a ``dangerouslySetInnerHTML`` target). It whitelist-guards
 *   independently of the backend: a stored or hand-typed body must never be able to inject a
 *   ``<script>``, an event-handler attribute, or any non-whitelisted tag into the admin page.
 * - {@link visibleLength} mirrors ``sanitize.visible_length`` — the character count Telegram's
 *   1024/4096 caption/message ceilings are enforced against (tags stripped, entities decoded
 *   exactly once).
 */

/** Same tag whitelist as the backend validator (``sanitize.ALLOWED_TAGS``). */
export const ALLOWED_TAGS: ReadonlySet<string> = new Set([
  "b",
  "i",
  "u",
  "s",
  "a",
  "code",
  "pre",
  "tg-spoiler",
  "blockquote",
]);

/** Telegram's caption-length ceiling — applies when the broadcast attaches media. */
export const MAX_WITH_MEDIA = 1024;

/** Telegram's plain-message-length ceiling — applies with no attached media. */
export const MAX_TEXT = 4096;

/** ``<a href>`` schemes the backend validator accepts (``sanitize._ALLOWED_ANCHOR_SCHEMES``). */
const ALLOWED_HREF_SCHEMES: ReadonlySet<string> = new Set(["http:", "https:", "tg:"]);

/**
 * contenteditable tag names that normalize to a Telegram mark tag.
 *
 * Keyed by the lower-cased ``tagName`` the browser actually produces (``document.execCommand``
 * inserts ``<b>``/``<i>`` in every current target browser, but ``<strong>``/``<em>``/``<strike>``
 * are tolerated too, in case a body was pasted in from elsewhere).
 */
const MARK_ALIASES: Readonly<Record<string, string>> = {
  b: "b",
  strong: "b",
  i: "i",
  em: "i",
  u: "u",
  s: "s",
  strike: "s",
  del: "s",
  code: "code",
  pre: "pre",
  "tg-spoiler": "tg-spoiler",
  blockquote: "blockquote",
};

/** contenteditable tag names treated as block-level — a boundary becomes ``"\n"``, never ``<br>``. */
const BLOCK_TAGS: ReadonlySet<string> = new Set([
  "div",
  "p",
  "li",
  "ul",
  "ol",
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
]);

/** Tags whose entire content is dropped in the preview — pure injection vectors, never visible text. */
const DROP_CONTENT_TAGS: ReadonlySet<string> = new Set(["script", "style"]);

function escapeText(text: string): string {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function escapeAttr(value: string): string {
  return escapeText(value).replace(/"/g, "&quot;");
}

/**
 * Resolve an href's scheme, mirroring the backend's ``urlsplit(href).scheme`` check.
 *
 * Returns null for a relative/scheme-less href (``new URL`` needs a base to resolve one, and a
 * scheme-less href is exactly the case the backend's whitelist check rejects too).
 */
function hrefScheme(href: string): string | null {
  try {
    return new URL(href).protocol;
  } catch {
    return null;
  }
}

function isElement(node: Node): node is HTMLElement {
  return node.nodeType === Node.ELEMENT_NODE;
}

function serializeNode(node: Node): string {
  if (node.nodeType === Node.TEXT_NODE) {
    return escapeText(node.textContent ?? "");
  }
  if (!isElement(node)) {
    // Comments and other non-content node types carry nothing visible.
    return "";
  }
  const tag = node.tagName.toLowerCase();

  if (tag === "br") {
    return "\n";
  }

  const inner = serializeChildren(node);

  if (tag === "a") {
    const href = node.getAttribute("href") ?? "";
    const scheme = hrefScheme(href);
    if (scheme !== null && ALLOWED_HREF_SCHEMES.has(scheme)) {
      return `<a href="${escapeAttr(href)}">${inner}</a>`;
    }
    // Disallowed scheme: drop the anchor wrapper but keep its visible text, same as the
    // backend would reject the tag outright rather than silently keep a dead link.
    return inner;
  }

  const mark = MARK_ALIASES[tag];
  if (mark !== undefined) {
    return `<${mark}>${inner}</${mark}>`;
  }

  // Anything else — a bare <span>/<font>/whatever the browser or a paste inserted, and every
  // block container — contributes no tag of its own; block boundaries are handled by the
  // parent's child-walk below.
  return inner;
}

function serializeChildren(parent: Node): string {
  const parts: string[] = [];
  for (const child of Array.from(parent.childNodes)) {
    if (isElement(child) && BLOCK_TAGS.has(child.tagName.toLowerCase()) && parts.length > 0) {
      parts.push("\n");
    }
    parts.push(serializeNode(child));
  }
  return parts.join("");
}

/**
 * Walk a contenteditable DOM subtree into a Telegram-HTML string.
 *
 * Marks (``b/i/u/s/code/pre/tg-spoiler/blockquote``) and anchors round-trip as their Telegram
 * tag; a block-level boundary (``<div>``, ``<p>``, ...) between two pieces of content becomes a
 * single ``"\n"`` (Telegram HTML has no ``<br>``-equivalent block model); everything else is
 * unwrapped to its visible text, with ``<``, ``>``, ``&`` escaped.
 */
export function serialize(root: HTMLElement): string {
  return serializeChildren(root);
}

/**
 * Return ``telegramHtml`` as the recipient will actually see it — mirrors
 * ``sanitize.visible_length``: every tag stripped, every entity decoded exactly once.
 *
 * Assumes structurally-valid input, same as the backend — this is normally called only on a
 * body this same module produced (via {@link serialize}) or one the backend has already
 * validated.
 */
export function visibleLength(telegramHtml: string): number {
  const doc = new DOMParser().parseFromString(telegramHtml, "text/html");
  // `Element.textContent`'s getter is non-nullable (unlike the base `Node` one used elsewhere
  // in this module for arbitrary child nodes), so no `?? ""` fallback is needed here.
  return doc.body.textContent.length;
}

function previewNode(node: Node): string {
  if (node.nodeType === Node.TEXT_NODE) {
    // Telegram HTML has no <br>; a literal "\n" is the only line-break marker, so the preview
    // bubble must translate it explicitly to actually wrap like Telegram's client would.
    return escapeText(node.textContent ?? "").replace(/\n/g, "<br>");
  }
  if (!isElement(node)) {
    return "";
  }
  const tag = node.tagName.toLowerCase();

  if (DROP_CONTENT_TAGS.has(tag)) {
    // A <script>/<style> injection attempt: drop the whole subtree, not just the tag — its
    // "text" is never meaningful visible content.
    return "";
  }

  const children = (): string => Array.from(node.childNodes).map(previewNode).join("");

  if (tag === "a") {
    const href = node.getAttribute("href") ?? "";
    const scheme = hrefScheme(href);
    if (scheme !== null && ALLOWED_HREF_SCHEMES.has(scheme)) {
      return `<a href="${escapeAttr(href)}" target="_blank" rel="noopener noreferrer">${children()}</a>`;
    }
    return children();
  }

  if (tag === "tg-spoiler") {
    return `<span class="spoiler">${children()}</span>`;
  }

  if (ALLOWED_TAGS.has(tag)) {
    // b/i/u/s/code/pre/blockquote pass straight through, same tag name, no attributes copied.
    return `<${tag}>${children()}</${tag}>`;
  }

  // Any non-whitelisted tag — a stray <div>, an <img onerror=...>, an attacker's <svg>/<iframe>
  // — is unwrapped: keep its visible text, drop the tag and every attribute so nothing but the
  // fixed set above can ever reach `dangerouslySetInnerHTML`.
  return children();
}

/**
 * Turn a Telegram-HTML body into safe HTML for the admin's preview bubble.
 *
 * Whitelist-guarded independently of the backend validator: only {@link ALLOWED_TAGS} survive
 * (``tg-spoiler`` becomes a ``<span class="spoiler">``, ``<a>`` keeps only a scheme-checked
 * ``href``); every other tag — and every attribute other than ``href`` — is stripped, and
 * ``<script>``/``<style>`` subtrees are dropped entirely. Never emits a tag it didn't
 * explicitly construct itself, so a stored or hand-typed body can never inject markup into the
 * admin page via this function's output.
 */
export function previewHtml(telegramHtml: string): string {
  const doc = new DOMParser().parseFromString(telegramHtml, "text/html");
  return Array.from(doc.body.childNodes).map(previewNode).join("");
}
