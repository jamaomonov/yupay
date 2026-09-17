"use client";

import { Package } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState } from "react";

import type { OrderRow, OrdersPage, Summary } from "@/lib/types";

import { useSearch } from "@/components/CabinetContext";
import { EmptyState } from "@/components/EmptyState";
import { PageHeading } from "@/components/PageHeading";
import { TodayStats } from "@/components/TodayStats";
import { api, downloadFile } from "@/lib/api";
import { formatMoment } from "@/lib/datetime";
import { ORDER_FILTERS, orderStatusLabel, orderStatusTone, orderTitle } from "@/lib/labels";
import { pathFor } from "@/lib/locale-href";
import { formatUsd, toCents } from "@/lib/money";

/** The two terminal outcomes, as a percentage of themselves.
 *
 * Not `delivered / orders`: most of a morning's orders are still in flight,
 * so that reads as a collapsing success rate all morning and recovers by
 * evening. `—` until something has actually finished. */

/** `null` is the «all» chip — a status of "no filter", not a status. */
const CHIPS: (string | null)[] = [null, ...ORDER_FILTERS];

export default function OrdersList() {
  const t = useTranslations("merchant.orders");
  const tCommon = useTranslations("merchant.common");
  const { locale } = useParams<{ locale: string }>();

  const [status, setStatus] = useState<string | null>(null);
  const query = useSearch(t("search"));
  const [search, setSearch] = useState("");
  const [today, setToday] = useState<Summary | null>(null);
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

  useEffect(() => {
    // Midnight on the *viewer's* clock, sent as UTC. The server does not
    // decide what "today" is — a day derived from the stored timezone would
    // disagree with the dates in the table below, which are browser-local.
    const midnight = new Date();
    midnight.setHours(0, 0, 0, 0);
    void api<Summary>(`/summary?since=${encodeURIComponent(midnight.toISOString())}`)
      .then(setToday)
      .catch(() => undefined);
  }, []);

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
      <div className="flex flex-wrap items-center justify-between gap-3">
        <PageHeading icon={Package} title={t("title")} />
        <button
          type="button"
          onClick={() => {
            void downloadFile("/orders.csv").catch(() => undefined);
          }}
          className="border-border bg-card rounded-btn text-tx-mute border px-3 py-1.5 text-xs font-semibold"
        >
          {tCommon("exportCsv")}
        </button>
      </div>

      <TodayStats today={today} />

      <div className="mt-5 flex flex-wrap gap-2">
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

      {rows !== null && rows.length === 0 && <EmptyState icon={Package} title={t("empty")} />}

      {rows !== null && rows.length > 0 && (
        <div className="border-border bg-card mt-6 overflow-x-auto rounded-xl border">
          <table className="w-full min-w-[52rem] text-sm">
            <thead className="text-tx-dim border-border border-b text-left text-xs">
              <tr>
                <th className="px-4 py-3 font-medium">{t("colOrder")}</th>
                <th className="px-4 py-3 font-medium">{t("colProduct")}</th>
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
                        href={pathFor(
                          locale,
                          `/cabinet/orders/${encodeURIComponent(row.merchant_order_id)}`,
                        )}
                        className="font-semibold underline-offset-4 hover:underline"
                      >
                        {orderTitle(row, t("title"))}
                      </Link>
                      {!row.merchant_order_id.startsWith("manual-") && (
                        <p className="text-tx-dim mt-0.5 text-xs">{row.merchant_order_id}</p>
                      )}
                    </td>
                    <td className="px-4 py-3">{row.sku_code}</td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ${orderStatusTone(
                          row.status,
                        )}`}
                      >
                        {orderStatusLabel(row.status, t)}
                      </span>
                    </td>
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
