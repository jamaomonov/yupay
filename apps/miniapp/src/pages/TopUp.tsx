import { useEffect, useMemo, useState } from "react";
import { useLocation, useParams } from "wouter";
import { motion } from "framer-motion";
import {
  ArrowLeft,
  Bitcoin,
  Check,
  ChevronRight,
  Clock,
  CreditCard,
  ExternalLink,
  Heart,
  Package as PackageIcon,
  RotateCcw,
  Send,
  Share2,
  ShieldCheck,
  Star,
  Zap,
} from "lucide-react";

import { DynamicFields } from "@/components/DynamicFields";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/hooks/use-toast";
import { ApiError } from "@/lib/api";
import { useMe } from "@/lib/auth";
import { isInsideTelegram } from "@/lib/telegram";
import {
  useBrandSummary,
  useGames,
  useProductWithSkus,
  type Package as ApiPackage,
} from "@/lib/catalog";
import { useCurrencyStore } from "@/lib/currency";
import { useCheckout } from "@/lib/orders";
import {
  forgetFulfillment,
  getRecentFulfillment,
  rememberFulfillment,
} from "@/lib/recent-checkout";
import { cn } from "@/lib/utils";

// ─── Adapter: API Package → local Package ─────────────────────────────────────
// Keeps badge/bonus optional for future enrichment.
type Package = {
  id: string;
  amount: number;
  label: string;
  region: string | null;
  price: number;
  priceCode: string;
  imageUrl: string | null;
  badge?: { label: string; color: string };
};

function adaptPackage(api: ApiPackage): Package {
  return {
    id: api.id,
    amount: api.amount,
    label: api.label,
    region: api.region,
    price: api.displayPrice?.amount ?? api.priceUsd,
    priceCode: api.displayPrice?.currency ?? "USD",
    imageUrl: api.imageUrl,
  };
}

// `mock` is a dev-only payment method — it short-circuits to a synchronous
// fulfilment via the MockFulfiller. Shipping it in prod is a footgun: a user
// can tap "Pay" with Mock pre-selected, see a "success" toast and never realise
// nothing was charged.
const ALL_PAYMENT_METHODS = [
  { id: "mock", name: "Mock", sub: "dev",        icon: ShieldCheck, devOnly: true },
  { id: "card", name: "Карта", sub: "Visa · МИР", icon: CreditCard, devOnly: false },
  { id: "sbp",  name: "СБП",   sub: "без коми",   icon: Zap,        devOnly: false },
  { id: "crypto", name: "Крипта", sub: "USDT",    icon: Bitcoin,    devOnly: false },
];

const PAYMENT_METHODS = ALL_PAYMENT_METHODS.filter(
  (m) => !m.devOnly || import.meta.env.DEV,
);

const DEFAULT_PAYMENT_METHOD = PAYMENT_METHODS[0]?.id ?? "card";

// When the user opens the miniapp in a plain browser we can't take payment
// (auth is bound to Telegram initData). Deep-link them back into the bot
// rather than letting them fill the whole form and bouncing at submit.
const BOT_USERNAME = (
  (import.meta.env.VITE_TELEGRAM_BOT_USERNAME as string | undefined) ?? ""
).replace(/^@/, "");
const TELEGRAM_DEEP_LINK = BOT_USERNAME ? `https://t.me/${BOT_USERNAME}` : null;

const PROVIDER_BY_METHOD: Record<string, string> = {
  mock: "mock",
  card: "click",
  sbp: "yookassa",
  crypto: "crypto",
};

// What the user will actually see on their bank statement / wallet after the
// gateway settles. Surfacing this upfront prevents the "I paid $5 but my bank
// statement shows 61 800 UZS — am I being scammed?" support ticket.
interface AcquirerInfo {
  label: string;
  currency: string;
}

const ACQUIRER_BY_METHOD: Record<string, AcquirerInfo> = {
  mock: { label: "Mock-провайдер", currency: "USD" },
  card: { label: "Click", currency: "UZS" },
  sbp: { label: "СБП через YooKassa", currency: "RUB" },
  crypto: { label: "USDT TRC-20", currency: "USDT" },
};

