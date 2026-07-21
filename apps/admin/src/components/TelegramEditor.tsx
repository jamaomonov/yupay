/**
 * TelegramEditor — contenteditable WYSIWYG composer for a broadcast body.
 *
 * A toolbar (bold/italic/underline/strikethrough/spoiler/link/code) toggles marks on the
 * current selection, then the component re-serializes the live contenteditable DOM into
 * Telegram-HTML via {@link serialize} and reports it through `onChange`. Bold/italic/underline/
 * strikethrough go through `document.execCommand` — deprecated, but still the only reliable
 * cross-browser way to toggle those marks on an arbitrary selection, and still supported in
 * every target browser (see the ADR at Task 14). Spoiler/link/code have no native
 * `execCommand`, so they wrap (or unwrap) the selection manually via the Selection/Range API.
 *
 * The contenteditable element is intentionally uncontrolled between keystrokes — React would
 * otherwise fight the browser for the caret on every render. `value` only re-hydrates the DOM
 * when it changes for a reason *other* than this component's own last `onChange` call (e.g. a
 * parent switching between two drafts, or a form reset); see `lastEmittedRef` below. If
 * contenteditable ever proves too fiddly in practice, the documented fallback (Task 14's ADR)
 * is a toolbar-wrapped `<textarea>` using this same `previewHtml`/`visibleLength` pair.
 */

import {
  Bold,
  Code as CodeIcon,
  EyeOff,
  Italic,
  Link as LinkIcon,
  Strikethrough,
  Underline,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  type AllowedHtmlRenderers,
  previewHtml,
  sanitizeToAllowedHtml,
  serialize,
  visibleLength,
} from "@/features/broadcasts/telegramHtml";

interface TelegramEditorProps {
  value: string;
  onChange: (telegramHtml: string) => void;
  maxLength: number;
}

// Unlike the preview bubble, the editable DOM needs the literal `tg-spoiler` element (so a
// further edit still round-trips through `serialize`) and a bare `href` (no target/rel — those
// are display-only concerns). Everything else — the tag whitelist, the script/style drop, the
// href scheme check, the "\n" → <br> translation — comes from the one shared walker in
// telegramHtml.ts, so this can never drift from `previewHtml` the way a second hand-rolled copy
// already had (it was missing the script/style drop entirely).
const EDITABLE_RENDERERS: AllowedHtmlRenderers = {
  renderSpoiler: (inner) => `<tg-spoiler>${inner}</tg-spoiler>`,
  renderAnchor: (escapedHref, inner) => `<a href="${escapedHref}">${inner}</a>`,
};

/** Rebuild the contenteditable DOM's innerHTML from a stored Telegram-HTML body. */
function toEditableHtml(telegramHtml: string): string {
  return sanitizeToAllowedHtml(telegramHtml, EDITABLE_RENDERERS);
}

function closestWithin(node: Node, tagName: string, editor: HTMLElement): HTMLElement | null {
  let current: Node | null = node;
  while (current && current !== editor) {
    if (
      current.nodeType === Node.ELEMENT_NODE &&
      (current as HTMLElement).tagName.toLowerCase() === tagName
    ) {
      return current as HTMLElement;
    }
    current = current.parentNode;
  }
  return null;
}

function unwrapElement(el: HTMLElement): void {
  const parent = el.parentNode;
  if (!parent) return;
  while (el.firstChild) {
    parent.insertBefore(el.firstChild, el);
  }
  parent.removeChild(el);
}

/** Prevents the toolbar button's mousedown from stealing focus (and the selection) from the editor. */
function preserveSelection(event: React.MouseEvent): void {
  event.preventDefault();
}

