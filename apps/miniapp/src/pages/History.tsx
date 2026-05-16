import { motion } from "framer-motion";
import { HISTORY, GAMES } from "@/lib/constants";
import { CheckCircle2, Clock3, TrendingUp, Receipt } from "lucide-react";

function parseMonthYear(dateStr: string): string {
  const head = dateStr.split(", ")[0] ?? "";
  const parts = head.split(" ");
  return `${parts[1] ?? ""} ${parts[2] ?? ""}`.trim();
}

export default function History() {
  const successTxs = HISTORY.filter((t) => t.status === "success");
  const totalSpent = successTxs.reduce((sum, t) => sum + t.amount, 0);
  const processingCount = HISTORY.filter((t) => t.status === "processing").length;

  const grouped = HISTORY.reduce(
    (acc, tx) => {
      const key = parseMonthYear(tx.date);
      if (!acc[key]) acc[key] = [];
      acc[key].push(tx);
      return acc;
    },
    {} as Record<string, typeof HISTORY>
  );

  return (
    <motion.div
      initial={{ opacity: 0, x: -20 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: -20 }}
      className="p-4 space-y-5"
    >
      <div className="space-y-0.5">
        <h1 className="text-2xl font-bold tracking-tight text-white">История</h1>
        <p className="text-muted-foreground text-sm">Все ваши пополнения</p>
      </div>

      {/* Summary strip */}
      <div className="grid grid-cols-3 gap-2">
        <div className="bg-card border border-border rounded-2xl p-3 flex flex-col gap-1">
          <TrendingUp size={16} className="text-primary" />
          <p className="text-lg font-black text-primary leading-none">{totalSpent.toLocaleString("ru")} ₽</p>
          <p className="text-[10px] text-muted-foreground leading-tight">Потрачено всего</p>
        </div>
        <div className="bg-card border border-border rounded-2xl p-3 flex flex-col gap-1">
          <CheckCircle2 size={16} className="text-green-400" />
          <p className="text-lg font-black text-white leading-none">{successTxs.length}</p>
          <p className="text-[10px] text-muted-foreground leading-tight">Выполнено</p>
        </div>
        <div className="bg-card border border-border rounded-2xl p-3 flex flex-col gap-1">
          <Clock3 size={16} className="text-yellow-400" />
          <p className="text-lg font-black text-white leading-none">{processingCount}</p>
          <p className="text-[10px] text-muted-foreground leading-tight">В обработке</p>
        </div>
      </div>

      {/* Grouped transactions */}
      <div className="space-y-5">
        {Object.entries(grouped).map(([monthYear, txs]) => (
          <div key={monthYear} className="space-y-2">
            <div className="flex items-center gap-2">
              <span className="text-xs font-bold text-muted-foreground uppercase tracking-widest">
                {monthYear}
              </span>
              <div className="flex-1 h-px bg-border" />
              <span className="text-xs text-muted-foreground">
                {txs.reduce((s, t) => s + t.amount, 0).toLocaleString("ru")} ₽
              </span>
            </div>

            {txs.map((tx, index) => {
              const game = GAMES.find((g) => g.id === tx.gameId);
              if (!game) return null;

              return (
                <motion.div
                  key={tx.id}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: index * 0.04 }}
                  className="flex items-center gap-3 p-3.5 rounded-2xl bg-card border border-border"
                  data-testid={`history-item-${tx.id}`}
                >
                  {/* Icon */}
                  <div className="w-11 h-11 rounded-xl bg-background border border-border flex items-center justify-center shrink-0 p-1.5 relative overflow-hidden">
                    {game.bgUrl && (
                      <div
                        className="absolute inset-0 opacity-30"
                        style={{
                          backgroundImage: `url(${game.bgUrl})`,
                          backgroundSize: "cover",
                          backgroundPosition: "center",
                        }}
                      />
                    )}
                    {game.logoUrl ? (
                      <img src={game.logoUrl} className="w-full h-auto z-10 relative" alt={game.name} />
                    ) : game.icon ? (
                      <game.icon
                        className="z-10 relative"
                        style={{ width: 20, height: 20, color: game.iconColor || "#fff" }}
                      />
                    ) : (
                      <Receipt size={18} className="text-muted-foreground z-10 relative" />
                    )}
                  </div>

                  {/* Info */}
                  <div className="flex-1 min-w-0">
                    <h3 className="font-bold text-white text-sm truncate">{game.name}</h3>
                    <p className="text-[11px] text-muted-foreground mt-0.5 truncate">
                      {tx.date.split(", ")[1] ?? ""} · {tx.date.split(", ")[0]}
                    </p>
                  </div>

                  {/* Amount + status */}
                  <div className="text-right shrink-0 space-y-1">
                    <p className="font-black text-primary text-sm">{tx.amount.toLocaleString("ru")} ₽</p>
                    {tx.status === "success" ? (
                      <div className="flex items-center justify-end gap-1 text-green-400">
                        <CheckCircle2 size={11} />
                        <span className="text-[10px] font-semibold">Выполнено</span>
                      </div>
                    ) : (
                      <div className="flex items-center justify-end gap-1 text-yellow-400">
                        <Clock3 size={11} />
                        <span className="text-[10px] font-semibold">Обработка</span>
                      </div>
                    )}
                  </div>
                </motion.div>
              );
            })}
          </div>
        ))}
      </div>
    </motion.div>
  );
}