function formatMoney(value: number, code: string): string {
  if (code === "USD" || code === "USDT") return `$${value.toFixed(2)}`;
  return `${value.toLocaleString("ru", { maximumFractionDigits: 2 })} ${code}`;
}

// ─── Step heading ──────────────────────────────────────────────────────────────
function Step({ n, title, sub }: { n: number; title: string; sub?: string }) {
  return (
    <div className="flex items-start gap-3 mb-3.5">
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

// ─── Page ─────────────────────────────────────────────────────────────────────
export default function TopUp() {
  const { gameId } = useParams();
  const [, setLocation] = useLocation();
  const { toast } = useToast();

  const gamesQuery = useGames();
  const game = gamesQuery.data?.find((g) => g.id === gameId);
  const brandQuery = useBrandSummary(gameId);
  const products = brandQuery.data?.products ?? [];

  // The currently picked product within the brand (PUBG UC vs Royale Pass …).
  const [selectedProductSlug, setSelectedProductSlug] = useState<string>("");
  useEffect(() => {
    if (!selectedProductSlug && products.length > 0) {
      setSelectedProductSlug(products[0]!.slug);
    }
  }, [products, selectedProductSlug]);

  const currency = useCurrencyStore((s) => s.currency);
  const productQuery = useProductWithSkus(selectedProductSlug || undefined, currency);
  const requiredFields = productQuery.data?.product.required_fields ?? [];
  const productImage = productQuery.data?.product.image_url ?? null;
  const packages: Package[] = useMemo(
    () => (productQuery.data?.packages ?? []).map(adaptPackage),
    [productQuery.data],
  );

  const me = useMe();
  const checkout = useCheckout();
  const isProcessing = checkout.isPending;
  // Checkout requires Telegram initData. Detected once at mount — re-running
  // on every render would let an authenticated user navigate-and-render with
  // a stale answer if their session was just rebuilt.
  const insideTelegram = isInsideTelegram();

  const [fulfillment, setFulfillment] = useState<Record<string, string>>({});
  // Pre-filled from localStorage on the first hydration of the form. We
  // surface a chip ("Используем те же данные · изменить") so the user is
  // never surprised, and the chip dismiss clears state + storage.
  const [prefilled, setPrefilled] = useState(false);
  const [selectedPkg, setSelectedPkg] = useState<string>("");
  const [paymentMethod, setPaymentMethod] = useState(DEFAULT_PAYMENT_METHOD);

  // Re-default the SKU on every product switch: pick the 3rd (often a popular
  // mid-tier) or fall back to the first.
  useEffect(() => {
    if (packages.length === 0) return;
    const stillPresent = packages.find((p) => p.id === selectedPkg);
    if (!stillPresent) {
      setSelectedPkg(packages[2]?.id ?? packages[0]?.id ?? "");
    }
  }, [packages, selectedPkg]);

  // Prefill fulfillment_data from the user's last successful checkout for
  // this brand. Runs once per brand-slug change: switching brand wipes the
  // prefilled flag so we don't carry PUBG's player_id into Steam's email.
  useEffect(() => {
    if (!gameId) return;
    const recent = getRecentFulfillment(gameId);
    if (!recent) {
      setPrefilled(false);
      return;
    }
    setFulfillment(recent.fulfillment_data);
    setPrefilled(true);
  }, [gameId]);

  const clearPrefilled = () => {
    if (!gameId) return;
    forgetFulfillment(gameId);
    setFulfillment({});
    setPrefilled(false);
  };

  if (gamesQuery.isLoading || brandQuery.isLoading) {
    return <PageSkeleton onBack={() => setLocation("/")} />;
  }
  if (!game || brandQuery.isError) {
    return (
      <div className="p-4 pt-20 text-center space-y-4">
        <h2 className="text-xl font-bold">Сервис не найден</h2>
        <button
          onClick={() => setLocation("/")}
          className="px-6 py-3 bg-primary text-black font-bold rounded-2xl"
        >
          На главную
        </button>
      </div>
    );
  }

  const activePkg = packages.find((p) => p.id === selectedPkg);
  const priceCode = activePkg?.priceCode ?? currency;
  const finalPrice = activePkg?.price ?? 0;

  const accountRequired = requiredFields.length > 0;
  const missingFieldKey = requiredFields.find((f) => {
    if (!f.required) return false;
    const v = fulfillment[f.key];
    return !v || v.trim().length === 0;
  })?.key;
  const fillingHint = accountRequired
    ? `Введите ${requiredFields[0]?.label?.["ru"] ?? "данные"} аккаунта`
    : "Без передачи аккаунта";

  const handlePayment = async () => {
    if (!activePkg) {
      toast({
        title: "Выберите пакет",
        description: "Сначала укажи номинал",
        variant: "destructive",
      });
      return;
    }
    if (missingFieldKey) {
      const f = requiredFields.find((x) => x.key === missingFieldKey);
      toast({
        title: "Заполните поле",
        description: f?.label?.["ru"] ?? missingFieldKey,
        variant: "destructive",
      });
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
    const fulfillmentData: Record<string, string> = {};
    for (const f of requiredFields) {
      const v = (fulfillment[f.key] ?? "").trim();
      if (v) fulfillmentData[f.key] = v;
    }
    try {
      const result = await checkout.mutateAsync({
        skuId: activePkg.id,
        fulfillmentData,
        currency,
        provider: PROVIDER_BY_METHOD[paymentMethod] ?? "click",
      });
      // Remember the fulfilment payload only after the order was accepted by
      // the API — no point caching a half-typed player_id that came back
      // 400. Subsequent visits to this brand pick it back up automatically.
      if (gameId) rememberFulfillment(gameId, fulfillmentData);
      if (result.payment.intent_url && result.payment.provider !== "mock") {
        toast({
          title: "Перенаправляем на оплату",
          description: result.payment.provider,
        });
        window.location.href = result.payment.intent_url;
        return;
      }
      toast({ title: "Заказ создан", description: `${game.name} в обработке` });
      setLocation(`/order/${result.order.id}`);
    } catch (exc) {
      const detail = exc instanceof ApiError ? exc.detail : "Попробуйте ещё раз";
      toast({
        title: "Не удалось оформить",
        description: detail,
        variant: "destructive",
      });
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
            <img
              src={game.bgUrl}
              className="absolute inset-0 w-full h-full object-cover"
              alt={game.name}
            />
          ) : (
            <div className="absolute inset-0 bg-gradient-to-br from-slate-800 to-slate-950" />
          )}
          <div className="absolute inset-0 bg-gradient-to-t from-background via-background/40 to-black/20" />

          <div className="absolute top-12 left-4 right-4 flex items-center justify-between z-10">
            <button
              onClick={() => setLocation("/")}
              className="w-9 h-9 rounded-full bg-black/50 backdrop-blur-md border border-white/10 flex items-center justify-center"
              data-testid="btn-back"
              aria-label="Назад"
            >
              <ArrowLeft size={16} className="text-white" />
            </button>
            <div className="flex items-center gap-2">
              <button
                className="w-9 h-9 rounded-full bg-black/50 backdrop-blur-md border border-white/10 flex items-center justify-center"
                aria-label="В избранное"
              >
                <Heart size={15} className="text-white/70" />
              </button>
              <button
                className="w-9 h-9 rounded-full bg-black/50 backdrop-blur-md border border-white/10 flex items-center justify-center"
                aria-label="Поделиться"
              >
                <Share2 size={15} className="text-white/70" />
              </button>
            </div>
          </div>

          <div className="absolute bottom-0 left-0 right-0 px-4 pb-4 flex items-end gap-3 z-10">
            <div className="w-14 h-14 rounded-[18px] overflow-hidden shadow-xl border border-white/15 flex-shrink-0">
              {game.appIcon ? (
                <img
                  src={game.appIcon}
                  className="w-full h-full object-cover"
                  alt={game.name}
                />
              ) : (
                <div
                  className="w-full h-full flex items-center justify-center text-white/80 font-black text-xl"
                  style={{ background: game.color }}
                >
                  {game.name.charAt(0)}
                </div>
              )}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-white/50 text-[11px] uppercase tracking-wide line-clamp-1">
                {game.publisher || "YuPay"}
              </p>
              <h1 className="text-white font-black text-lg leading-tight line-clamp-1">
                {game.name}
              </h1>
              <div className="flex items-center gap-3 mt-0.5">
                <div className="flex items-center gap-1">
                  <Star size={11} className="text-yellow-400 fill-yellow-400" />
                  <span className="text-white/60 text-[11px]">4.9</span>
                </div>
                <div
                  className="flex items-center gap-1 px-2 py-0.5 rounded-full"
                  style={{
                    background: "hsl(var(--primary) / 0.15)",
                    border: "1px solid hsl(var(--primary) / 0.3)",
                  }}
                >
                  <Clock size={10} className="text-primary" />
                  <span className="text-primary text-[10px] font-semibold">
                    1–2 мин
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Telegram-only banner — surfaced at the top of the funnel, before
            the user invests time filling fulfilment fields and picking a
            package. */}
        {!insideTelegram && (
          <div className="px-4 pt-4">
            <div
              className="rounded-2xl p-4 flex items-start gap-3"
              style={{
                background: "hsl(228 32% 14%)",
                border: "1.5px solid hsl(var(--primary) / 0.4)",
              }}
              role="status"
            >
              <div
                className="size-9 rounded-xl flex items-center justify-center flex-shrink-0"
                style={{
                  background: "hsl(var(--primary) / 0.15)",
                  color: "hsl(var(--primary))",
                }}
                aria-hidden="true"
              >
                <Send size={16} />
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-white font-semibold text-sm leading-tight">
                  Откройте в Telegram
                </p>
                <p className="text-white/55 text-[12px] mt-1 leading-relaxed">
                  Оплата привязана к вашему Telegram-аккаунту. Каталог
                  доступен для просмотра — оформить заказ можно только из бота.
                </p>
                {TELEGRAM_DEEP_LINK && (
                  <a
                    href={TELEGRAM_DEEP_LINK}
                    className="mt-2.5 inline-flex items-center gap-1.5 text-[12px] font-semibold transition-opacity active:opacity-70"
                    style={{ color: "hsl(var(--primary))" }}
                  >
                    Открыть бота
                    <ExternalLink size={11} />
                  </a>
                )}
              </div>
            </div>
          </div>
        )}

        {/* ── Form ── */}
        <div className="px-4 pt-5 space-y-7">
          {/* Step 0 — Product picker (only when there's more than one product) */}
          {products.length > 1 && (
            <div>
              <div className="flex items-center justify-between mb-2.5">
                <div className="flex items-center gap-2">
                  <PackageIcon size={13} className="text-white/40" />
                  <span className="text-xs font-semibold text-white/50 uppercase tracking-wide">
                    Выберите продукт
                  </span>
                </div>
                <span className="text-[10px] text-white/30">
                  {products.length} опций
                </span>
              </div>
              <div className="flex gap-2 overflow-x-auto no-scrollbar -mx-4 px-4">
                {products.map((p) => {
                  const active = p.slug === selectedProductSlug;
                  return (
                    <button
                      key={p.id}
                      onClick={() => setSelectedProductSlug(p.slug)}
                      className="flex items-center gap-2 flex-shrink-0 pl-2 pr-3 py-1.5 rounded-2xl transition-all duration-150"
                      style={{
                        background: active
                          ? "hsl(228 32% 22%)"
                          : "hsl(228 32% 16%)",
                        border: active
                          ? "1.5px solid hsl(var(--primary) / 0.7)"
                          : "1.5px solid hsl(var(--border))",
                      }}
                    >
                      <div className="w-6 h-6 rounded-md overflow-hidden bg-black/30 flex-shrink-0 flex items-center justify-center">
                        {p.image_url ? (
                          <img
                            src={p.image_url}
                            className="w-full h-full object-cover"
                            alt=""
                          />
                        ) : (
                          <PackageIcon size={11} className="text-white/40" />
                        )}
                      </div>
                      <span
                        className={cn(
                          "text-xs font-semibold whitespace-nowrap",
                          active ? "text-white" : "text-white/60",
                        )}
                      >
                        {p.name}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* Step 1 — Dynamic account fields from product.required_fields */}
          {accountRequired && (
            <div>
              <Step
                n={1}
                title={requiredFields.length === 1 ? "Куда зачислить?" : "Реквизиты"}
                sub={fillingHint}
              />
              {prefilled && (
                <div className="mb-2.5 flex items-center justify-between gap-2 rounded-2xl px-3 py-2"
                  style={{
                    background: "hsl(var(--primary) / 0.08)",
                    border: "1px solid hsl(var(--primary) / 0.25)",
                  }}
                >
                  <p className="text-[12px] text-white/75 leading-snug">
                    Используем данные с прошлого заказа
                  </p>
                  <button
                    type="button"
                    onClick={clearPrefilled}
                    className="text-[11px] font-semibold transition-opacity active:opacity-70 whitespace-nowrap"
                    style={{ color: "hsl(var(--primary))" }}
                  >
                    Изменить
                  </button>
                </div>
              )}
              <DynamicFields
                fields={requiredFields}
                values={fulfillment}
                onChange={(key, value) => {
                  setFulfillment((prev) => ({ ...prev, [key]: value }));
                  // Manual edit dismisses the chip — user is explicitly
                  // overriding the cached value.
                  if (prefilled) setPrefilled(false);
                }}
              />
            </div>
          )}

          {/* Step 2 — Packages */}
          <div>
            <Step
              n={accountRequired ? 2 : 1}
              title="Сколько пополнить?"
              sub="Зачисление обычно в течение пары минут"
            />

            {productQuery.isLoading && <PackagesSkeleton />}
            {!productQuery.isLoading && packages.length === 0 && (
              <p className="rounded-2xl border border-dashed border-white/10 p-6 text-center text-sm text-white/40">
                У этого продукта пока нет активных позиций. Загляни позже.
              </p>
            )}
            {packages.length > 0 && (
              <div className="grid grid-cols-2 gap-2.5">
                {packages.map((pkg) => (
                  <PackageCard
                    key={pkg.id}
                    pkg={pkg}
                    active={selectedPkg === pkg.id}
                    fallbackImage={productImage}
                    onSelect={() => setSelectedPkg(pkg.id)}
                  />
                ))}
              </div>
            )}
          </div>

          {/* Step 3 — Payment */}
          <div>
            <Step
              n={accountRequired ? 3 : 2}
              title="Способ оплаты"
              sub="Безопасно, без передачи карт"
            />

            <div className="grid grid-cols-4 gap-2 mb-3">
              {PAYMENT_METHODS.map((m) => {
                const active = paymentMethod === m.id;
                const Icon = m.icon;
                return (
                  <button
                    key={m.id}
                    onClick={() => setPaymentMethod(m.id)}
                    className="relative flex flex-col items-center gap-1 py-3 rounded-2xl transition-all duration-150"
                    style={{
                      background: active ? "hsl(228 32% 22%)" : "hsl(228 32% 16%)",
                      border: active
                        ? "1.5px solid hsl(var(--primary) / 0.8)"
                        : "1.5px solid hsl(var(--border))",
                    }}
                    data-testid={`btn-pay-${m.id}`}
                  >
                    {active && (
                      <div
                        className="absolute top-1.5 right-1.5 w-4 h-4 rounded-full flex items-center justify-center"
                        style={{ background: "hsl(var(--primary))" }}
                      >
                        <Check size={9} strokeWidth={3} className="text-black" />
                      </div>
                    )}
                    <Icon
                      size={18}
                      className={active ? "text-primary" : "text-white/40"}
                    />
                    <span
                      className={cn(
                        "text-[11px] font-bold leading-none",
                        active ? "text-white" : "text-white/50",
                      )}
                    >
                      {m.name}
                    </span>
                  </button>
                );
              })}
            </div>

          </div>

          {/* Trust items */}
          <div className="space-y-2.5 pt-1">
            {[
              {
                icon: ShieldCheck,
                text: accountRequired
                  ? "Без передачи пароля — только публичные данные аккаунта"
                  : "Шифрованные платежи и безопасная выдача кодов",
              },
              {
                icon: RotateCcw,
                text: "Не пришло за 5 минут — оформим возврат",
              },
            ].map(({ icon: Icon, text }, i) => (
              <div key={i} className="flex items-center gap-2.5">
                <Icon size={14} className="text-white/25 flex-shrink-0" />
                <span className="text-white/35 text-xs">{text}</span>
              </div>
            ))}
          </div>

          {/* Order summary */}
          {activePkg && (
            <motion.div
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex items-center gap-3 p-3 rounded-2xl"
              style={{
                background: "hsl(228 32% 16%)",
                border: "1px solid hsl(var(--border))",
              }}
            >
              <PackageThumb pkg={activePkg} fallback={productImage ?? game.appIcon ?? null} />
              <div className="flex-1 min-w-0">
                <p className="text-white font-bold text-sm line-clamp-1">
                  {activePkg.label} · {game.name}
                </p>
                <p className="text-white/40 text-xs mt-0.5 line-clamp-1">
                  {accountRequired
                    ? missingFieldKey
                      ? "Заполните реквизиты выше"
                      : "Реквизиты заполнены"
                    : "Получите код после оплаты"}
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
        {/* Settlement disclaimer — only shown when the gateway will charge
            in a currency different from the displayed one. Keeps the CTA
            honest without forcing a live FX preview. */}
        {insideTelegram &&
          activePkg &&
          ACQUIRER_BY_METHOD[paymentMethod] &&
          ACQUIRER_BY_METHOD[paymentMethod]!.currency !== priceCode && (
            <p
              className="mb-2 text-center text-[11px] text-white/45"
              role="note"
            >
              Списание в {ACQUIRER_BY_METHOD[paymentMethod]!.currency} через{" "}
              {ACQUIRER_BY_METHOD[paymentMethod]!.label} по курсу банка
            </p>
          )}
        {!insideTelegram && TELEGRAM_DEEP_LINK ? (
          <motion.a
            whileTap={{ scale: 0.97 }}
            href={TELEGRAM_DEEP_LINK}
            className="w-full py-4 rounded-2xl text-base font-black tracking-wide flex items-center justify-center gap-2 transition-all"
            style={{
              background: "hsl(var(--primary))",
              color: "#000",
              boxShadow: "0 0 24px hsl(var(--primary) / 0.35)",
            }}
          >
            <Send size={16} />
            Открыть в Telegram
          </motion.a>
        ) : (
          <motion.button
            whileTap={{ scale: 0.97 }}
            onClick={handlePayment}
            disabled={isProcessing || !activePkg || !insideTelegram}
            className="w-full py-4 rounded-2xl text-base font-black tracking-wide flex items-center justify-center gap-2 transition-all"
            style={{
              background:
                isProcessing || !activePkg || !insideTelegram
                  ? "hsl(var(--primary) / 0.45)"
                  : "hsl(var(--primary))",
              color: "#000",
              boxShadow:
                isProcessing || !activePkg || !insideTelegram
                  ? "none"
                  : "0 0 24px hsl(var(--primary) / 0.35)",
            }}
            data-testid="btn-pay"
          >
            {isProcessing ? (
              "Обработка..."
            ) : !insideTelegram ? (
              "Доступно в Telegram"
            ) : (
              <>
                Пополнить за {finalPrice > 0 ? formatMoney(finalPrice, priceCode) : "—"}
                <ChevronRight size={18} strokeWidth={2.5} />
              </>
            )}
          </motion.button>
        )}
      </div>
    </>
  );
}

// ─── Package card ─────────────────────────────────────────────────────────────
function PackageCard({
  pkg,
  active,
  fallbackImage,
  onSelect,
}: {
  pkg: Package;
  active: boolean;
  fallbackImage: string | null;
  onSelect: () => void;
}) {
  return (
    <button
      onClick={onSelect}
      className="relative text-left p-3.5 rounded-2xl transition-all duration-150"
      style={{
        background: active ? "hsl(228 32% 22%)" : "hsl(228 32% 16%)",
        border: active
          ? "1.5px solid hsl(var(--primary) / 0.8)"
          : "1.5px solid hsl(var(--border))",
        boxShadow: active ? "0 0 0 3px hsl(var(--primary) / 0.1)" : "none",
      }}
      data-testid={`btn-pkg-${pkg.id}`}
    >
      {pkg.badge && (
        <div
          className="absolute -top-2 left-3 px-2 py-0.5 rounded-md text-[9px] font-black tracking-wider"
          style={{ background: pkg.badge.color, color: "#fff" }}
        >
          {pkg.badge.label}
        </div>
      )}

      {active && (
        <div
          className="absolute top-2.5 right-2.5 w-5 h-5 rounded-full flex items-center justify-center"
          style={{ background: "hsl(var(--primary))" }}
        >
          <Check size={11} strokeWidth={3} className="text-black" />
        </div>
      )}

      <div className="flex items-center gap-2 mb-1.5">
        <PackageThumb pkg={pkg} fallback={fallbackImage} />
        <span className="text-white font-black text-lg leading-none">
          {pkg.amount > 0 ? pkg.amount.toLocaleString("ru") : pkg.label}
        </span>
      </div>

      {pkg.region && pkg.region !== "GLOBAL" && (
        <p className="text-white/40 text-[11px] mb-2">регион {pkg.region}</p>
      )}

      <p className="text-white font-bold text-sm">
        {formatMoney(pkg.price, pkg.priceCode)}
      </p>
    </button>
  );
}

function PackageThumb({
  pkg,
  fallback,
}: {
  pkg: Package;
  fallback: string | null;
}) {
  const src = pkg.imageUrl ?? fallback;
  if (src) {
    return (
      <div className="w-9 h-9 rounded-xl overflow-hidden bg-black/30 flex-shrink-0">
        <img src={src} className="w-full h-full object-cover" alt={pkg.label} />
      </div>
    );
  }
  // No image — show a small chip with whatever non-numeric part of the
  // denomination we have (e.g. "UC", "VP", "1 мес").
  const tag = pkg.label.replace(/^[\s\d.,]+/, "").trim() || "—";
  return (
    <div
      className="w-9 h-9 rounded-xl flex items-center justify-center text-[10px] font-black text-black"
      style={{ background: "hsl(var(--primary))" }}
    >
      {tag.slice(0, 4).toUpperCase()}
    </div>
  );
}

// ─── Loading skeletons ────────────────────────────────────────────────────────
function PageSkeleton({ onBack }: { onBack: () => void }) {
  return (
    <div className="pb-32">
      <div className="relative h-56 overflow-hidden bg-gradient-to-br from-slate-800 to-slate-950">
        <div className="absolute top-12 left-4 z-10">
          <button
            onClick={onBack}
            className="w-9 h-9 rounded-full bg-black/50 backdrop-blur-md border border-white/10 flex items-center justify-center"
            aria-label="Назад"
          >
            <ArrowLeft size={16} className="text-white" />
          </button>
        </div>
      </div>
      <div className="px-4 pt-5 space-y-4">
        <Skeleton className="h-12 w-full" />
        <PackagesSkeleton />
      </div>
    </div>
  );
}

function PackagesSkeleton() {
  return (
    <div className="grid grid-cols-2 gap-2.5">
      {[0, 1, 2, 3].map((i) => (
        <Skeleton key={i} className="h-24 rounded-2xl" />
      ))}
    </div>
  );
}
