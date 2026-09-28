"use client";

import { Search } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";

import type { SkinItem, SkinQuery } from "@/lib/skins";

import { apiFetch } from "@/lib/client";
import { pathFor } from "@/lib/seo";
import { skinQueryString } from "@/lib/skins";

const DEBOUNCE_MS = 250;

/**
 * Search as you type: up to ten suggestions from `/skins/suggest` (Postgres
 * trigram, no supplier call), Enter searches the grid via `?q=`. Each keystroke
 * aborts the previous request so a slow answer never overwrites a newer one.
 */
export function SkinSearch({
  initial,
  locale,
  query,
}: {
  initial: string;
  locale: string;
  query: SkinQuery;
}) {
  const t = useTranslations("web.skins");
  const router = useRouter();
  const [text, setText] = useState(initial);
  const [items, setItems] = useState<SkinItem[]>([]);
  const [open, setOpen] = useState(false);
  const abort = useRef<AbortController | null>(null);

  useEffect(() => {
    const q = text.trim();
    abort.current?.abort();
    if (q.length < 2) {
      setItems([]);
      return undefined;
    }
    const controller = new AbortController();
    abort.current = controller;
    const timer = setTimeout(() => {
      apiFetch<{ items: SkinItem[] }>(`/skins/suggest?q=${encodeURIComponent(q)}`, {
        anonymous: true,
        signal: controller.signal,
      })
        .then((r) => {
          setItems(r.items);
        })
        .catch(() => {
          setItems([]);
        });
    }, DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [text]);

  return (
    <form
      role="search"
      className="relative flex-1"
      onSubmit={(e) => {
        e.preventDefault();
        setOpen(false);
        const q = text.trim();
        router.push(pathFor(locale, "/skins") + skinQueryString(query, { q: q || undefined }));
      }}
    >
      <Search className="text-tx-dim pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2" />
      <input
        type="search"
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          setOpen(true);
        }}
        onBlur={() => {
          setTimeout(() => {
            setOpen(false);
          }, 150);
        }}
        placeholder={t("searchPlaceholder")}
        aria-label={t("searchPlaceholder")}
        className="border-border bg-card w-full rounded-xl border py-2.5 pl-9 pr-3 text-[14px]"
      />
      {open && items.length > 0 && (
        <ul className="border-border bg-card absolute inset-x-0 top-full z-20 mt-1 max-h-96 overflow-y-auto rounded-xl border shadow-xl">
          {items.map((i) => (
            <li key={i.slug}>
              <Link
                href={pathFor(locale, `/skins/${i.slug}`)}
                className="hover:bg-muted flex items-center justify-between gap-3 px-3 py-2 text-[13px]"
              >
                <span className="truncate">{i.name}</span>
                {i.phase && <span className="text-tx-dim shrink-0">{i.phase}</span>}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </form>
  );
}
