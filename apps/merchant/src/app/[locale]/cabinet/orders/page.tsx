"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState } from "react";

import type { OrderRow, OrdersPage } from "@/lib/types";

import { api } from "@/lib/api";
import { formatMoment } from "@/lib/datetime";
import { ORDER_FILTERS, orderStatusLabel } from "@/lib/labels";
import { formatUsd, toCents } from "@/lib/money";

/** `null` is the «all» chip — a status of "no filter", not a status. */
const CHIPS: (string | null)[] = [null, ...ORDER_FILTERS];

export default function OrdersList() {
  const t = useTranslations("merchant.orders");
  const { locale } = useParams<{ locale: string }>();

  const [status, setStatus] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [rows, setRows] = useState<OrderRow[] | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // Typing in the search box restarts the query on every keystroke, and the
  // answers can land out of order. Only the newest generation may write.
  const generation = useRef(0);

  useEffect(() => {
    const id = setTimeout(() => {
      setSearch(query.trim());
    }, 350);
    return () => {
      clearTimeout(id);
    };
  }, [query]);

  const fetchPage = useCallback(
    async (after: string | null) => {
      // A fresh query opens a generation; a «show more» belongs to the
      // current one, so a filter changed mid-page discards it.
      const mine = after === null ? (generation.current += 1) : generation.current;
      setBusy(true);
      const params = new URLSearchParams();
      if (status !== null) params.set("status_filter", status);
      if (search !== "") params.set("search", search);
      if (after !== null) params.set("cursor", after);
      try {
        const page = await api<OrdersPage>(`/orders?${params.toString()}`);
        if (mine !== generation.current) return;
        setRows((previous) => (after === null ? page.items : [...(previous ?? []), ...page.items]));
        setCursor(page.next_cursor);
      } catch {
        // An empty list rather than an error banner: the only failures
        // reachable here are a lapsed session, which the shell resolves on the
        // next navigation, and a filter the API refused, which cannot be
        // produced by these chips.
        if (mine === generation.current) {
          setRows([]);
          setCursor(null);
        }
      } finally {
        if (mine === generation.current) setBusy(false);
      }
    },
    [search, status],
  );

  useEffect(() => {
    void fetchPage(null);
  }, [fetchPage]);

  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight">{t("title")}</h1>

      <input
        type="search"
        value={query}
        onChange={(event) => {
          setQuery(event.target.value);
        }}
        placeholder={t("search")}
        aria-label={t("search")}
        className="border-border bg-card rounded-btn mt-5 w-full border px-3.5 py-2.5 text-sm outline-none sm:max-w-sm"
      />

      <div className="mt-4 flex flex-wrap gap-2">
        {CHIPS.map((chip) => {
          const active = chip === status;
          return (
            <button
              key={chip ?? "all"}
              type="button"
              aria-pressed={active}
              onClick={() => {
                setStatus(chip);
              }}
              className={`rounded-btn border px-3 py-1.5 text-xs ${
                active
                  ? "border-primary bg-primary text-primary-foreground font-semibold"
                  : "border-border text-tx-mute"
              }`}
            >
              {chip === null ? t("filterAll") : orderStatusLabel(chip, t)}
            </button>
          );
        })}
      </div>

      {rows !== null && rows.length === 0 && (
        <p className="text-tx-dim mt-8 text-sm">{t("empty")}</p>
      )}

      {rows !== null && rows.length > 0 && (
        <div className="border-border bg-card mt-6 overflow-x-auto rounded-xl border">
          <table className="w-full min-w-[44rem] text-sm">
            <thead className="text-tx-dim border-border border-b text-left text-xs">
              <tr>
                <th className="px-4 py-3 font-medium">{t("colOrder")}</th>
                <th className="px-4 py-3 font-medium">{t("colStatus")}</th>
                <th className="px-4 py-3 text-right font-medium">{t("colPrice")}</th>
                <th className="px-4 py-3 text-right font-medium">{t("colRefunded")}</th>
                <th className="px-4 py-3 font-medium">{t("colCreated")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const refunded = toCents(row.refunded_usd);
                return (
                  <tr key={row.order_id} className="border-border border-b last:border-0">
                    <td className="px-4 py-3">
                      <Link
                        href={`/${locale}/cabinet/orders/${encodeURIComponent(row.merchant_order_id)}`}
                        className="font-medium underline-offset-4 hover:underline"
                      >
                        {row.merchant_order_id}
                      </Link>
                      <p className="text-tx-dim mt-0.5 font-mono text-xs">{row.sku_code}</p>
                    </td>
                    <td className="text-tx-mute px-4 py-3">{orderStatusLabel(row.status, t)}</td>
                    <td className="px-4 py-3 text-right font-mono">
                      ${formatUsd(toCents(row.price_usd))}
                    </td>
                    <td className="px-4 py-3 text-right font-mono">
                      {refunded === 0n ? (
                        <span className="text-tx-dim">—</span>
                      ) : (
                        `$${formatUsd(refunded)}`
                      )}
                    </td>
                    <td className="text-tx-mute whitespace-nowrap px-4 py-3">
                      {formatMoment(row.created_at, locale)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {cursor !== null && (
        <button
          type="button"
          disabled={busy}
          onClick={() => {
            void fetchPage(cursor);
          }}
          className="border-border rounded-btn mt-5 border px-4 py-2 text-sm font-semibold disabled:opacity-50"
        >
          {t("loadMore")}
        </button>
      )}
    </div>
  );
}
