/**
 * Global search palette — ⌘K / Ctrl+K from anywhere in the admin SPA.
 *
 * Behaviour:
 *  - Opens via the `open` prop driven by Layout.
 *  - 200 ms debounce before hitting `/api/v1/admin/search`.
 *  - Results are grouped by source (Users / Orders / Payments / SKUs) but the
 *    highlight cursor walks them as a single flat list so ↑↓ feels natural.
 *  - Enter navigates to the hit's `path` and closes the palette.
 *  - Esc or backdrop click closes.
 *
 * Server contract: see ADR-0017 and
 * `apps/api/src/yupay/modules/admin/schemas.py`.
 */

import { useQuery } from "@tanstack/react-query";
import { Search, Loader2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import type { HitType, SearchHit, SearchOut } from "./types";

import { type ApiError, apiGet } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { useDialog } from "@/lib/useDialog";

interface Props {
  open: boolean;
  onClose: () => void;
}

const GROUP_ORDER: HitType[] = ["user", "order", "payment", "sku"];
const GROUP_LABEL: Record<HitType, string> = {
  user: "Пользователи",
  order: "Заказы",
  payment: "Платежи",
  sku: "SKU",
};

const MIN_QUERY = 2;
const DEBOUNCE_MS = 200;
const PER_GROUP_LIMIT = 10;

function flatten(data: SearchOut | undefined): SearchHit[] {
  if (!data) return [];
  return [...data.users, ...data.orders, ...data.payments, ...data.skus];
}

export function SearchPalette({ open, onClose }: Props) {
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [highlight, setHighlight] = useState(0);
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);
  const dialogRef = useRef<HTMLDivElement | null>(null);

  // useDialog handles focus restoration + Esc + Tab trap. Local state reset on
  // open runs separately.
  useDialog({
    open,
    onClose,
    containerRef: dialogRef,
    initialFocus: () => inputRef.current?.focus(),
  });

  useEffect(() => {
    if (!open) return;
    setQ("");
    setDebounced("");
    setHighlight(0);
  }, [open]);

  // Debounce the typed query before issuing the network request.
  useEffect(() => {
    const t = window.setTimeout(() => {
      setDebounced(q.trim());
    }, DEBOUNCE_MS);
    return () => {
      window.clearTimeout(t);
    };
  }, [q]);

  const enabled = open && debounced.length >= MIN_QUERY;
  const query = useQuery<SearchOut, ApiError>({
    queryKey: qk.search(debounced),
    queryFn: () =>
      apiGet<SearchOut>(
        `/api/v1/admin/search?q=${encodeURIComponent(debounced)}&limit=${PER_GROUP_LIMIT.toString()}`,
      ),
    enabled,
    staleTime: 30_000,
  });

  const hits = useMemo(() => flatten(query.data), [query.data]);

  // Keep the highlight pointer valid as results change.
  useEffect(() => {
    if (highlight >= hits.length) setHighlight(0);
  }, [hits.length, highlight]);

  // Keep the highlighted row scrolled into view.
  useEffect(() => {
    if (!listRef.current) return;
    const el = listRef.current.querySelector<HTMLElement>(
      `[data-hit-index="${highlight.toString()}"]`,
    );
    el?.scrollIntoView({ block: "nearest" });
  }, [highlight]);

  if (!open) return null;

  const state: "idle" | "loading" | "error" | "empty" | "ready" = !enabled
    ? "idle"
    : query.isPending
      ? "loading"
      : query.isError
        ? "error"
        : hits.length === 0
          ? "empty"
          : "ready";

  const onKeyDown = (e: React.KeyboardEvent) => {
    // Esc is handled by useDialog (window-level); ArrowDown/Up/Enter stay here.
    if (e.key === "ArrowDown" || (e.key === "n" && e.ctrlKey)) {
      e.preventDefault();
      if (hits.length) setHighlight((h) => (h + 1) % hits.length);
      return;
    }
    if (e.key === "ArrowUp" || (e.key === "p" && e.ctrlKey)) {
      e.preventDefault();
      if (hits.length) setHighlight((h) => (h - 1 + hits.length) % hits.length);
      return;
    }
    if (e.key === "Enter") {
      if (state !== "ready") return;
      e.preventDefault();
      const hit = hits[highlight];
      if (hit) {
        void navigate(hit.path);
        onClose();
      }
    }
  };

  // Assign a flat index per hit so the cursor can walk across groups.
  let cursor = 0;
  const groups = GROUP_ORDER.map((type) => {
    const bucket = query.data?.[bucketKey(type)] ?? [];
    const indexed = bucket.map((hit) => {
      const idx = cursor;
      cursor += 1;
      return { hit, idx };
    });
    return { type, hits: indexed };
  });

  return (
    <div
      ref={dialogRef}
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 px-4 pt-[8vh] backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label="Глобальный поиск"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="relative w-full max-w-xl rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] text-[var(--text-primary)] shadow-2xl ring-1 ring-black/5">
        <div className="flex items-center gap-2 border-b border-[var(--border-default)] px-4 py-3">
          <Search className="size-4 text-[var(--text-secondary)]" aria-hidden />
          <input
            ref={inputRef}
            type="text"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
            }}
            onKeyDown={onKeyDown}
            placeholder="Заказ, email, @username, payment id, SKU…"
            className="flex-1 bg-transparent text-sm outline-none placeholder:text-[var(--text-secondary)]"
            aria-label="Поисковый запрос"
            autoComplete="off"
            spellCheck={false}
          />
          {query.isFetching && enabled && (
            <Loader2 className="size-4 animate-spin text-[var(--text-secondary)]" aria-hidden />
          )}
          <kbd className="rounded border border-[var(--border-default)] px-1.5 py-0.5 text-[10px] uppercase text-[var(--text-secondary)]">
            Esc
          </kbd>
        </div>

        <div ref={listRef} className="max-h-[60vh] overflow-y-auto py-1">
          {state === "idle" && <Hint>Начните вводить — минимум {MIN_QUERY} символа.</Hint>}
          {state === "loading" && <Hint>Поиск…</Hint>}
          {state === "error" && <Hint danger>Ошибка поиска. Проверьте подключение.</Hint>}
          {state === "empty" && <Hint>Ничего не найдено.</Hint>}
          {state === "ready" &&
            groups.map((group) =>
              group.hits.length === 0 ? null : (
                <div key={group.type}>
                  <p className="px-4 pb-1 pt-3 text-[10px] font-medium uppercase tracking-wide text-[var(--text-secondary)]">
                    {GROUP_LABEL[group.type]}
                  </p>
                  {group.hits.map(({ hit, idx }) => (
                    <HitRow
                      key={`${group.type}-${hit.id}`}
                      hit={hit}
                      index={idx}
                      active={highlight === idx}
                      onHover={() => {
                        setHighlight(idx);
                      }}
                      onClick={() => {
                        void navigate(hit.path);
                        onClose();
                      }}
                    />
                  ))}
                </div>
              ),
            )}
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-[var(--border-default)] px-4 py-2 text-[11px] text-[var(--text-secondary)]">
          <span className="flex items-center gap-2">
            <Hotkey>↑↓</Hotkey> навигация · <Hotkey>↵</Hotkey> открыть
          </span>
          <span>
            <Hotkey>⌘K</Hotkey> / <Hotkey>Ctrl+K</Hotkey>
          </span>
        </div>
      </div>
    </div>
  );
}

