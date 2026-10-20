"use client";

import { Package } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState } from "react";

import type { OrderRow, OrdersPage, Summary } from "@/lib/types";

import { BrandMark } from "@/components/BrandMark";
import { useSearch } from "@/components/CabinetContext";
import { EmptyState } from "@/components/EmptyState";
import { ListSkeleton } from "@/components/ListSkeleton";
import { LoadError } from "@/components/LoadError";
import { PageHeading } from "@/components/PageHeading";
import { TodayStats } from "@/components/TodayStats";
import { api, downloadFile } from "@/lib/api";
import { formatMoment } from "@/lib/datetime";
import { ORDER_FILTERS, orderStatusLabel, orderStatusTone, orderTitle } from "@/lib/labels";
import { pathFor } from "@/lib/locale-href";
import { dollars, toCents } from "@/lib/money";

/** The two terminal outcomes, as a percentage of themselves.
 *
 * Not `delivered / orders`: most of a morning's orders are still in flight,
 * so that reads as a collapsing success rate all morning and recovers by
 * evening. `—` until something has actually finished. */

/** `null` is the «all» chip — a status of "no filter", not a status. */
const CHIPS: (string | null)[] = [null, ...ORDER_FILTERS];

export default function OrdersList() {
  const t = useTranslations("merchant.orders");
  const router = useRouter();
  const tCommon = useTranslations("merchant.common");
  const { locale } = useParams<{ locale: string }>();

  const [status, setStatus] = useState<string | null>(null);
  const query = useSearch(t("search"));
  const [search, setSearch] = useState("");
  const [today, setToday] = useState<Summary | null>(null);
  const [rows, setRows] = useState<OrderRow[] | null>(null);
  const [failed, setFailed] = useState(false);
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
        setFailed(false);
        setRows((previous) => (after === null ? page.items : [...(previous ?? []), ...page.items]));
        setCursor(page.next_cursor);
      } catch {
        // An error, not an empty list: a timeout used to read as «Заказов нет».
        // A lapsed session never reaches here — the client redirects to sign-in.
        if (mine === generation.current && after === null) setFailed(true);
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

      <div className="mt-5">
        <TodayStats today={today} />
      </div>

      <div className="-mx-4 mt-5 flex gap-2 overflow-x-auto px-4 sm:mx-0 sm:flex-wrap sm:px-0">
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
              className={`rounded-btn shrink-0 border px-3 py-1.5 text-xs ${
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

      {rows === null && !failed && <ListSkeleton className="mt-6" />}
      {rows === null && failed && (
        <LoadError
          onRetry={() => {
            setFailed(false);
            void fetchPage(null);
          }}
        />
      )}

      {rows !== null && rows.length === 0 && (
        <EmptyState icon={Package} title={t("empty")} hint={t("emptyHint")} />
      )}

      {rows !== null && rows.length > 0 && (
        // A phone gets one card per order instead of the six-column table,
        // which scrolled sideways inside its box and cut the status off.
        <ul className="border-border bg-card divide-border mt-6 divide-y rounded-xl border md:hidden">
          {rows.map((row) => {
            const refunded = toCents(row.refunded_usd);
            return (
              <li key={row.order_id}>
                <Link
                  href={pathFor(
                    locale,
                    `/cabinet/orders/${encodeURIComponent(row.merchant_order_id)}`,
                  )}
                  className="block px-4 py-3.5"
                >
                  <div className="flex items-start justify-between gap-3">
                    <BrandMark name={row.brand_name} logoUrl={row.brand_logo_url} size="sm" />
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-semibold leading-snug">
                        {orderTitle(row, t("colOrder"))}
                      </p>
                      {row.recipient && (
                        <p className="text-tx-mute mt-0.5 break-all font-mono text-xs">
                          {row.recipient}
                        </p>
                      )}
                    </div>
                    <span className="shrink-0 font-mono text-sm tabular-nums">
                      {dollars(toCents(row.price_usd))}
                    </span>
                  </div>
                  <div className="mt-1.5 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-xs">
                    <span
                      className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${orderStatusTone(
                        row.status,
                      )}`}
                    >
                      {orderStatusLabel(row.status, t)}
                    </span>
                    {refunded > 0n && (
                      <span className="text-tx-mute font-mono">
                        {t("colRefunded")} {dollars(refunded)}
                      </span>
                    )}
                    <span className="text-tx-dim">{formatMoment(row.created_at, locale)}</span>
                  </div>
                  {!row.merchant_order_id.startsWith("manual-") && (
                    <p className="text-tx-dim mt-1 truncate font-mono text-[11px]">
                      {row.merchant_order_id}
                    </p>
                  )}
                </Link>
              </li>
            );
          })}
        </ul>
      )}

      {rows !== null && rows.length > 0 && (
        // Four columns: what, where it stands, what it cost, when. The SKU code and an
        // empty «Возвращено» column took two of six for something the title already says
        // or that is almost always «—»; a refund now sits under the amount it returns.
        <div className="border-border bg-card mt-6 hidden overflow-hidden rounded-xl border md:block">
          <table className="w-full text-sm">
            <thead className="text-tx-dim border-border border-b text-left text-xs">
              <tr>
                <th className="px-4 py-3 font-medium">{t("colOrder")}</th>
                <th className="w-36 px-4 py-3 font-medium">{t("colStatus")}</th>
                <th className="w-32 px-4 py-3 text-right font-medium">{t("colPrice")}</th>
                <th className="w-44 px-4 py-3 text-right font-medium">{t("colCreated")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const refunded = toCents(row.refunded_usd);
                const href = pathFor(
                  locale,
                  `/cabinet/orders/${encodeURIComponent(row.merchant_order_id)}`,
                );
                const meta = [
                  row.recipient,
                  row.merchant_order_id.startsWith("manual-") ? null : row.merchant_order_id,
                ].filter(Boolean);
                return (
                  <tr
                    key={row.order_id}
                    onClick={() => {
                      router.push(href);
                    }}
                    className="border-border hover:bg-card-2/60 cursor-pointer border-b transition-colors last:border-0"
                  >
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3">
                        <BrandMark name={row.brand_name} logoUrl={row.brand_logo_url} size="sm" />
                        <div className="min-w-0">
                          <Link
                            href={href}
                            onClick={(event) => {
                              event.stopPropagation();
                            }}
                            className="font-semibold"
                          >
                            {orderTitle(row, t("colOrder"))}
                          </Link>
                          {meta.length > 0 && (
                            <p className="text-tx-dim mt-0.5 truncate font-mono text-xs">
                              {meta.join(" · ")}
                            </p>
                          )}
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ${orderStatusTone(
                          row.status,
                        )}`}
                      >
                        {orderStatusLabel(row.status, t)}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right font-mono tabular-nums">
                      {dollars(toCents(row.price_usd))}
                      {refunded > 0n && (
                        <p className="text-tx-mute mt-0.5 text-xs">
                          {t("colRefunded")} {dollars(refunded)}
                        </p>
                      )}
                    </td>
                    <td className="text-tx-mute whitespace-nowrap px-4 py-3 text-right">
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
