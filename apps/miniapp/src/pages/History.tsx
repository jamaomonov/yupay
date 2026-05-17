import { motion } from "framer-motion";
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Receipt,
  RotateCcw,
} from "lucide-react";
import { Link } from "wouter";

import { useMe } from "@/lib/auth";
import { useMyOrders, orderToHistoryRow, type HistoryRow } from "@/lib/orders";
import { useDocumentTitle } from "@/lib/use-document-title";

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
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.22 }}
      className="p-4 space-y-5"
    >
      <div className="flex items-start justify-between">
        <div className="space-y-0.5">
          <h1 className="text-2xl font-bold tracking-tight text-white">История</h1>
          <p className="text-muted-foreground text-sm">Все ваши пополнения</p>
        </div>
        {me.data && (
          <button
            type="button"
            onClick={() => ordersQuery.refetch()}
            disabled={ordersQuery.isFetching}
            className="w-9 h-9 rounded-full flex items-center justify-center transition-colors disabled:opacity-40"
            style={{
              background: "hsl(var(--surface-2))",
              border: "1px solid hsl(var(--border))",
            }}
            aria-label="Обновить"
          >
            <RotateCcw
              size={14}
              className={`text-white/60 ${
                ordersQuery.isFetching ? "animate-spin" : ""
              }`}
            />
          </button>
        )}
      </div>

      {!me.data && !me.isLoading && (
        <div className="rounded-2xl border border-yellow-400/30 bg-yellow-400/5 p-4 flex items-start gap-3">
          <AlertTriangle size={18} className="text-yellow-400 flex-shrink-0 mt-0.5" />
          <div className="text-sm">
            <p className="font-semibold text-yellow-200">Откройте в Telegram</p>
            <p className="text-yellow-100/70 text-xs mt-1">
              История заказов доступна только под авторизацией через Telegram Mini App.
            </p>
          </div>
        </div>
      )}

      {ordersQuery.isLoading && me.data && (
        <div className="py-10 text-center text-white/40 text-sm">Загрузка…</div>
      )}

      {ordersQuery.isError && (
        <div className="rounded-2xl border border-rose-500/30 bg-rose-500/5 p-4 text-sm text-rose-200">
          Не удалось загрузить историю. Попробуйте позже.
        </div>
      )}

      {me.data && !ordersQuery.isLoading && rows.length === 0 && (
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

      {/* Grouped transactions */}
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
                {/* Icon — brand/product image when we have one */}
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

                {/* Info */}
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

                {/* Amount + status */}
                <div className="text-right shrink-0 space-y-1">
                  <p className="font-bold text-primary text-sm">
                    {tx.amount.toLocaleString("ru", { maximumFractionDigits: 2 })} {tx.currency}
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
    </motion.div>
  );
}
