import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import {
  AlertTriangle,
  ArrowDownLeft,
  ArrowUpRight,
  CheckCircle2,
  Clock3,
  Receipt,
  Wallet as WalletIcon,
} from "lucide-react";
import { Link } from "wouter";

import { useMe } from "@/lib/auth";
import { useMyOrders, orderToHistoryRow, type HistoryRow } from "@/lib/orders";
import { useDocumentTitle } from "@/lib/use-document-title";
import {
  summarizeForUser,
  type UserAccountKind,
  type UserTransactionView,
  useWallet,
  useWalletTransactions,
} from "@/lib/wallet";

type Tab = "orders" | "finance";

const STATUS_LABEL: Record<HistoryRow["status"], string> = {
  success: "Выполнено",
  processing: "Обработка",
  failed: "Отменён",
};

const RU_MONTHS = [
  "янв",
  "фев",
  "мар",
  "апр",
  "май",
  "июн",
  "июл",
  "авг",
  "сен",
  "окт",
  "ноя",
  "дек",
];

function monthYearKey(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return `${RU_MONTHS[d.getMonth()] ?? ""} ${d.getFullYear()}`;
}

function shortTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString("ru", { hour: "2-digit", minute: "2-digit" });
}

export default function History() {
  useDocumentTitle("История");
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
      className="p-4 space-y-5"
    >
      <header className="space-y-0.5">
        <h1 className="text-2xl font-bold tracking-tight text-white">История</h1>
        <p className="text-muted-foreground text-sm">
          Все ваши покупки и движения по балансу
        </p>
      </header>

      {!me.data && !me.isLoading && (
        <div className="rounded-2xl border border-yellow-400/30 bg-yellow-400/5 p-4 flex items-start gap-3">
          <AlertTriangle size={18} className="text-yellow-400 flex-shrink-0 mt-0.5" />
          <div className="text-sm">
            <p className="font-semibold text-yellow-200">Откройте в Telegram</p>
            <p className="text-yellow-100/70 text-xs mt-1">
              История доступна только под авторизацией через Telegram Mini App.
            </p>
          </div>
        </div>
      )}

      {me.data && (
        <SegmentedTabs
          value={tab}
          onChange={onTabChange}
          options={[
            { id: "orders", label: "Заказы" },
            { id: "finance", label: "Финансы" },
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
}: {
  value: T;
  onChange: (next: T) => void;
  options: { id: T; label: string }[];
}) {
  return (
    <div
      role="tablist"
      aria-label="Тип истории"
      className="grid grid-cols-2 gap-1 p-1 rounded-2xl"
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
            onClick={() => { onChange(opt.id); }}
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

function OrdersTab() {
  // Tab content is unmounted/remounted when the segmented switcher
  // flips, and ``refetchOnMount: "always"`` on the underlying query
  // makes that remount run a network refresh. So just by toggling
  // Заказы → Финансы → Заказы the user gets a fresh feed without a
  // dedicated refresh button.
  const ordersQuery = useMyOrders();
  const orders = ordersQuery.data ?? [];
  const rows: HistoryRow[] = orders.map(orderToHistoryRow);
  const currency = rows[0]?.currency ?? "USD";

  const grouped = rows.reduce<Record<string, HistoryRow[]>>((acc, tx) => {
    const key = monthYearKey(tx.raw.created_at);
    (acc[key] ??= []).push(tx);
    return acc;
  }, {});

  return (
    <div className="space-y-5" role="tabpanel">
      {ordersQuery.isLoading && (
        <div className="py-10 text-center text-white/40 text-sm">Загрузка…</div>
      )}

      {ordersQuery.isError && (
        <div className="rounded-2xl border border-rose-500/30 bg-rose-500/5 p-4 text-sm text-rose-200">
          Не удалось загрузить историю. Попробуйте позже.
        </div>
      )}

      {!ordersQuery.isLoading && rows.length === 0 && (
        <div className="rounded-2xl border border-border bg-card p-10 text-center space-y-3">
          <Receipt size={28} className="mx-auto text-white/30" />
          <p className="text-white/60 text-sm">У вас ещё нет заказов.</p>
          <Link
            href="/"
            className="inline-block rounded-2xl px-5 py-2.5 text-sm font-semibold"
            style={{ background: "hsl(var(--primary))", color: "#000" }}
          >
            Выбрать игру
          </Link>
        </div>
      )}

      <div className="space-y-5">
        {Object.entries(grouped).map(([monthYear, txs]) => (
          <div key={monthYear} className="space-y-2">
            <div className="flex items-center gap-2">
              <span className="text-xs font-bold text-muted-foreground uppercase tracking-[0.08em]">
                {monthYear}
              </span>
              <div className="flex-1 h-px bg-border" />
              <span className="text-xs text-muted-foreground">
                {txs.reduce((s, t) => s + t.amount, 0).toLocaleString("ru", {
                  maximumFractionDigits: 2,
                })}{" "}
                {txs[0]?.currency ?? currency}
              </span>
            </div>

            {txs.map((tx, index) => (
              <Link key={tx.id} href={`/order/${tx.id}`}>
                <motion.div
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: index * 0.04 }}
                  whileTap={{ scale: 0.985 }}
                  className="flex items-center gap-3 p-3.5 rounded-2xl bg-card border border-border cursor-pointer"
                  data-testid={`history-item-${tx.id}`}
                >
                  <div className="w-11 h-11 rounded-xl overflow-hidden bg-background border border-border flex items-center justify-center shrink-0">
                    {tx.imageUrl ? (
                      <img
                        src={tx.imageUrl}
                        alt=""
                        className="w-full h-full object-cover"
                      />
                    ) : (
                      <Receipt size={18} className="text-muted-foreground" />
                    )}
                  </div>

                  <div className="flex-1 min-w-0">
                    <h3 className="font-bold text-white text-sm truncate">
                      {tx.title}
                    </h3>
                    <p className="text-[11px] text-muted-foreground mt-0.5 truncate">
                      {shortTime(tx.raw.created_at)}
                      {tx.subtitle ? ` · ${tx.subtitle}` : ""}
                      {tx.itemsCount > 1 ? ` · ${tx.itemsCount} поз.` : ""}
                    </p>
                  </div>

                  <div className="text-right shrink-0 space-y-1">
                    <p className="font-bold text-primary text-sm">
                      {tx.amount.toLocaleString("ru", {
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
                            : "text-yellow-400"
                      }`}
                    >
                      {tx.status === "success" ? (
                        <CheckCircle2 size={11} />
                      ) : tx.status === "failed" ? (
                        <AlertTriangle size={11} />
                      ) : (
                        <Clock3 size={11} />
                      )}
                      <span className="text-[10px] font-semibold">
                        {STATUS_LABEL[tx.status]}
                      </span>
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

const TX_KIND_FINANCE_LABEL: Record<string, string> = {
  "admin.adjust": "Корректировка от админа",
  "payment.refund": "Возврат за заказ",
  "topup": "Пополнение",
  "order.payment": "Оплата заказа",
};

function FinanceTab() {
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
      .map((tx) => {
        const view = summarizeForUser(tx, userAccountIds, accountKindById);
        if (view) {
          // Re-map the label to a finance-focused phrasing.
          return { ...view, label: TX_KIND_FINANCE_LABEL[view.kind] ?? view.label };
        }
        return null;
      })
      .filter((v): v is UserTransactionView => v !== null);
  }, [txQuery.data, userAccountIds, accountKindById]);

  const grouped = useMemo(() => {
    return rows.reduce<Record<string, UserTransactionView[]>>((acc, r) => {
      const key = monthYearKey(r.createdAt);
      (acc[key] ??= []).push(r);
      return acc;
    }, {});
  }, [rows]);

  return (
    <div className="space-y-5" role="tabpanel">
      {txQuery.isLoading && (
        <div className="py-10 text-center text-white/40 text-sm">Загрузка…</div>
      )}

      {txQuery.isError && (
        <div className="rounded-2xl border border-rose-500/30 bg-rose-500/5 p-4 text-sm text-rose-200">
          Не удалось загрузить финансовые операции.
        </div>
      )}

      {!txQuery.isLoading && rows.length === 0 && (
        <div className="rounded-2xl border border-border bg-card p-10 text-center space-y-3">
          <WalletIcon size={28} className="mx-auto text-white/30" />
          <p className="text-white/60 text-sm">
            Пополнений и корректировок ещё не было.
          </p>
        </div>
      )}

      <div className="space-y-5">
        {Object.entries(grouped).map(([monthYear, txs]) => {
          const net = txs.reduce((s, t) => s + t.delta, 0);
          const currency = txs[0]?.currency ?? "USD";
          return (
            <div key={monthYear} className="space-y-2">
              <div className="flex items-center gap-2">
                <span className="text-xs font-bold text-muted-foreground uppercase tracking-[0.08em]">
                  {monthYear}
                </span>
                <div className="flex-1 h-px bg-border" />
                <span
                  className="text-xs"
                  style={{
                    color:
                      net >= 0
                        ? "rgb(134, 239, 172)"
                        : "rgb(252, 165, 165)",
                  }}
                >
                  {net >= 0 ? "+" : "−"}
                  {Math.abs(net).toLocaleString("ru", {
                    maximumFractionDigits: 2,
                  })}{" "}
                  {currency}
                </span>
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
  const positive = row.delta >= 0;
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.04 }}
      className="flex items-center gap-3 p-3.5 rounded-2xl bg-card border border-border"
    >
      <div
        className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
        style={{
          background: positive
            ? "rgba(74, 222, 128, 0.12)"
            : "rgba(248, 113, 113, 0.12)",
          color: positive ? "rgb(134, 239, 172)" : "rgb(252, 165, 165)",
        }}
        aria-hidden="true"
      >
        {positive ? (
          <ArrowDownLeft size={18} />
        ) : (
          <ArrowUpRight size={18} />
        )}
      </div>

      <div className="flex-1 min-w-0">
        <h3 className="font-bold text-white text-sm truncate">{row.label}</h3>
        <p className="text-[11px] text-muted-foreground mt-0.5 truncate">
          {shortTime(row.createdAt)}
          {row.reason ? ` · ${row.reason}` : ""}
        </p>
      </div>

      <p
        className="font-bold text-sm tabular-nums whitespace-nowrap"
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