export function TelegramEditor({ value, onChange, maxLength }: TelegramEditorProps) {
  const editorRef = useRef<HTMLDivElement>(null);
  const lastEmittedRef = useRef<string | null>(null);
  const savedRangeRef = useRef<Range | null>(null);
  const [currentHtml, setCurrentHtml] = useState(value);
  const [linkPromptOpen, setLinkPromptOpen] = useState(false);
  const [linkValue, setLinkValue] = useState("");

  // Hydrate the editable DOM only when `value` changed for a reason other than our own last
  // `onChange` — otherwise every keystroke would round-trip through the parent and rebuild the
  // DOM out from under the caret.
  useEffect(() => {
    const editor = editorRef.current;
    if (!editor || value === lastEmittedRef.current) return;
    editor.innerHTML = toEditableHtml(value);
    lastEmittedRef.current = value;
    setCurrentHtml(value);
  }, [value]);

  const emitChange = useCallback(() => {
    const editor = editorRef.current;
    if (!editor) return;
    const html = serialize(editor);
    lastEmittedRef.current = html;
    setCurrentHtml(html);
    onChange(html);
  }, [onChange]);

  const runCommand = useCallback(
    (command: string) => {
      editorRef.current?.focus();
      document.execCommand(command);
      emitChange();
    },
    [emitChange],
  );

  const toggleWrap = useCallback(
    (tagName: string) => {
      const editor = editorRef.current;
      const selection = window.getSelection();
      if (!editor || !selection || selection.rangeCount === 0) return;
      const range = selection.getRangeAt(0);
      if (!editor.contains(range.commonAncestorContainer)) return;
      const existing = closestWithin(range.commonAncestorContainer, tagName, editor);
      if (existing) {
        unwrapElement(existing);
      } else {
        if (range.collapsed) return; // wrap-based marks need an explicit selection to wrap
        const wrapper = document.createElement(tagName);
        wrapper.appendChild(range.extractContents());
        range.insertNode(wrapper);
        selection.removeAllRanges();
        const restored = document.createRange();
        restored.selectNodeContents(wrapper);
        selection.addRange(restored);
      }
      emitChange();
    },
    [emitChange],
  );

  const openLinkPrompt = useCallback(() => {
    const editor = editorRef.current;
    const selection = window.getSelection();
    if (!editor || !selection || selection.rangeCount === 0 || selection.isCollapsed) return;
    const range = selection.getRangeAt(0);
    if (!editor.contains(range.commonAncestorContainer)) return;
    savedRangeRef.current = range.cloneRange();
    setLinkValue("");
    setLinkPromptOpen(true);
  }, []);

  const confirmLink = useCallback(() => {
    const range = savedRangeRef.current;
    const raw = linkValue.trim();
    if (!range || !raw) {
      setLinkPromptOpen(false);
      return;
    }
    // A bare "example.com" typed without a scheme would otherwise fail the http(s)/tg
    // whitelist both here and on the backend — default to https so the common case works.
    const href = /^[a-z][a-z0-9+.-]*:/i.test(raw) ? raw : `https://${raw}`;
    const anchor = document.createElement("a");
    anchor.setAttribute("href", href);
    anchor.appendChild(range.extractContents());
    range.insertNode(anchor);
    setLinkPromptOpen(false);
    emitChange();
  }, [linkValue, emitChange]);

  const charCount = visibleLength(currentHtml);
  const overLimit = charCount > maxLength;

  return (
    <div className="space-y-2">
      <div
        role="toolbar"
        aria-label="Форматирование текста"
        className="flex flex-wrap items-center gap-1 rounded-t-md border border-b-0 border-[var(--border-default)] bg-[var(--bg-surface)] p-1"
      >
        <ToolbarButton
          label="Жирный"
          onMouseDown={preserveSelection}
          onClick={() => {
            runCommand("bold");
          }}
        >
          <Bold size={16} />
        </ToolbarButton>
        <ToolbarButton
          label="Курсив"
          onMouseDown={preserveSelection}
          onClick={() => {
            runCommand("italic");
          }}
        >
          <Italic size={16} />
        </ToolbarButton>
        <ToolbarButton
          label="Подчёркнутый"
          onMouseDown={preserveSelection}
          onClick={() => {
            runCommand("underline");
          }}
        >
          <Underline size={16} />
        </ToolbarButton>
        <ToolbarButton
          label="Зачёркнутый"
          onMouseDown={preserveSelection}
          onClick={() => {
            runCommand("strikeThrough");
          }}
        >
          <Strikethrough size={16} />
        </ToolbarButton>
        <ToolbarButton
          label="Спойлер"
          onMouseDown={preserveSelection}
          onClick={() => {
            toggleWrap("tg-spoiler");
          }}
        >
          <EyeOff size={16} />
        </ToolbarButton>
        <ToolbarButton
          label="Код"
          onMouseDown={preserveSelection}
          onClick={() => {
            toggleWrap("code");
          }}
        >
          <CodeIcon size={16} />
        </ToolbarButton>
        <ToolbarButton label="Ссылка" onMouseDown={preserveSelection} onClick={openLinkPrompt}>
          <LinkIcon size={16} />
        </ToolbarButton>
      </div>

      {linkPromptOpen && (
        <div className="flex items-center gap-2 border border-[var(--border-default)] bg-[var(--bg-surface)] p-2">
          <input
            autoFocus
            type="text"
            value={linkValue}
            placeholder="https://..."
            onChange={(e) => {
              setLinkValue(e.target.value);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                confirmLink();
              } else if (e.key === "Escape") {
                e.preventDefault();
                setLinkPromptOpen(false);
              }
            }}
            className="flex-1 rounded-md border border-[var(--border-default)] bg-[var(--bg-base)] px-2 py-1 text-sm"
          />
          <button
            type="button"
            className="text-xs text-[var(--accent)] underline"
            onClick={confirmLink}
          >
            Добавить
          </button>
          <button
            type="button"
            className="text-xs text-[var(--text-secondary)] underline"
            onClick={() => {
              setLinkPromptOpen(false);
            }}
          >
            Отмена
          </button>
        </div>
      )}

      <div
        ref={editorRef}
        role="textbox"
        aria-multiline="true"
        aria-label="Текст рассылки"
        contentEditable
        suppressContentEditableWarning
        onInput={emitChange}
        className="min-h-24 whitespace-pre-wrap rounded-b-md border border-[var(--border-default)] bg-[var(--bg-base)] p-3 text-sm focus:outline-none"
      />

      <div className="flex items-center justify-between text-xs text-[var(--text-secondary)]">
        <span>Предпросмотр</span>
        <span className={overLimit ? "font-medium text-[var(--danger-fg)]" : ""}>
          {charCount} / {maxLength}
        </span>
      </div>
      <div
        className="rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] p-3 text-sm"
        // Safe by construction: `previewHtml` is whitelist-guarded and never emits a tag it
        // didn't explicitly build itself (see telegramHtml.ts).
        dangerouslySetInnerHTML={{ __html: previewHtml(currentHtml) }}
      />
    </div>
  );
}

interface ToolbarButtonProps {
  label: string;
  onClick: () => void;
  onMouseDown: (event: React.MouseEvent) => void;
  children: React.ReactNode;
}

function ToolbarButton({ label, onClick, onMouseDown, children }: ToolbarButtonProps) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onMouseDown={onMouseDown}
      onClick={onClick}
      className="flex h-8 w-8 items-center justify-center rounded-md text-[var(--text-primary)] hover:bg-[var(--bg-muted)] active:bg-[var(--bg-surface-2)]"
    >
      {children}
    </button>
  );
}