function bucketKey(type: HitType): keyof SearchOut {
  switch (type) {
    case "user":
      return "users";
    case "order":
      return "orders";
    case "payment":
      return "payments";
    case "sku":
      return "skus";
  }
}

function HitRow({
  hit,
  index,
  active,
  onHover,
  onClick,
}: {
  hit: SearchHit;
  index: number;
  active: boolean;
  onHover: () => void;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      data-hit-index={index}
      onMouseMove={onHover}
      onClick={onClick}
      className={[
        "flex w-full items-center gap-3 px-4 py-2 text-left text-sm transition-colors",
        active
          ? "bg-[var(--bg-muted)] text-[var(--text-primary)]"
          : "hover:bg-[var(--bg-muted)]/60 text-[var(--text-primary)]",
      ].join(" ")}
    >
      <span className="min-w-0 flex-1">
        <span className="block truncate font-medium">{hit.label}</span>
        {hit.sublabel && (
          <span className="block truncate text-xs text-[var(--text-secondary)]">
            {hit.sublabel}
          </span>
        )}
      </span>
      <span className="shrink-0 font-mono text-[10px] text-[var(--text-secondary)]">
        {hit.id.slice(0, 8)}
      </span>
    </button>
  );
}

function Hint({ children, danger }: { children: React.ReactNode; danger?: boolean }) {
  return (
    <p
      className={[
        "px-4 py-6 text-center text-sm",
        danger ? "text-[var(--danger)]" : "text-[var(--text-secondary)]",
      ].join(" ")}
    >
      {children}
    </p>
  );
}

function Hotkey({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="rounded border border-[var(--border-default)] px-1 py-0.5 text-[10px] uppercase">
      {children}
    </kbd>
  );
}
