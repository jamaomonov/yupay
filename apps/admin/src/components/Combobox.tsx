/** Searchable single-select combobox.
 *
 * Generic over the item type — pass ``items``, a ``keyFor`` and a
 * ``renderItem`` function. The wrapper owns the open/closed state, the
 * keyboard navigation (↑↓ Enter Esc Tab), the debounced search input,
 * and the popover positioning. Data-fetching stays in the caller — pass
 * ``loading`` / ``empty`` / ``error`` so the dropdown can mirror the
 * upstream query state without coupling to TanStack Query here.
 *
 * Why not pull in cmdk / downshift / react-aria's combobox: we need one
 * combobox in three places (SKU, G2B product, G2B game), the keyboard
 * surface is small, and a 150-line component beats adding a new
 * upstream that the design system has to track. */

import { Check, ChevronsUpDown, Search, X } from "lucide-react";
import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";

export interface ComboboxProps<T> {
  /** Currently selected value, if any. */
  value: T | null;
  /** Fires when the user picks an item from the list (or clears it). */
  onChange: (next: T | null) => void;
  /** Items rendered in the dropdown. Filter upstream when async; this
   *  component does no client-side filtering so server-side ranking is
   *  authoritative. */
  items: T[];
  /** Stable identity for ``key=`` props + selection comparison. */
  keyFor: (item: T) => string;
  /** Row content inside the dropdown. */
  renderItem: (item: T, active: boolean) => ReactNode;
  /** Compact text rendered inside the closed control. */
  renderSelected: (item: T) => ReactNode;
  /** Placeholder text shown when ``value`` is null. */
  placeholder?: string;
  /** Live search query (lifted state — the caller debounces and fetches
   *  on it). */
  query: string;
  onQueryChange: (q: string) => void;
  /** Async-data signals. */
  loading?: boolean;
  /** Custom empty-state message; defaults to a generic line. */
  emptyMessage?: ReactNode;
  /** Render to surface a fatal fetch error inside the dropdown. */
  errorMessage?: ReactNode;
  /** Allow clearing the current value via an ``×`` chip. Default true. */
  clearable?: boolean | undefined;
  /** Disabled state — locks the popover and greys the trigger. */
  disabled?: boolean | undefined;
  /** ``id`` for the trigger button, useful for ``<label>`` association. */
  id?: string | undefined;
  /** ``aria-label`` for screen readers when no visible label is present. */
  ariaLabel?: string | undefined;
}

