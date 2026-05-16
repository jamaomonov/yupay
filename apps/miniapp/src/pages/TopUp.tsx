import { useParams, useLocation } from "wouter";
import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  ArrowLeft, Heart, Share2, Star, Clock, Check, ChevronRight,
  CreditCard, Zap, Bitcoin, Tag, ShieldCheck, RotateCcw, Users, X,
} from "lucide-react";
import { useGames, useBrandWithPrimaryProduct, type Package as ApiPackage } from "@/lib/catalog";
import { useCheckout } from "@/lib/orders";
import { useMe } from "@/lib/auth";
import { useToast } from "@/hooks/use-toast";
import { cn } from "@/lib/utils";
import { ApiError } from "@/lib/api";

// ─── Package types ─────────────────────────────────────────────────────────────
type Package = {
  id: string;            // SKU id (used for checkout)
  currency: number;      // numeric denomination — pulled from sku.denomination
  bonus?: number;
  price: number;         // numeric price in `priceCode`
  priceCode: string;     // currency code (USD by default)
  badge?: { label: string; color: string };
  currencyLabel?: string; // "UC", "VP", or "" — kept for the existing icon switch
};

function denominationToParts(label: string): { amount: number; tag: string } {
  const m = label.match(/^\s*(\d[\d\s,.]*)\s*(.*)$/);
  if (!m) return { amount: 0, tag: label };
  const amount = Number.parseInt((m[1] ?? "").replace(/[\s,.]/g, ""), 10) || 0;
  const tag = (m[2] ?? "").trim();
  return { amount, tag };
}

function adaptPackage(api: ApiPackage): Package {
  const parts = denominationToParts(api.label);
  return {
    id: api.id,
    currency: parts.amount || api.amount || 1,
    price: api.displayPrice?.amount ?? api.priceUsd,
    priceCode: api.displayPrice?.currency ?? "USD",
    currencyLabel: parts.tag || undefined,
  };
}

const PAYMENT_METHODS = [
  { id: "mock",   name: "Mock",    sub: "dev / staging", icon: ShieldCheck },
  { id: "card",   name: "Карта",   sub: "скоро",         icon: CreditCard },
  { id: "sbp",    name: "СБП",     sub: "скоро",         icon: Zap },
  { id: "crypto", name: "Крипта",  sub: "скоро",         icon: Bitcoin },
];

const PROVIDER_BY_METHOD: Record<string, string> = {
  mock: "mock",
  card: "click",
  sbp: "yookassa",
  crypto: "crypto",
};

function formatMoney(value: number, code: string): string {
  if (code === "USD" || code === "USDT") {
    return `$${value.toFixed(2)}`;
  }
  return `${value.toLocaleString("ru", { maximumFractionDigits: 2 })} ${code}`;
}

// ─── Step label ────────────────────────────────────────────────────────────────
function Step({ n, title, sub }: { n: number; title: string; sub?: string }) {
  return (
    <div className="flex items-start gap-3 mb-4">
      <div
        className="w-6 h-6 rounded-full flex items-center justify-center text-[11px] font-black flex-shrink-0 mt-0.5"
        style={{ background: "hsl(var(--primary))", color: "#000" }}
      >
        {n}
      </div>
      <div>
        <p className="text-white font-bold text-base leading-tight">{title}</p>
        {sub && <p className="text-white/40 text-xs mt-0.5">{sub}</p>}
      </div>
    </div>
  );
}

// ─── UC icon ───────────────────────────────────────────────────────────────────
function UCIcon({ label }: { label?: string }) {
  if (label === "VP") return (
    <div className="w-7 h-7 rounded-full flex items-center justify-center text-[9px] font-black flex-shrink-0"
      style={{ background: "#ff4655", color: "#fff" }}>VP</div>
  );
  if (label === "₽") return (
    <div className="w-7 h-7 rounded-full flex items-center justify-center text-[10px] font-black flex-shrink-0"
      style={{ background: "#4285f4", color: "#fff" }}>₽</div>
  );
  return (
    <div className="w-7 h-7 rounded-full flex items-center justify-center text-[9px] font-black flex-shrink-0"
      style={{ background: "#f59e0b", color: "#000" }}>UC</div>
  );
}

