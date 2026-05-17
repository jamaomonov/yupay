/**
 * Order success / status page.
 *
 * Mounted at ``/order/:id``. Drives the post-checkout journey:
 *
 *   pending_payment ─► paid ─► fulfilling ─► delivered  → show codes
 *                                       └─► cancelled / expired → show error
 *
 * Polls ``useOrder`` while the order is in motion and surfaces delivery
 * artifacts (voucher codes, receipts, license keys) the moment they appear.
 */

import { useEffect, useMemo } from "react";
import { useLocation, useParams, Link } from "wouter";
import { motion, AnimatePresence } from "framer-motion";
import {
  ArrowLeft,
  CheckCircle2,
  Copy,
  Loader2,
  Receipt,
  ShoppingBag,
  Sparkles,
  XCircle,
} from "lucide-react";

import { useToast } from "@/hooks/use-toast";
import {
  useDeliveries,
  useOrder,
  type ArtifactKind,
  type DeliveryOut,
  type OrderOut,
  type OrderStatus,
} from "@/lib/orders";

const PROCESSING: OrderStatus[] = [
  "pending_payment",
  "paid",
  "fulfilling",
  "fulfilled",
];

const TERMINAL_FAIL: OrderStatus[] = ["cancelled", "expired", "refunded"];

interface StageCopy {
  title: string;
  subtitle: string;
}

const STAGE: Record<OrderStatus, StageCopy> = {
  pending_payment: {
    title: "Ждём оплату",
    subtitle: "Платёж ещё не подтверждён.",
  },
  paid: {
    title: "Оплата получена",
    subtitle: "Передаём заказ в выдачу…",
  },
  fulfilling: {
    title: "Выдаём заказ",
    subtitle: "Резервируем код / отправляем на сервер.",
  },
  fulfilled: {
    title: "Почти готово",
    subtitle: "Завершаем оформление выдачи.",
  },
  delivered: {
    title: "Готово",
    subtitle: "Заказ выдан. Подробности ниже.",
  },
  cancelled: {
    title: "Заказ отменён",
    subtitle: "Деньги не списаны или были возвращены.",
  },
  expired: {
    title: "Истёк срок оплаты",
    subtitle: "Создайте новый заказ.",
  },
  refunded: {
    title: "Сделан возврат",
    subtitle: "Средства возвращены на исходный метод оплаты.",
  },
};

export default function OrderSuccess() {
  const params = useParams<{ id: string }>();
  const orderId = params.id;
  const [, setLocation] = useLocation();

  const orderQuery = useOrder(orderId);
  const order = orderQuery.data;

  const deliveriesQuery = useDeliveries(orderId, order?.status);
  const deliveries = deliveriesQuery.data ?? [];

  // Map delivered artifacts back to their items so we can render brand + denom
  // alongside each artifact block.
  const deliveriesByItem = useMemo(() => {
    const map: Record<string, DeliveryOut> = {};
    for (const d of deliveries) map[d.order_item_id] = d;
    return map;
  }, [deliveries]);

  if (!orderId) {
    return (
      <ErrorView
        title="Заказ не найден"
        subtitle="Попробуйте открыть страницу из истории."
        onHome={() => setLocation("/")}
      />
    );
  }

  if (orderQuery.isLoading || !order) {
    return <SkeletonView onBack={() => setLocation("/")} />;
  }

  const stage = STAGE[order.status];
  const isProcessing = PROCESSING.includes(order.status);
  const isDelivered = order.status === "delivered";
  const isFailed = TERMINAL_FAIL.includes(order.status);

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="space-y-4 pb-6"
    >
      <header className="px-4 pt-3 flex items-center gap-3">
        <button
          onClick={() => setLocation("/history")}
          className="size-9 rounded-xl flex items-center justify-center"
          style={{
            background: "hsl(var(--card))",
            border: "1.5px solid hsl(var(--border))",
          }}
          aria-label="Назад"
        >
          <ArrowLeft size={15} className="text-white/60" />
        </button>
        <div className="flex-1 min-w-0">
          <p className="text-[10px] uppercase tracking-[0.12em] text-white/35">
            Заказ
          </p>
          <p className="text-white text-sm font-mono leading-tight truncate">
            {order.id.slice(0, 8)}…
          </p>
        </div>
      </header>

      <StatusCard
        order={order}
        stage={stage}
        isProcessing={isProcessing}
        isDelivered={isDelivered}
        isFailed={isFailed}
      />

      {/* Per-item delivery artifacts. Always render so the user sees what's
          waiting on fulfilment vs what has landed already. */}
      <section className="px-4 space-y-2">
        {order.items.map((item) => (
          <ItemCard
            key={item.id}
            item={item}
            delivery={deliveriesByItem[item.id] ?? null}
            currency={order.currency}
          />
        ))}
      </section>

      <Summary order={order} />

      <div className="px-4 grid grid-cols-2 gap-3 pt-2">
        <Link
          href={order.items[0]?.display?.brand_slug ? `/topup/${order.items[0].display.brand_slug}` : "/"}
        >
          <ActionButton
            icon={<Sparkles size={15} />}
            label="Купить ещё"
            variant="primary"
          />
        </Link>
        <Link href="/history">
          <ActionButton
            icon={<Receipt size={15} />}
            label="История"
            variant="secondary"
          />
        </Link>
      </div>
    </motion.div>
  );
}

