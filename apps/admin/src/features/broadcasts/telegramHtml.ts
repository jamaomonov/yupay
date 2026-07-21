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

/** True when `node` is a block element whose only content is a single `<br>` — the DOM shape
 * browsers use for a blank line (e.g. after pressing Enter at the end of a composer). Its `<br>`
 * already gets to *be* the newline via the block-boundary logic in `serializeChildren`; if we
 * also serialized it as a child we'd double the newline (see `serializeChildren`'s docstring). */
function isEmptyBlockLine(node: HTMLElement, tag: string): boolean {
  return (
    BLOCK_TAGS.has(tag) &&
    node.childNodes.length === 1 &&
    node.firstChild !== null &&
    isElement(node.firstChild) &&
    node.firstChild.tagName.toLowerCase() === "br"
  );
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

  const inner = isEmptyBlockLine(node, tag) ? "" : serializeChildren(node);

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

/**
 * Join a node's children into one string, inserting a single ``"\n"`` at every block-level
 * boundary.
 *
 * The boundary check is deliberately bidirectional — a boundary exists if *either* side of an
 * adjacent pair is a block-level element, not just the upcoming child — otherwise a block
 * followed by a bare inline/text sibling (e.g. ``<div>a</div>`` then a text node ``"b"``, which
 * contenteditable produces plenty of) would serialize as ``"ab"`` instead of ``"a\nb"``: only
 * checking the *next* child misses the boundary on the trailing side of the block that just
 * ended.
 */
function serializeChildren(parent: Node): string {
  const parts: string[] = [];
  let previousWasBlock = false;
  for (const child of Array.from(parent.childNodes)) {
    const isBlock = isElement(child) && BLOCK_TAGS.has(child.tagName.toLowerCase());
    if (parts.length > 0 && (isBlock || previousWasBlock)) {
      parts.push("\n");
    }
    parts.push(serializeNode(child));
    previousWasBlock = isBlock;
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
 *
 * Trailing newlines are trimmed: contenteditable typically leaves a trailing
 * ``<div><br></div>`` wherever the caret currently sits on a blank final line, which is a DOM
 * artifact, not authored content — and Telegram trims trailing whitespace from a sent message
 * anyway, so dropping it here is safe.
 */
export function serialize(root: HTMLElement): string {
  return serializeChildren(root).replace(/\s+$/, "");
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

/**
 * Per-caller output for the two tags {@link sanitizeToAllowedHtml} can't render generically:
 * ``tg-spoiler`` and ``<a>`` each need a different concrete target tag depending on who's
 * consuming the result (see {@link sanitizeToAllowedHtml}'s docstring).
 */
export interface AllowedHtmlRenderers {
  /** Render a ``tg-spoiler`` element's already-sanitized inner HTML. */
  renderSpoiler: (inner: string) => string;
  /** Render an ``<a>`` whose ``href`` already passed the scheme whitelist and is attr-escaped. */
  renderAnchor: (escapedHref: string, inner: string) => string;
}

function sanitizeNode(node: Node, renderers: AllowedHtmlRenderers): string {
  if (node.nodeType === Node.TEXT_NODE) {
    // Telegram HTML has no <br>; a literal "\n" is the only line-break marker. Both consumers
    // of this walker need it turned into a real line break: the preview bubble because raw
    // HTML collapses "\n" to a space, and the editor's hydration because a bare "\n" text
    // character round-trips back out through `serialize` identically to a `<br>` anyway (see
    // `serializeNode`), so giving the editor a real `<br>` element is both correct and simpler
    // than teaching it to preserve a raw newline character in a text node.
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

  const children = (): string =>
    Array.from(node.childNodes)
      .map((child) => sanitizeNode(child, renderers))
      .join("");

  if (tag === "a") {
    const href = node.getAttribute("href") ?? "";
    const scheme = hrefScheme(href);
    if (scheme !== null && ALLOWED_HREF_SCHEMES.has(scheme)) {
      return renderers.renderAnchor(escapeAttr(href), children());
    }
    return children();
  }

  if (tag === "tg-spoiler") {
    return renderers.renderSpoiler(children());
  }

  if (ALLOWED_TAGS.has(tag)) {
    // b/i/u/s/code/pre/blockquote pass straight through, same tag name, no attributes copied.
    return `<${tag}>${children()}</${tag}>`;
  }

  // Any non-whitelisted tag — a stray <div>, an <img onerror=...>, an attacker's <svg>/<iframe>
  // — is unwrapped: keep its visible text, drop the tag and every attribute so nothing but the
  // fixed set above can ever reach the sink this output feeds.
  return children();
}

/**
 * Parse ``telegramHtml`` and rebuild it through {@link ALLOWED_TAGS} only — the single shared
 * whitelist walker behind both {@link previewHtml} (a ``dangerouslySetInnerHTML`` target) and
 * ``TelegramEditor``'s contenteditable hydration (an ``innerHTML =`` assignment) — two sinks
 * exactly as sensitive as each other. Keeping one walker means the two call sites can't drift
 * out of sync the way a second hand-rolled copy inevitably would (and did: an earlier duplicate
 * in ``TelegramEditor.tsx`` forgot to drop ``<script>``/``<style>`` content).
 *
 * ``tg-spoiler`` and ``<a>`` are the only tags whose *output* differs by caller — the preview
 * wants a ``<span class="spoiler">`` and a real, clickable, scheme-checked link; the editor
 * wants the literal ``tg-spoiler`` element and a bare ``href`` so a further edit still
 * round-trips through {@link serialize} — so callers supply `renderers` for exactly those two.
 * Every other allowed tag, the ``<script>``/``<style>`` drop, and the attribute stripping are
 * identical between callers by construction, not by convention.
 */
export function sanitizeToAllowedHtml(
  telegramHtml: string,
  renderers: AllowedHtmlRenderers,
): string {
  const doc = new DOMParser().parseFromString(telegramHtml, "text/html");
  return Array.from(doc.body.childNodes)
    .map((node) => sanitizeNode(node, renderers))
    .join("");
}

const PREVIEW_RENDERERS: AllowedHtmlRenderers = {
  renderSpoiler: (inner) => `<span class="spoiler">${inner}</span>`,
  renderAnchor: (escapedHref, inner) =>
    `<a href="${escapedHref}" target="_blank" rel="noopener noreferrer">${inner}</a>`,
};

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
  return sanitizeToAllowedHtml(telegramHtml, PREVIEW_RENDERERS);
}
