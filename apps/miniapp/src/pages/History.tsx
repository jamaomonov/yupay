import { useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import {
  AlertTriangle,
  ArrowDownLeft,
  ArrowUpRight,
  CheckCircle2,
  Clock3,
  ExternalLink,
  Receipt,
  RotateCcw,
  Star,
  Undo2,
  Wallet as WalletIcon,
} from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useLocation } from "wouter";

import type { Locale } from "@yupay/i18n";

import { ReviewsSheet } from "@/components/ReviewsSheet";
import { BOT_LINK } from "@/lib/bot-link";
import { SafeImage } from "@/components/ui/safe-image";
import { useMe } from "@/lib/auth";
import { useT, useLocale, type MessageKey } from "@/lib/i18n";
import { useMyOrders, orderToHistoryRow, type HistoryRow } from "@/lib/orders";
import { getMyReviews } from "@/lib/reviews";
import { hrefForGameSlug } from "@/lib/routes";
import { useDocumentTitle } from "@/lib/use-document-title";
import {
  summarizeForUser,
  txKindLabelKey,
  type UserAccountKind,
  type UserTransactionView,
  useWallet,
  useWalletTransactions,
} from "@/lib/wallet";

type Tab = "orders" | "finance";

const STATUS_KEY: Record<HistoryRow["status"], MessageKey> = {
  success: "history.status.success",
  processing: "history.status.processing",
  failed: "history.status.failed",
  refunded: "history.status.refunded",
};

function monthYearKey(iso: string, locale: Locale): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return new Intl.DateTimeFormat(locale, { month: "short", year: "numeric" }).format(d);
}

function shortTime(iso: string, locale: Locale): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" });
}

export default function History() {
  const { t } = useT();
  useDocumentTitle(t("history.title"));
  const me = useMe();
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>("orders");

  // Switching the segmented control re-fetches the destination tab's
  // data so the user sees fresh state every time they flip — replaces
  // the dedicated refresh button that used to sit on each panel.
  const onTabChange = (next: Tab) => {
    if (next === tab) return;
    setTab(next);
    if (next === "orders") {
      void qc.invalidateQueries({ queryKey: ["my-orders"] });
    } else {
      void qc.invalidateQueries({ queryKey: ["wallet", "transactions"] });
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.22 }}
      className="space-y-5 p-4"
    >
      <header className="space-y-0.5">
        <h1 className="text-2xl font-bold tracking-tight text-white">{t("history.title")}</h1>
        <p className="text-muted-foreground text-sm">{t("history.subtitle")}</p>
      </header>

      {!me.data && !me.isLoading && (
        <div className="flex items-start gap-3 rounded-2xl border border-yellow-400/30 bg-yellow-400/5 p-4">
          <AlertTriangle size={18} className="mt-0.5 flex-shrink-0 text-yellow-400" />
          <div className="text-sm">
            <p className="font-semibold text-yellow-200">{t("common.openInTelegram")}</p>
            <p className="mt-1 text-xs text-yellow-100/70">{t("history.authHint")}</p>
            {BOT_LINK && (
              <a
                href={BOT_LINK}
                className="mt-2.5 inline-flex items-center gap-1.5 text-[12px] font-semibold transition-opacity active:opacity-70"
                style={{ color: "hsl(var(--primary))" }}
              >
                {t("common.openBot")}
                <ExternalLink size={11} />
              </a>
            )}
          </div>
        </div>
      )}

      {me.data && (
        <SegmentedTabs
          value={tab}
          onChange={onTabChange}
          ariaLabel={t("history.tabsLabel")}
          options={[
            { id: "orders", label: t("history.tabOrders") },
            { id: "finance", label: t("history.tabFinance") },
          ]}
        />
      )}

      {me.data && tab === "orders" && <OrdersTab />}
      {me.data && tab === "finance" && <FinanceTab />}
    </motion.div>
  );
}

// ---------- shared tab control ----------