// ─── Main component ────────────────────────────────────────────────────────────
export default function TopUp() {
  const { gameId } = useParams();
  const [, setLocation] = useLocation();
  const { toast } = useToast();

  const gamesQuery = useGames();
  const game = gamesQuery.data?.find((g) => g.id === gameId);
  const brandQuery = useBrandWithPrimaryProduct(gameId, "USD");
  const packages: Package[] = (brandQuery.data?.packages ?? []).map(adaptPackage);
  const product = brandQuery.data?.product ?? null;
  const requiredFields = product?.required_fields ?? [];

  const me = useMe();
  const checkout = useCheckout();

  const [accountId, setAccountId]           = useState("");
  const [selectedPkg, setSelectedPkg]       = useState<string>("");
  const [showCustom, setShowCustom]         = useState(false);
  const [customAmount, setCustomAmount]     = useState("");
  const [paymentMethod, setPaymentMethod]   = useState("mock");
  const [promoCode, setPromoCode]           = useState("");
  const [promoOpen, setPromoOpen]           = useState(false);

  // Preselect a sensible default once packages land. Sweet spot: 3rd package, or
  // the first one available.
  if (selectedPkg === "" && packages.length > 0) {
    const initial = packages[2]?.id ?? packages[0]?.id ?? "";
    if (initial) setSelectedPkg(initial);
  }

  const isProcessing = checkout.isPending;

  if (gamesQuery.isLoading || brandQuery.isLoading) {
    return (
      <div className="p-4 pt-24 text-center text-white/40 text-sm">Загрузка…</div>
    );
  }

  if (!game || brandQuery.isError) {
    return (
      <div className="p-4 pt-20 text-center space-y-4">
        <h2 className="text-xl font-bold">Сервис не найден</h2>
        <button onClick={() => setLocation("/")} className="px-6 py-3 bg-primary text-black font-bold rounded-2xl">
          На главную
        </button>
      </div>
    );
  }

  const activePkg = packages.find((p) => p.id === selectedPkg);
  const finalPrice = showCustom && customAmount
    ? parseInt(customAmount, 10)
    : (activePkg?.price ?? 0);
  const finalCurrency = showCustom && customAmount
    ? parseInt(customAmount, 10)
    : (activePkg?.currency ?? 0);
  const currencyLabel = activePkg?.currencyLabel ?? "";
  const priceCode = activePkg?.priceCode ?? "USD";

  const handlePayment = async () => {
    if (!activePkg) {
      toast({ title: "Выберите пакет", description: "Сначала укажи номинал", variant: "destructive" });
      return;
    }
    if (requiredFields.length > 0 && !accountId.trim()) {
      toast({ title: "Заполните поле", description: `Введите ${game.inputType}`, variant: "destructive" });
      return;
    }
    if (!me.data) {
      toast({
        title: "Откройте в Telegram",
        description: "Оплата доступна только из Telegram Mini App",
        variant: "destructive",
      });
      return;
    }
    // Map the single input field to whatever the product expects. If there are
    // several fields we'd render them dynamically — that's a follow-up.
    const fulfillmentData: Record<string, string> = {};
    const primaryField = requiredFields.find((f) => f.required) ?? requiredFields[0];
    if (primaryField) {
      fulfillmentData[primaryField.key] = accountId.trim();
    } else if (accountId.trim()) {
      fulfillmentData["account_id"] = accountId.trim();
    }
    try {
      const result = await checkout.mutateAsync({
        skuId: activePkg.id,
        fulfillmentData,
        provider: PROVIDER_BY_METHOD[paymentMethod] ?? "mock",
      });
      if (result.payment.intent_url) {
        toast({
          title: "Перенаправляем на оплату",
          description: result.payment.provider,
        });
        // For mock the URL is a placeholder; in dev we just announce success.
        if (result.payment.provider !== "mock") {
          window.location.href = result.payment.intent_url;
          return;
        }
      } else {
        toast({ title: "Заказ создан", description: `${game.name} в обработке` });
      }
      setLocation("/history");
    } catch (exc) {
      const detail = exc instanceof ApiError ? exc.detail : "Попробуйте ещё раз";
      toast({ title: "Не удалось оформить", description: detail, variant: "destructive" });
    }
  };

  return (
    <>
      <motion.div
        initial={{ opacity: 0, x: 20 }}
        animate={{ opacity: 1, x: 0 }}
        exit={{ opacity: 0, x: -20 }}
        className="pb-32"
      >
        {/* ── Hero ── */}
        <div className="relative h-56 overflow-hidden">
          {game.bgUrl ? (
            <img src={game.bgUrl} className="absolute inset-0 w-full h-full object-cover" alt={game.name} />
          ) : (
            <div className={`absolute inset-0 bg-gradient-to-br ${game.gradient}`} />
          )}
          <div className="absolute inset-0 bg-gradient-to-t from-background via-background/40 to-black/20" />

          {/* Top buttons */}
          <div className="absolute top-12 left-4 right-4 flex items-center justify-between z-10">
            <button
              onClick={() => setLocation("/")}
              className="w-9 h-9 rounded-full bg-black/50 backdrop-blur-md border border-white/10 flex items-center justify-center"
              data-testid="btn-back"
            >
              <ArrowLeft size={16} className="text-white" />
            </button>
            <div className="flex items-center gap-2">
              <button className="w-9 h-9 rounded-full bg-black/50 backdrop-blur-md border border-white/10 flex items-center justify-center">
                <Heart size={15} className="text-white/70" />
              </button>
              <button className="w-9 h-9 rounded-full bg-black/50 backdrop-blur-md border border-white/10 flex items-center justify-center">
                <Share2 size={15} className="text-white/70" />
              </button>
            </div>
          </div>

          {/* Game info row — bottom of hero */}
          <div className="absolute bottom-0 left-0 right-0 px-4 pb-4 flex items-end gap-3 z-10">
            <div className="w-14 h-14 rounded-[18px] overflow-hidden shadow-xl border border-white/15 flex-shrink-0">
              {game.appIcon ? (
                <img src={game.appIcon} className="w-full h-full object-cover" alt={game.name} />
              ) : game.bgUrl ? (
                <img src={game.bgUrl} className="w-full h-full object-cover" alt={game.name} />
              ) : (
                <div className={`w-full h-full bg-gradient-to-br ${game.gradient} flex items-center justify-center`}>
                  {game.icon && <game.icon style={{ width: 24, height: 24, color: game.iconColor || "#fff" }} />}
                </div>
              )}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-white/50 text-[11px] uppercase tracking-wide">{game.publisher}</p>
              <h1 className="text-white font-black text-lg leading-tight">{game.name}</h1>
              <div className="flex items-center gap-3 mt-0.5">
                <div className="flex items-center gap-1">
                  <Star size={11} className="text-yellow-400 fill-yellow-400" />
                  <span className="text-white/60 text-[11px]">4.9 · 8.2k отзывов</span>
                </div>
                <div className="flex items-center gap-1 px-2 py-0.5 rounded-full"
                  style={{ background: "hsl(var(--primary) / 0.15)", border: "1px solid hsl(var(--primary) / 0.3)" }}>
                  <Clock size={10} className="text-primary" />
                  <span className="text-primary text-[10px] font-semibold">1–2 мин</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* ── Form ── */}
        <div className="px-4 pt-5 space-y-7">

          {/* Step 1 — Account ID */}
          <div>
            <Step n={1} title={`Введите ${game.inputType}`} sub="UID профиля в игре" />
            <div className="relative">
              <input
                value={accountId}
                onChange={(e) => setAccountId(e.target.value)}
                placeholder={game.inputPlaceholder}
                className="w-full rounded-2xl px-4 py-3.5 text-base text-white placeholder:text-white/25 outline-none transition-all"
                style={{
                  background: "hsl(228 32% 17%)",
                  border: accountId
                    ? "1.5px solid hsl(var(--primary) / 0.7)"
                    : "1.5px solid hsl(var(--border))",
                  color: accountId ? "hsl(var(--primary))" : "white",
                  letterSpacing: accountId ? "0.08em" : "normal",
                }}
                data-testid="input-account-id"
              />
              {accountId && (
                <button
                  onClick={() => setAccountId("")}
                  className="absolute right-3.5 top-1/2 -translate-y-1/2 w-6 h-6 rounded-full bg-white/10 flex items-center justify-center"
                >
                  <X size={12} className="text-white/60" />
                </button>
              )}
            </div>

            {/* Validation hint */}
            <AnimatePresence>
              {accountId.length >= 4 && (
                <motion.div
                  initial={{ opacity: 0, y: -4 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                  className="flex items-center justify-between mt-2 px-1"
                >
                  <div className="flex items-center gap-1.5">
                    <Check size={12} className="text-primary" />
                    <span className="text-primary text-xs font-medium">Найден: iLoveChicken</span>
                  </div>
                  <button className="flex items-center gap-1 text-white/40 text-xs">
                    Где найти ID?
                    <ChevronRight size={11} />
                  </button>
                </motion.div>
              )}
            </AnimatePresence>
          </div>

          {/* Step 2 — Packages */}
          <div>
            <Step
              n={2}
              title={`Сколько ${currencyLabel === "₽" ? "пополнить?" : currencyLabel + "?"}`}
              sub="Выбери пакет — зачисление сразу"
            />

            <div className="grid grid-cols-2 gap-2.5">
              {packages.map((pkg) => {
                const active = selectedPkg === pkg.id && !showCustom;
                return (
                  <button
                    key={pkg.id}
                    onClick={() => { setSelectedPkg(pkg.id); setShowCustom(false); }}
                    className="relative text-left p-3.5 rounded-2xl transition-all duration-150"
                    style={{
                      background: active ? "hsl(228 32% 20%)" : "hsl(228 32% 16%)",
                      border: active
                        ? "1.5px solid hsl(var(--primary) / 0.8)"
                        : "1.5px solid hsl(var(--border))",
                      boxShadow: active ? "0 0 0 3px hsl(var(--primary) / 0.1)" : "none",
                    }}
                    data-testid={`btn-pkg-${pkg.id}`}
                  >
                    {/* Badge */}
                    {pkg.badge && (
                      <div
                        className="absolute -top-2 left-3 px-2 py-0.5 rounded-md text-[9px] font-black tracking-wider"
                        style={{ background: pkg.badge.color, color: "#fff" }}
                      >
                        {pkg.badge.label}
                      </div>
                    )}

                    {/* Checkmark */}
                    {active && (
                      <div
                        className="absolute top-2.5 right-2.5 w-5 h-5 rounded-full flex items-center justify-center"
                        style={{ background: "hsl(var(--primary))" }}
                      >
                        <Check size={11} strokeWidth={3} className="text-black" />
                      </div>
                    )}

                    <div className="flex items-center gap-2 mb-1.5">
                      <UCIcon label={pkg.currencyLabel} />
                      <span className="text-white font-black text-lg leading-none">
                        {pkg.currency.toLocaleString("ru")}
                      </span>
                    </div>

                    {pkg.bonus && (
                      <p className="text-white/40 text-[11px] mb-2">
                        +{pkg.bonus} бонус {pkg.currencyLabel}
                      </p>
                    )}

                    <p className="text-white font-bold text-sm">
                      {formatMoney(pkg.price, pkg.priceCode)}
                    </p>
                  </button>
                );
              })}
            </div>

            {/* Custom amount */}
            <button
              onClick={() => setShowCustom(!showCustom)}
              className="w-full mt-3 py-3 rounded-2xl border text-sm font-semibold text-white/50 flex items-center justify-center gap-2 transition-colors"
              style={{
                border: showCustom ? "1.5px solid hsl(var(--primary) / 0.5)" : "1.5px solid hsl(var(--border))",
                background: "hsl(228 32% 16%)",
              }}
            >
              + Другая сумма
            </button>

            <AnimatePresence>
              {showCustom && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: "auto" }}
                  exit={{ opacity: 0, height: 0 }}
                  className="overflow-hidden"
                >
                  <div className="relative mt-2">
                    <input
                      type="tel"
                      value={customAmount}
                      onChange={(e) => setCustomAmount(e.target.value.replace(/\D/g, ""))}
                      placeholder="Введите сумму"
                      className="w-full rounded-2xl px-4 py-3.5 pr-12 text-base text-white placeholder:text-white/25 outline-none"
                      style={{
                        background: "hsl(228 32% 17%)",
                        border: "1.5px solid hsl(var(--primary) / 0.5)",
                      }}
                    />
                    <span className="absolute right-4 top-1/2 -translate-y-1/2 text-white/40 font-bold">₽</span>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>

          {/* Step 3 — Payment */}
          <div>
            <Step n={3} title="Способ оплаты" sub="без комиссии, мгновенно" />

            <div className="grid grid-cols-3 gap-2 mb-3">
              {PAYMENT_METHODS.map((m) => {
                const active = paymentMethod === m.id;
                const Icon = m.icon;
                return (
                  <button
                    key={m.id}
                    onClick={() => setPaymentMethod(m.id)}
                    className="relative flex flex-col items-center gap-1.5 py-3.5 rounded-2xl transition-all duration-150"
                    style={{
                      background: active ? "hsl(228 32% 20%)" : "hsl(228 32% 16%)",
                      border: active
                        ? "1.5px solid hsl(var(--primary) / 0.8)"
                        : "1.5px solid hsl(var(--border))",
                    }}
                    data-testid={`btn-pay-${m.id}`}
                  >
                    {active && (
                      <div
                        className="absolute top-2 right-2 w-4 h-4 rounded-full flex items-center justify-center"
                        style={{ background: "hsl(var(--primary))" }}
                      >
                        <Check size={9} strokeWidth={3} className="text-black" />
                      </div>
                    )}
                    <Icon size={20} className={active ? "text-primary" : "text-white/40"} />
                    <span className={cn("text-xs font-bold", active ? "text-white" : "text-white/50")}>{m.name}</span>
                    <span className="text-[10px] text-white/30">{m.sub}</span>
                  </button>
                );
              })}
            </div>

            {/* Promo code */}
            <button
              onClick={() => setPromoOpen(!promoOpen)}
              className="w-full flex items-center gap-3 px-4 py-3 rounded-2xl transition-all"
              style={{
                background: "hsl(228 32% 16%)",
                border: promoOpen ? "1.5px solid hsl(var(--primary) / 0.5)" : "1.5px solid hsl(var(--border))",
              }}
            >
              <Tag size={15} className="text-primary flex-shrink-0" />
              {promoOpen ? (
                <input
                  autoFocus
                  value={promoCode}
                  onChange={(e) => setPromoCode(e.target.value)}
                  placeholder="Введите промокод"
                  onClick={(e) => e.stopPropagation()}
                  className="flex-1 bg-transparent text-sm text-white placeholder:text-white/30 outline-none"
                />
              ) : (
                <span className="flex-1 text-left text-sm text-white/40">Промокод, есть код?</span>
              )}
              <ChevronRight size={15} className={cn("text-white/25 transition-transform", promoOpen && "rotate-90")} />
            </button>
          </div>

          {/* Trust items */}
          <div className="space-y-2.5 pt-1">
            {[
              { icon: ShieldCheck, text: `Без передачи пароля — только ${game.inputType}` },
              { icon: RotateCcw,   text: "Зачисление 1–2 минуты, иначе возврат" },
              { icon: Users,       text: `1 247 пополнений ${game.name} за сегодня` },
            ].map(({ icon: Icon, text }, i) => (
              <div key={i} className="flex items-center gap-2.5">
                <Icon size={14} className="text-white/25 flex-shrink-0" />
                <span className="text-white/35 text-xs">{text}</span>
              </div>
            ))}
          </div>

          {/* Order summary */}
          {accountId && activePkg && !showCustom && (
            <motion.div
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex items-center gap-3 p-3 rounded-2xl"
              style={{ background: "hsl(228 32% 16%)", border: "1px solid hsl(var(--border))" }}
            >
              <div className="w-10 h-10 rounded-[14px] overflow-hidden flex-shrink-0">
                {game.appIcon ? (
                  <img src={game.appIcon} className="w-full h-full object-cover" alt={game.name} />
                ) : game.bgUrl ? (
                  <img src={game.bgUrl} className="w-full h-full object-cover" alt={game.name} />
                ) : (
                  <div className={`w-full h-full bg-gradient-to-br ${game.gradient} flex items-center justify-center`}>
                    {game.icon && <game.icon style={{ width: 16, height: 16, color: game.iconColor || "#fff" }} />}
                  </div>
                )}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-white text-sm font-semibold">
                  {activePkg.currency.toLocaleString("ru")} {currencyLabel}
                  {activePkg.bonus && (
                    <span className="text-primary text-xs ml-1">+{activePkg.bonus} бонус</span>
                  )}
                </p>
                <p className="text-white/40 text-xs mt-0.5 line-clamp-1">
                  по ID {accountId}
                </p>
              </div>
              <p className="text-white font-black text-sm flex-shrink-0">
                {formatMoney(activePkg.price, activePkg.priceCode)}
              </p>
            </motion.div>
          )}
        </div>
      </motion.div>

      {/* ── Fixed CTA ── */}
      <div className="fixed bottom-[76px] left-1/2 -translate-x-1/2 w-full max-w-[430px] px-4 z-40">
        <motion.button
          whileTap={{ scale: 0.97 }}
          onClick={handlePayment}
          disabled={isProcessing}
          className="w-full py-4 rounded-2xl text-base font-black tracking-wide flex items-center justify-center gap-2 transition-all"
          style={{
            background: isProcessing ? "hsl(var(--primary) / 0.5)" : "hsl(var(--primary))",
            color: "#000",
            boxShadow: isProcessing ? "none" : "0 0 24px hsl(var(--primary) / 0.35)",
          }}
          data-testid="btn-pay"
        >
          {isProcessing ? (
            "Обработка..."
          ) : (
            <>
              Пополнить за {finalPrice > 0 ? formatMoney(finalPrice, priceCode) : "—"}
              <ChevronRight size={18} strokeWidth={2.5} />
            </>
          )}
        </motion.button>
      </div>
    </>
  );
}