// ─── Status card ─────────────────────────────────────────────────────────────

function StatusCard({
  order,
  stage,
  isProcessing,
  isDelivered,
  isFailed,
}: {
  order: OrderOut;
  stage: StageCopy;
  isProcessing: boolean;
  isDelivered: boolean;
  isFailed: boolean;
}) {
  const tone = isDelivered
    ? "delivered"
    : isFailed
      ? "failed"
      : isProcessing
        ? "processing"
        : "neutral";

  const accent =
    tone === "delivered"
      ? "hsl(var(--primary))"
      : tone === "failed"
        ? "#ef4444"
        : "hsl(220 70% 60%)";

  return (
    <div className="px-4">
      <div
        className="relative overflow-hidden rounded-3xl p-5"
        style={{
          background: "hsl(228 32% 14%)",
          border: `1.5px solid ${tone === "delivered" ? "hsl(var(--primary) / 0.4)" : "hsl(var(--border))"}`,
        }}
      >
        {/* Glow */}
        <div
          className="pointer-events-none absolute -top-12 -right-12 size-44 rounded-full blur-3xl opacity-30"
          style={{ background: accent }}
        />

        <div className="relative flex items-center gap-3">
          <StatusIcon tone={tone} />
          <div className="min-w-0 flex-1">
            <h1 className="text-white text-lg font-bold leading-tight">
              {stage.title}
            </h1>
            <p className="text-white/55 text-xs mt-0.5">{stage.subtitle}</p>
          </div>
        </div>

        {/* Progress strip — only while in motion. */}
        {isProcessing && (
          <div className="relative mt-4 h-1 rounded-full bg-white/5 overflow-hidden">
            <motion.div
              className="absolute inset-y-0 left-0 w-1/3 rounded-full"
              style={{ background: accent }}
              animate={{ x: ["-100%", "300%"] }}
              transition={{
                duration: 1.6,
                repeat: Infinity,
                ease: "easeInOut",
              }}
            />
          </div>
        )}
      </div>
    </div>
  );
}

function StatusIcon({
  tone,
}: {
  tone: "delivered" | "failed" | "processing" | "neutral";
}) {
  if (tone === "delivered") {
    return (
      <motion.div
        initial={{ scale: 0.6, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ type: "spring", stiffness: 280, damping: 18 }}
        className="size-11 rounded-2xl flex items-center justify-center flex-shrink-0"
        style={{
          background:
            "linear-gradient(140deg, hsl(var(--primary)) 0%, hsl(84 100% 70%) 100%)",
          boxShadow: "0 8px 24px hsl(var(--primary) / 0.4)",
        }}
      >
        <CheckCircle2 size={22} strokeWidth={2.5} className="text-black" />
      </motion.div>
    );
  }
  if (tone === "failed") {
    return (
      <div
        className="size-11 rounded-2xl flex items-center justify-center flex-shrink-0"
        style={{ background: "rgba(239, 68, 68, 0.18)" }}
      >
        <XCircle size={22} className="text-red-400" />
      </div>
    );
  }
  return (
    <div
      className="size-11 rounded-2xl flex items-center justify-center flex-shrink-0"
      style={{ background: "rgba(255, 255, 255, 0.05)" }}
    >
      <Loader2 size={20} className="text-white/70 animate-spin" />
    </div>
  );
}