function SegmentedTabs<T extends string>({
  value,
  onChange,
  options,
  ariaLabel,
}: {
  value: T;
  onChange: (next: T) => void;
  options: { id: T; label: string }[];
  ariaLabel: string;
}) {
  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      className="grid grid-cols-2 gap-1 rounded-2xl p-1"
      style={{
        background: "hsl(var(--surface-1))",
        border: "1px solid hsl(var(--border))",
      }}
    >
      {options.map((opt) => {
        const active = opt.id === value;
        return (
          <button
            key={opt.id}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => {
              onChange(opt.id);
            }}
            className="rounded-xl py-2 text-sm font-semibold transition-colors"
            style={
              active
                ? { background: "hsl(var(--primary))", color: "#000" }
                : { color: "hsl(var(--muted-foreground))" }
            }
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

// ---------- orders tab ----------

const STATUS_FILTERS = ["all", "success", "processing", "failed", "refunded"] as const;
type StatusFilter = (typeof STATUS_FILTERS)[number];

function OrdersTab() {
  // Tab content is unmounted/remounted when the segmented switcher
  // flips, and ``refetchOnMount: "always"`` on the underlying query
  // makes that remount run a network refresh. So just by toggling
  // Заказы → Финансы → Заказы the user gets a fresh feed without a
  // dedicated refresh button.
  const { t, tn } = useT();
  const locale = useLocale();
  const [, navigate] = useLocation();
  const ordersQuery = useMyOrders();
  const orders = ordersQuery.data ?? [];
  const allRows: HistoryRow[] = orders.map(orderToHistoryRow);
  // Hide the "Оценить" CTA on orders the user has already reviewed. Shares the
  // ["my-reviews"] query key with OrderSuccess, which ReviewsSheet invalidates
  // on submit, so a fresh review makes the button disappear here too.
  const myReviews = useQuery({ queryKey: ["my-reviews"], queryFn: () => getMyReviews() });
  const reviewedOrderIds = useMemo(
    () => new Set((myReviews.data?.items ?? []).map((r) => r.order_id)),
    [myReviews.data],
  );
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [reviewFor, setReviewFor] = useState<{ slug: string; orderId: string } | null>(null);
  const rows = statusFilter === "all" ? allRows : allRows.filter((r) => r.status === statusFilter);

  const grouped = rows.reduce<Record<string, HistoryRow[]>>((acc, tx) => {
    const key = monthYearKey(tx.raw.created_at, locale);
    (acc[key] ??= []).push(tx);
    return acc;
  }, {});

  return (
    <div className="space-y-5" role="tabpanel">
      {reviewFor && (
        <ReviewsSheet
          brandSlug={reviewFor.slug}
          formOrderId={reviewFor.orderId}
          onClose={() => {
            setReviewFor(null);
          }}
        />
      )}
      {ordersQuery.isLoading && (
        <div className="py-10 text-center text-sm text-white/40">{t("common.loading")}</div>
      )}

      {/* Status filter — only worth the row once there's something to narrow. */}
      {allRows.length > 0 && (
        <div className="no-scrollbar -mt-1 flex gap-2 overflow-x-auto">
          {STATUS_FILTERS.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => {
                setStatusFilter(s);
              }}
              className="flex-shrink-0 whitespace-nowrap rounded-xl px-3 py-1.5 text-[11px] font-semibold transition-all"
              style={{
                background: statusFilter === s ? "hsl(var(--primary))" : "hsl(var(--card))",
                color: statusFilter === s ? "#000" : "rgba(255,255,255,0.55)",
                border:
                  statusFilter === s
                    ? "1px solid hsl(var(--primary))"
                    : "1px solid hsl(var(--border))",
              }}
              data-testid={`history-filter-${s}`}
            >
              {s === "all" ? t("history.filterAll") : t(STATUS_KEY[s])}
            </button>
          ))}
        </div>
      )}

      {/* Filter matched nothing (but there ARE orders) — offer a way back. */}
      {!ordersQuery.isLoading && allRows.length > 0 && rows.length === 0 && (
        <div className="border-border bg-card rounded-2xl border p-8 text-center">
          <p className="text-sm text-white/60">{t("history.filterEmpty")}</p>
          <button
            type="button"
            onClick={() => {
              setStatusFilter("all");
            }}
            className="text-primary mt-2 text-sm font-semibold"
          >
            {t("history.filterReset")}
          </button>
        </div>
      )}

      {ordersQuery.isError && (
        <div className="rounded-2xl border border-rose-500/30 bg-rose-500/5 p-4 text-sm text-rose-200">
          {t("history.ordersError")}
        </div>
      )}

      {!ordersQuery.isLoading && allRows.length === 0 && (
        <div className="border-border bg-card space-y-3 rounded-2xl border p-10 text-center">
          <Receipt size={28} className="mx-auto text-white/30" />
          <p className="text-sm text-white/60">{t("history.ordersEmpty")}</p>
          <Link
            href="/"
            className="inline-block rounded-2xl px-5 py-2.5 text-sm font-semibold"
            style={{ background: "hsl(var(--primary))", color: "#000" }}
          >
            {t("history.chooseGame")}
          </Link>
        </div>
      )}

      <div className="space-y-5">
        {Object.entries(grouped).map(([monthYear, txs]) => (
          <div key={monthYear} className="flex flex-col gap-3">
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground text-xs font-bold uppercase tracking-[0.08em]">
                {monthYear}
              </span>
              <div className="bg-border h-px flex-1" />
            </div>

            {txs.map((tx, index) => (
              <Link key={tx.id} href={`/order/${tx.id}`} className="block">
                <motion.div
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: index * 0.04 }}
                  whileTap={{ scale: 0.985 }}
                  className="bg-card border-border flex cursor-pointer items-center gap-3 rounded-2xl border p-3.5"
                  data-testid={`history-item-${tx.id}`}
                >
                  <div className="flex h-11 w-11 shrink-0 items-center justify-center overflow-hidden rounded-xl">
                    {tx.imageUrl ? (
                      <SafeImage
                        src={tx.imageUrl}
                        className="h-full w-full object-cover"
                        fallback={<Receipt size={18} className="text-muted-foreground" />}
                      />
                    ) : (
                      <Receipt size={18} className="text-muted-foreground" />
                    )}
                  </div>

                  <div className="min-w-0 flex-1">
                    <h3 className="truncate text-sm font-bold text-white">{tx.title}</h3>
                    <p className="text-muted-foreground mt-0.5 truncate text-[11px]">
                      {shortTime(tx.raw.created_at, locale)}
                      {tx.subtitle ? ` · ${tx.subtitle}` : ""}
                      {tx.itemsCount > 1 ? ` · ${tn("orders.positions", tx.itemsCount)}` : ""}
                    </p>
                    {tx.gameSlug && tx.status === "success" && (
                      <button
                        type="button"
                        onClick={(e) => {
                          // The row itself is a Link to the order — keep the
                          // repeat tap from triggering that navigation.
                          e.preventDefault();
                          e.stopPropagation();
                          if (tx.gameSlug) navigate(hrefForGameSlug(tx.gameSlug));
                        }}
                        className="text-primary mt-1.5 inline-flex items-center gap-1 text-[11px] font-semibold"
                        data-testid={`history-repeat-${tx.id}`}
                      >
                        <RotateCcw size={10} aria-hidden="true" />
                        {t("history.repeat")}
                      </button>
                    )}
                    {tx.gameSlug && tx.status === "success" && !reviewedOrderIds.has(tx.id) && (
                      <button
                        type="button"
                        onClick={(e) => {
                          e.preventDefault();
                          e.stopPropagation();
                          if (tx.gameSlug) setReviewFor({ slug: tx.gameSlug, orderId: tx.id });
                        }}
                        className="text-primary ml-3 mt-1.5 inline-flex items-center gap-1 text-[11px] font-semibold"
                        data-testid={`history-rate-${tx.id}`}
                      >
                        <Star size={10} aria-hidden="true" />
                        {t("reviews.rateCta")}
                      </button>
                    )}
                  </div>

                  <div className="shrink-0 space-y-1 text-right">
                    <p className="text-primary text-sm font-bold">
                      {tx.amount.toLocaleString(locale, {
                        maximumFractionDigits: 2,
                      })}{" "}
                      {tx.currency}
                    </p>
                    <div
                      className={`flex items-center justify-end gap-1 ${
                        tx.status === "success"
                          ? "text-green-400"
                          : tx.status === "failed"
                            ? "text-rose-400"
                            : tx.status === "refunded"
                              ? "text-sky-400"
                              : "text-yellow-400"
                      }`}
                    >
                      {tx.status === "success" ? (
                        <CheckCircle2 size={11} />
                      ) : tx.status === "failed" ? (
                        <AlertTriangle size={11} />
                      ) : tx.status === "refunded" ? (
                        <Undo2 size={11} />
                      ) : (
                        <Clock3 size={11} />
                      )}
                      <span className="text-[10px] font-semibold">{t(STATUS_KEY[tx.status])}</span>
                    </div>
                  </div>
                </motion.div>
              </Link>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------- finance tab ----------

/**
 * "Финансы" lists ledger movements on the user's main wallet account:
 * top-ups (once acquirers are live), refunds, and admin adjustments.
 * Cashback / promo are intentionally excluded — those chips are hidden
 * on /wallet too, so surfacing the rows here would just bring back the
 * UI we just removed.
 */
const FINANCE_VISIBLE_KINDS: UserAccountKind[] = ["user_wallet"];

function FinanceTab() {
  const { t } = useT();
  const locale = useLocale();
  const wallet = useWallet();
  const txQuery = useWalletTransactions(50);

  // Filter the user-account map down to the kinds we want to surface so
  // ``summarizeForUser`` returns null for legs on cashback / promo and
  // we can simply drop those rows.
  const { userAccountIds, accountKindById } = useMemo(() => {
    const ids = new Set<string>();
    const kinds = new Map<string, UserAccountKind>();
    for (const b of wallet.data ?? []) {
      if (FINANCE_VISIBLE_KINDS.includes(b.kind)) {
        ids.add(b.raw.account_id);
        kinds.set(b.raw.account_id, b.kind);
      }
    }
    return { userAccountIds: ids, accountKindById: kinds };
  }, [wallet.data]);

  const rows = useMemo<UserTransactionView[]>(() => {
    if (!txQuery.data) return [];
    return txQuery.data
      .map((tx) => summarizeForUser(tx, userAccountIds, accountKindById))
      .filter((v): v is UserTransactionView => v !== null);
  }, [txQuery.data, userAccountIds, accountKindById]);

  const grouped = useMemo(() => {
    return rows.reduce<Record<string, UserTransactionView[]>>((acc, r) => {
      const key = monthYearKey(r.createdAt, locale);
      (acc[key] ??= []).push(r);
      return acc;
    }, {});
  }, [rows, locale]);

  return (
    <div className="space-y-5" role="tabpanel">
      {txQuery.isLoading && (
        <div className="py-10 text-center text-sm text-white/40">{t("common.loading")}</div>
      )}

      {txQuery.isError && (
        <div className="rounded-2xl border border-rose-500/30 bg-rose-500/5 p-4 text-sm text-rose-200">
          {t("history.financeError")}
        </div>
      )}

      {!txQuery.isLoading && rows.length === 0 && (
        <div className="border-border bg-card space-y-3 rounded-2xl border p-10 text-center">
          <WalletIcon size={28} className="mx-auto text-white/30" />
          <p className="text-sm text-white/60">{t("history.financeEmpty")}</p>
        </div>
      )}

      <div className="space-y-5">
        {Object.entries(grouped).map(([monthYear, txs]) => {
          return (
            <div key={monthYear} className="space-y-2">
              <div className="flex items-center gap-2">
                <span className="text-muted-foreground text-xs font-bold uppercase tracking-[0.08em]">
                  {monthYear}
                </span>
                <div className="bg-border h-px flex-1" />
              </div>

              {txs.map((row, index) => (
                <FinanceRow key={row.id} row={row} index={index} />
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function FinanceRow({ row, index }: { row: UserTransactionView; index: number }) {
  const { t } = useT();
  const locale = useLocale();
  const positive = row.delta >= 0;
  const labelKey = txKindLabelKey(row.kind);
  const label = labelKey ? t(labelKey) : row.kind;
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.04 }}
      className="bg-card border-border flex items-center gap-3 rounded-2xl border p-3.5"
    >
      <div
        className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl"
        style={{
          background: positive ? "rgba(74, 222, 128, 0.12)" : "rgba(248, 113, 113, 0.12)",
          color: positive ? "rgb(134, 239, 172)" : "rgb(252, 165, 165)",
        }}
        aria-hidden="true"
      >
        {positive ? <ArrowDownLeft size={18} /> : <ArrowUpRight size={18} />}
      </div>

      <div className="min-w-0 flex-1">
        <h3 className="truncate text-sm font-bold text-white">{label}</h3>
        <p className="text-muted-foreground mt-0.5 truncate text-[11px]">
          {shortTime(row.createdAt, locale)}
        </p>
      </div>

      <p
        className="whitespace-nowrap text-sm font-bold tabular-nums"
        style={{
          color: positive ? "rgb(134, 239, 172)" : "rgb(252, 165, 165)",
        }}
      >
        {positive ? "+" : "−"}
        {Math.abs(row.delta).toFixed(2)} {row.currency}
      </p>
    </motion.div>
  );
}