export function Combobox<T>({
  value,
  onChange,
  items,
  keyFor,
  renderItem,
  renderSelected,
  placeholder = "Выберите…",
  query,
  onQueryChange,
  loading = false,
  emptyMessage,
  errorMessage,
  clearable = true,
  disabled = false,
  id,
  ariaLabel,
}: ComboboxProps<T>) {
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listboxId = useId();
  const generatedId = useId();
  const triggerId = id ?? generatedId;

  // Whenever the items change, clamp the active index so ↑↓ never points
  // at a stale row.
  useEffect(() => {
    setActiveIndex((i) => Math.min(i, Math.max(0, items.length - 1)));
  }, [items]);

  // Focus the search input the moment the popover opens — keyboard users
  // shouldn't need a second Tab to start typing.
  useEffect(() => {
    if (open) {
      // microtask defer — the input only mounts after this render commits.
      queueMicrotask(() => inputRef.current?.focus());
    }
  }, [open]);

  // Close on outside click. We bind to ``mousedown`` rather than
  // ``click`` so a click inside the input doesn't reopen-then-close.
  useEffect(() => {
    if (!open) return undefined;
    function onDocMouseDown(e: MouseEvent) {
      const target = e.target as Node | null;
      if (!target) return;
      const inside =
        triggerRef.current?.contains(target) ||
        document.getElementById(listboxId)?.contains(target);
      if (!inside) setOpen(false);
    }
    document.addEventListener("mousedown", onDocMouseDown);
    return () => {
      document.removeEventListener("mousedown", onDocMouseDown);
    };
  }, [open, listboxId]);

  const close = useCallback(() => {
    setOpen(false);
    triggerRef.current?.focus();
  }, []);

  const choose = useCallback(
    (item: T) => {
      onChange(item);
      setOpen(false);
      // Defer focus return so React commits before we move focus —
      // otherwise the trigger steals it back inside a closing portal and
      // the screenreader announces "button" twice.
      queueMicrotask(() => triggerRef.current?.focus());
    },
    [onChange],
  );

  const handleKey = useCallback(
    (e: KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Escape") {
        e.preventDefault();
        close();
        return;
      }
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setActiveIndex((i) => Math.min(i + 1, items.length - 1));
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setActiveIndex((i) => Math.max(i - 1, 0));
        return;
      }
      if (e.key === "Enter") {
        e.preventDefault();
        const item = items[activeIndex];
        if (item) choose(item);
        return;
      }
      if (e.key === "Home") {
        e.preventDefault();
        setActiveIndex(0);
        return;
      }
      if (e.key === "End") {
        e.preventDefault();
        setActiveIndex(Math.max(0, items.length - 1));
      }
    },
    [items, activeIndex, choose, close],
  );

  const selectedLabel = useMemo(() => {
    if (!value) return null;
    return renderSelected(value);
  }, [value, renderSelected]);

  const activeOptionId = items[activeIndex]
    ? `${listboxId}-opt-${keyFor(items[activeIndex] as T)}`
    : undefined;

  return (
    <div className="relative">
      <button
        ref={triggerRef}
        id={triggerId}
        type="button"
        role="combobox"
        aria-expanded={open}
        aria-controls={listboxId}
        aria-haspopup="listbox"
        aria-label={ariaLabel}
        aria-disabled={disabled}
        disabled={disabled}
        onClick={() => {
          if (!disabled) setOpen((o) => !o);
        }}
        className={[
          "flex h-10 w-full items-center justify-between gap-2 rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 text-left text-sm",
          "transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--bg-base)]",
          disabled ? "opacity-50" : "hover:bg-[var(--bg-muted)]",
        ].join(" ")}
      >
        <span className="flex min-w-0 flex-1 items-center gap-2 truncate">
          {selectedLabel ?? <span className="text-[var(--text-tertiary)]">{placeholder}</span>}
        </span>
        <div className="flex items-center gap-1">
          {value && clearable && !disabled && (
            <span
              role="button"
              tabIndex={-1}
              onClick={(e) => {
                e.stopPropagation();
                onChange(null);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  e.stopPropagation();
                  onChange(null);
                }
              }}
              aria-label="Очистить"
              className="rounded p-0.5 text-[var(--text-tertiary)] hover:bg-[var(--bg-muted)] hover:text-[var(--text-primary)]"
            >
              <X className="size-3.5" aria-hidden />
            </span>
          )}
          <ChevronsUpDown className="size-4 text-[var(--text-tertiary)]" aria-hidden />
        </div>
      </button>

      {open && !disabled && (
        <div
          id={listboxId}
          role="listbox"
          aria-labelledby={triggerId}
          className="absolute left-0 right-0 z-40 mt-1 max-h-80 overflow-hidden rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] shadow-[var(--shadow-md)]"
        >
          <div className="flex items-center gap-2 border-b border-[var(--border-subtle)] px-3">
            <Search className="size-4 shrink-0 text-[var(--text-tertiary)]" aria-hidden />
            <input
              ref={inputRef}
              type="text"
              value={query}
              onChange={(e) => {
                onQueryChange(e.target.value);
              }}
              onKeyDown={handleKey}
              placeholder="Поиск…"
              className="h-9 flex-1 bg-transparent text-sm outline-none placeholder:text-[var(--text-tertiary)]"
              aria-activedescendant={activeOptionId}
              aria-controls={listboxId}
              autoComplete="off"
              spellCheck={false}
            />
          </div>
          <div className="max-h-60 overflow-y-auto py-1">
            {loading && (
              <div className="px-3 py-2 text-xs text-[var(--text-tertiary)]">Загрузка…</div>
            )}
            {!loading && errorMessage && (
              <div className="px-3 py-2 text-xs text-[var(--danger)]">{errorMessage}</div>
            )}
            {!loading && !errorMessage && items.length === 0 && (
              <div className="px-3 py-2 text-xs text-[var(--text-tertiary)]">
                {emptyMessage ?? "Ничего не найдено"}
              </div>
            )}
            {!loading &&
              !errorMessage &&
              items.map((item, idx) => {
                const key = keyFor(item);
                const isActive = idx === activeIndex;
                const isSelected = value !== null && keyFor(value) === key;
                return (
                  <button
                    type="button"
                    key={key}
                    id={`${listboxId}-opt-${key}`}
                    role="option"
                    aria-selected={isSelected}
                    onMouseEnter={() => {
                      setActiveIndex(idx);
                    }}
                    onClick={() => {
                      choose(item);
                    }}
                    className={[
                      "flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm",
                      isActive ? "bg-[var(--bg-accent-soft)]" : "",
                    ].join(" ")}
                  >
                    <span className="min-w-0 flex-1">{renderItem(item, isActive)}</span>
                    {isSelected && (
                      <Check className="size-4 shrink-0 text-[var(--accent)]" aria-hidden />
                    )}
                  </button>
                );
              })}
          </div>
        </div>
      )}
    </div>
  );
}