// ─── Per-item card ───────────────────────────────────────────────────────────

function ItemCard({
  item,
  delivery,
  currency,
}: {
  item: OrderOut["items"][number];
  delivery: DeliveryOut | null;
  currency: string;
}) {
  const display = item.display;
  const headline = display
    ? display.brand_name
      ? `${display.brand_name} · ${display.denomination ?? display.sku_code}`
      : `${display.product_name || display.product_slug} · ${display.denomination ?? display.sku_code}`
    : `SKU ${item.sku_id.slice(0, 8)}…`;

  const isTopUp = display?.product_kind === "top_up";

  return (
    <div
      className="rounded-2xl p-3.5"
      style={{
        background: "hsl(228 32% 14%)",
        border: "1px solid hsl(var(--border))",
      }}
    >
      <div className="flex items-center gap-3">
        {display?.image_url ? (
          <img
            src={display.image_url}
            className="size-11 rounded-xl object-cover flex-shrink-0"
            alt=""
          />
        ) : (
          <div
            className="size-11 rounded-xl flex items-center justify-center flex-shrink-0 text-sm font-bold text-white/40"
            style={{ background: "hsl(228 32% 19%)" }}
          >
            {display?.brand_name?.[0]?.toUpperCase() ?? "?"}
          </div>
        )}
        <div className="min-w-0 flex-1">
          <p className="text-white text-sm font-semibold leading-tight truncate">
            {headline}
          </p>
          <p className="text-white/40 text-[11px] mt-0.5 flex items-center gap-1.5">
            <span>
              {Number.parseFloat(item.unit_price_usd).toFixed(2)} USD
            </span>
            {item.qty > 1 && (
              <>
                <span>·</span>
                <span>×{item.qty}</span>
              </>
            )}
          </p>
        </div>
      </div>

      <AnimatePresence>
        {delivery ? (
          isTopUp ? (
            <TopUpReceipt
              delivery={delivery}
              fulfillmentData={item.fulfillment_data}
            />
          ) : (
            <ArtifactBlock delivery={delivery} />
          )
        ) : (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="mt-3 flex items-center gap-2 text-[11px] text-white/40"
          >
            <Loader2 size={12} className="animate-spin" />
            <span>{isTopUp ? "пополняем аккаунт…" : "ожидаем выдачу…"}</span>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ─── Top-up receipt ─────────────────────────────────────────────────────────
// For top-up products there is no code to deliver — the supplier credits the
// player's account directly. The receipt block surfaces:
//   * the fields the user entered at checkout (player_id, region, …) so they
//     can confirm we pushed UC to the right account;
//   * the supplier's order id, in case support needs it later.

const FIELD_LABEL: Record<string, string> = {
  player_id: "ID игрока",
  user_id: "ID пользователя",
  account_id: "Аккаунт",
  email: "Email",
  phone: "Телефон",
  region: "Регион",
  zone_id: "Zone ID",
  character: "Персонаж",
  nickname: "Никнейм",
};

function labelForField(key: string): string {
  return FIELD_LABEL[key] ?? key;
}

function TopUpReceipt({
  delivery,
  fulfillmentData,
}: {
  delivery: DeliveryOut;
  fulfillmentData: Record<string, unknown>;
}) {
  // Prefer the snapshot stored in the artifact (frozen at fulfilment time),
  // fall back to the live item.fulfillment_data if the supplier didn't echo
  // it back.
  const artifactSnapshot = isStringRecord(delivery.artifact.fulfillment_data)
    ? delivery.artifact.fulfillment_data
    : null;
  const fields = artifactSnapshot ?? fulfillmentData;
  const externalId =
    typeof delivery.artifact.external_id === "string"
      ? delivery.artifact.external_id
      : null;

  const entries = Object.entries(fields).filter(
    ([, v]) => typeof v === "string" && (v as string).trim().length > 0,
  ) as [string, string][];

  return (
    <motion.div
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      className="mt-3 space-y-2"
    >
      <div className="flex items-center gap-1.5">
        <span
          className="text-[10px] uppercase tracking-[0.12em] font-semibold"
          style={{ color: "hsl(var(--primary))" }}
        >
          Зачислено
        </span>
        <span className="text-white/25 text-[10px]">·</span>
        <span className="text-white/35 text-[10px]">
          {new Date(delivery.delivered_at).toLocaleString("ru", {
            day: "2-digit",
            month: "short",
            hour: "2-digit",
            minute: "2-digit",
          })}
        </span>
      </div>

      {entries.length > 0 && (
        <div
          className="rounded-xl p-3 space-y-1.5"
          style={{
            background: "hsl(228 32% 19%)",
            border: "1px solid hsl(var(--border))",
          }}
        >
          {entries.map(([key, value]) => (
            <div key={key} className="flex items-baseline justify-between gap-3 text-xs">
              <span className="text-white/50">{labelForField(key)}</span>
              <span className="text-white font-mono text-right truncate max-w-[60%]">
                {value}
              </span>
            </div>
          ))}
        </div>
      )}

      {externalId && (
        <p className="text-[10px] text-white/30 font-mono">
          № операции: {externalId}
        </p>
      )}
    </motion.div>
  );
}

function isStringRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

// ─── Artifact block ──────────────────────────────────────────────────────────

function ArtifactBlock({ delivery }: { delivery: DeliveryOut }) {
  const { toast } = useToast();

  const onCopy = async (value: string, label: string) => {
    try {
      await navigator.clipboard.writeText(value);
      toast({ title: `${label} скопирован` });
    } catch {
      toast({
        title: "Не удалось скопировать",
        description: "Выделите и скопируйте вручную",
        variant: "destructive",
      });
    }
  };

  const code = typeof delivery.artifact.code === "string" ? delivery.artifact.code : null;
  const key = typeof delivery.artifact.key === "string" ? delivery.artifact.key : null;
  const receipt =
    typeof delivery.artifact.external_id === "string"
      ? delivery.artifact.external_id
      : null;

  return (
    <motion.div
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      className="mt-3"
    >
      <div className="flex items-center gap-1.5 mb-1.5">
        <span
          className="text-[10px] uppercase tracking-[0.12em] font-semibold"
          style={{ color: "hsl(var(--primary))" }}
        >
          {labelForKind(delivery.artifact_kind)}
        </span>
        <span className="text-white/25 text-[10px]">·</span>
        <span className="text-white/35 text-[10px]">
          {new Date(delivery.delivered_at).toLocaleString("ru", {
            day: "2-digit",
            month: "short",
            hour: "2-digit",
            minute: "2-digit",
          })}
        </span>
      </div>

      {code && (
        <CopyableValue
          value={code}
          label="Код"
          onCopy={(v) => void onCopy(v, "Код")}
        />
      )}
      {!code && key && (
        <CopyableValue
          value={key}
          label="Ключ"
          onCopy={(v) => void onCopy(v, "Ключ")}
        />
      )}
      {!code && !key && receipt && (
        <div
          className="rounded-xl px-3 py-2.5 text-xs text-white/75 leading-snug"
          style={{
            background: "hsl(228 32% 19%)",
            border: "1px solid hsl(var(--border))",
          }}
        >
          <span className="text-white/45">Зачислено · </span>
          <span className="font-mono">{receipt}</span>
        </div>
      )}
      {!code && !key && !receipt && (
        <pre
          className="rounded-xl px-3 py-2.5 text-[11px] text-white/65 leading-snug whitespace-pre-wrap font-mono overflow-x-auto"
          style={{
            background: "hsl(228 32% 19%)",
            border: "1px solid hsl(var(--border))",
          }}
        >
          {JSON.stringify(delivery.artifact, null, 2)}
        </pre>
      )}
    </motion.div>
  );
}

function labelForKind(kind: ArtifactKind): string {
  switch (kind) {
    case "voucher_code":
      return "Ваучер";
    case "license_key":
      return "Лицензия";
    case "topup_receipt":
      return "Чек";
  }
}

function CopyableValue({
  value,
  label,
  onCopy,
}: {
  value: string;
  label: string;
  onCopy: (v: string) => void;
}) {
  return (
    <button
      onClick={() => onCopy(value)}
      className="group w-full text-left rounded-xl px-3 py-3 flex items-center gap-3 transition-colors active:scale-[0.99]"
      style={{
        background: "hsl(228 32% 19%)",
        border: "1.5px solid hsl(var(--primary) / 0.45)",
      }}
    >
      <div className="flex-1 min-w-0">
        <p className="text-white/40 text-[10px] uppercase tracking-wide">
          {label}
        </p>
        <p className="text-white text-sm font-mono mt-0.5 break-all">{value}</p>
      </div>
      <div
        className="size-8 rounded-lg flex items-center justify-center flex-shrink-0 transition-colors"
        style={{ background: "hsl(var(--primary) / 0.18)" }}
      >
        <Copy size={13} style={{ color: "hsl(var(--primary))" }} />
      </div>
    </button>
  );
}

// ─── Summary footer ─────────────────────────────────────────────────────────

function Summary({ order }: { order: OrderOut }) {
  return (
    <div className="px-4">
      <div
        className="rounded-2xl p-4 space-y-1.5 text-xs"
        style={{
          background: "hsl(228 32% 14%)",
          border: "1px solid hsl(var(--border))",
        }}
      >
        <Row
          label="Сумма"
          value={`${Number.parseFloat(order.total_charged).toLocaleString("ru", { maximumFractionDigits: 2 })} ${order.currency}`}
        />
        <Row label="Создан" value={fmtDate(order.created_at)} />
        {order.paid_at && <Row label="Оплачен" value={fmtDate(order.paid_at)} />}
        {order.delivered_at && (
          <Row label="Выдан" value={fmtDate(order.delivered_at)} />
        )}
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-white/45">{label}</span>
      <span className="text-white font-medium">{value}</span>
    </div>
  );
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleString("ru", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// ─── Action buttons ─────────────────────────────────────────────────────────

function ActionButton({
  icon,
  label,
  variant,
}: {
  icon: React.ReactNode;
  label: string;
  variant: "primary" | "secondary";
}) {
  const primary = variant === "primary";
  return (
    <button
      type="button"
      className="w-full rounded-2xl py-3 flex items-center justify-center gap-2 text-sm font-semibold transition-transform active:scale-[0.97]"
      style={{
        background: primary ? "hsl(var(--primary))" : "hsl(228 32% 16%)",
        color: primary ? "hsl(var(--primary-foreground))" : "rgba(255,255,255,0.85)",
        border: primary
          ? "1.5px solid hsl(var(--primary))"
          : "1.5px solid hsl(var(--border))",
      }}
    >
      {icon}
      <span>{label}</span>
    </button>
  );
}

// ─── Skeleton + error ───────────────────────────────────────────────────────

function SkeletonView({ onBack }: { onBack: () => void }) {
  return (
    <div className="space-y-4 pb-6">
      <header className="px-4 pt-3 flex items-center gap-3">
        <button
          onClick={onBack}
          className="size-9 rounded-xl flex items-center justify-center"
          style={{
            background: "hsl(var(--card))",
            border: "1.5px solid hsl(var(--border))",
          }}
        >
          <ArrowLeft size={15} className="text-white/60" />
        </button>
        <div
          className="flex-1 h-3 rounded animate-pulse"
          style={{ background: "hsl(228 32% 18%)" }}
        />
      </header>
      <div className="px-4">
        <div
          className="h-28 rounded-3xl animate-pulse"
          style={{ background: "hsl(228 32% 14%)" }}
        />
      </div>
      <div className="px-4 space-y-2">
        {Array.from({ length: 2 }).map((_, i) => (
          <div
            key={i}
            className="h-20 rounded-2xl animate-pulse"
            style={{ background: "hsl(228 32% 14%)" }}
          />
        ))}
      </div>
    </div>
  );
}

function ErrorView({
  title,
  subtitle,
  onHome,
}: {
  title: string;
  subtitle: string;
  onHome: () => void;
}) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-16 gap-4 text-center">
      <ShoppingBag size={40} className="text-white/20" />
      <div>
        <p className="text-white font-semibold">{title}</p>
        <p className="text-white/45 text-xs mt-1">{subtitle}</p>
      </div>
      <button
        onClick={onHome}
        className="px-5 py-2 rounded-full text-sm font-semibold"
        style={{
          background: "hsl(var(--primary))",
          color: "hsl(var(--primary-foreground))",
        }}
      >
        На главную
      </button>
    </div>
  );
}

// Auto-scroll to top when the page is opened by a router change. The wouter
// router preserves scroll between routes by default, which makes the success
// page feel "stale" if the user was scrolled deep on TopUp.
export function useScrollToTopOnMount(): void {
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "instant" as ScrollBehavior });
  }, []);
}
