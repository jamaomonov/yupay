"use client";

import { formatMoney } from "@yupay/utils";
import { ArrowUpRight, Check, Loader2 } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";

import type { FormField, ProductDetail, SkuOut } from "@/lib/catalog";

import { useAuth } from "@/lib/auth";
import { buttonStyles } from "@/lib/button";
import { getAccessToken } from "@/lib/client";
import { canCheck, IDLE, runPlayerCheck, type CheckState } from "@/lib/player-check-state";
import { formatUzs } from "@/lib/seo";

const API = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");

interface Method {
  id: string;
  name: string;
  provider: string;
  icon: string;
  w: number;
  h: number;
}

/** In-scope acquirers (UZ rails + USDT). Real gateways are still stubs in dev,
 * so checkout falls back to the live `mock` provider when the chosen one isn't
 * available yet — the UI stays honest while the flow works end-to-end. */
const METHODS: Method[] = [
  { id: "click", name: "Click", provider: "click", icon: "/payment/click.svg", w: 157, h: 40 },
  { id: "payme", name: "Payme", provider: "payme", icon: "/payment/payme.png", w: 454, h: 179 },
  { id: "uzum", name: "Uzum", provider: "uzum", icon: "/payment/uzum.png", w: 506, h: 148 },
  { id: "usdt", name: "USDT", provider: "crypto", icon: "/payment/usdt.png", w: 2000, h: 2000 },
];

function skuPrice(locale: string, sku: SkuOut): string {
  if (sku.display_price) return formatUzs(locale, Math.round(Number(sku.display_price.amount)));
  return formatMoney(sku.price_usd, "USD", locale);
}

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

/**
 * Advisory player-id lookup button rendered next to a checkable field
 * (`f.check` set on the catalog schema). Owns its own check state via the
 * shared `player-check-state` unit so `PurchasePanel` stays thin glue; a
 * failed lookup never blocks checkout — it just shows a muted note.
 */
function PlayerCheckControl({
  productId,
  value,
  pattern,
  serverId,
  t,
}: {
  productId: string;
  value: string;
  pattern?: string | null | undefined;
  serverId: string | null;
  t: (key: string, values?: Record<string, string>) => string;
}) {
  const [state, setState] = useState<CheckState>(IDLE);
  useEffect(() => {
    setState(IDLE);
  }, [value]);
  const enabled = canCheck(value, pattern);

  async function onCheck() {
    setState({ phase: "loading" });
    setState(await runPlayerCheck(productId, { playerId: value, serverId }));
  }

  return (
    <div className="mt-1.5 flex items-center gap-2">
      <button
        type="button"
        disabled={!enabled || state.phase === "loading"}
        onClick={() => void onCheck()}
        className={buttonStyles({ variant: "ghost", size: "xs", className: "h-8 px-3 text-[12px]" })}
      >
        {state.phase === "loading" ? t("checking") : t("check")}
      </button>
      {state.phase === "done" &&
        (state.result.valid ? (
          <span className="text-primary truncate text-[12px] font-medium">
            {t("checkNickname", { name: state.result.name ?? "" })}
          </span>
        ) : (
          <span className="text-tx-dim truncate text-[12px] font-medium">{t("checkFailed")}</span>
        ))}
    </div>
  );
}

export function PurchasePanel({ products, locale }: { products: ProductDetail[]; locale: string }) {
  const t = useTranslations("web.store");
  const { user } = useAuth();
  const firstSku = products[0]?.skus[0]?.id;
  const [skuId, setSkuId] = useState<string | undefined>(firstSku);
  const [form, setForm] = useState<Record<string, string>>({});
  const [email, setEmail] = useState("");
  const [methodId, setMethodId] = useState<string>(METHODS[0]?.id ?? "click");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<{
    orderId: string;
    intentUrl: string | null;
    trackHref: string;
  } | null>(null);
  // The mobile sticky pay bar scrolls here when the form isn't complete yet.
  const asideRef = useRef<HTMLElement>(null);

  let selSku: SkuOut | undefined;
  let selProduct: ProductDetail | undefined;
  for (const p of products) {
    const s = p.skus.find((x) => x.id === skuId);
    if (s) {
      selSku = s;
      selProduct = p;
      break;
    }
  }
  const fields: FormField[] = selProduct?.required_fields ?? [];
  const label = (m: Record<string, string> | null | undefined): string =>
    (m && (m[locale] ?? m.ru ?? Object.values(m)[0])) ?? "";

  const emailOk = EMAIL_RE.test(email);
  const fieldsOk = fields.every((f) => !f.required || (form[f.key]?.trim() ?? "") !== "");
  // Logged-in users don't need to supply an email — the account email is used server-side.
  const canPay =
    Boolean(selSku) && (user !== null || emailOk) && fieldsOk && Boolean(methodId) && !loading;
  // Tell the user *why* the pay button is inactive instead of leaving a dimmed
  // button with no explanation.
  const payHint = !selSku
    ? t("selectPack")
    : !user && !emailOk
      ? t("payHintEmail")
      : !fieldsOk
        ? t("payHintFields")
        : null;

  async function pay() {
    if (!selSku || !canPay) return;
    setLoading(true);
    setError(null);
    try {
      const providers = await fetch(`${API}/api/v1/payments/providers`)
        .then((r) => r.json() as Promise<{ providers: string[] }>)
        .catch(() => ({ providers: [] as string[] }));
      const wanted = METHODS.find((m) => m.id === methodId)?.provider ?? "mock";
      const provider = providers.providers.includes(wanted)
        ? wanted
        : providers.providers.includes("mock")
          ? "mock"
          : wanted;

      const token = getAccessToken();
      const isLoggedIn = user !== null && token !== null;

      let auth: { Authorization: string };
      let emailSuffix: string;

      if (isLoggedIn) {
        // ── Logged-in path: use Bearer token; no guest step needed ──
        auth = { Authorization: `Bearer ${token}` };
        emailSuffix = "";
      } else {
        // ── Guest path: obtain a guest token first (unchanged behavior) ──
        const g = await fetch(`${API}/api/v1/auth/guest`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email }),
        });
        if (!g.ok) throw new Error("guest");
        const { access_token } = (await g.json()) as { access_token: string };
        auth = { Authorization: `Guest ${access_token}` };
        emailSuffix = `?email=${encodeURIComponent(email)}`;
      }

      const orderBody = isLoggedIn
        ? { currency: "UZS", items: [{ sku_id: selSku.id, qty: 1, fulfillment_data: form }] }
        : {
            currency: "UZS",
            guest_email: email,
            items: [{ sku_id: selSku.id, qty: 1, fulfillment_data: form }],
          };

      const ord = await fetch(`${API}/api/v1/orders`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Accept-Language": locale,
          "Idempotency-Key": crypto.randomUUID(),
          ...auth,
        },
        body: JSON.stringify(orderBody),
      });
      if (!ord.ok) throw new Error("order");
      const order = (await ord.json()) as { id: string };

      const intentsUrl = isLoggedIn
        ? `${API}/api/v1/payments/intents`
        : `${API}/api/v1/payments/intents?email=${encodeURIComponent(email)}`;

      const intentRes = await fetch(intentsUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": crypto.randomUUID(),
          ...auth,
        },
        body: JSON.stringify({ order_id: order.id, provider }),
      });
      if (!intentRes.ok) throw new Error("intent");
      const intent = (await intentRes.json()) as { intent_url: string | null };
      const trackHref = `/${locale}/orders/${order.id}${emailSuffix}`;
      if (intent.intent_url && provider !== "mock") {
        // Real acquirer → go straight to the hosted payment page. The dev `mock`
        // provider returns a non-resolvable URL, so we keep its clickable
        // confirmation screen instead of redirecting into a dead end.
        window.location.href = intent.intent_url;
        return;
      }
      setDone({ orderId: order.id, intentUrl: intent.intent_url, trackHref });
    } catch {
      setError(t("payError"));
    } finally {
      setLoading(false);
    }
  }

  if (done) {
    return (
      <div className="border-primary/30 rounded-2xl border bg-[linear-gradient(135deg,hsl(var(--primary)/0.08),hsl(var(--card)))] p-8 text-center">
        <span className="bg-primary mx-auto flex h-14 w-14 items-center justify-center rounded-full">
          <Check size={28} strokeWidth={3} className="text-primary-foreground" />
        </span>
        <h2 className="font-display mt-5 text-2xl font-bold tracking-[-0.02em]">
          {t("successTitle")}
        </h2>
        <p className="text-tx-mute mx-auto mt-2 max-w-[420px] text-[15px] leading-relaxed">
          {t("successNote")}
        </p>
        <p className="text-tx-dim mt-3 font-mono text-xs">
          {t("orderLabel")} #{done.orderId.slice(0, 8)}
        </p>
        {done.intentUrl && (
          <a
            href={done.intentUrl}
            className={buttonStyles({ size: "lg", className: "mx-auto mt-6 w-full max-w-[320px]" })}
          >
            {t("goToPay")}
            <ArrowUpRight size={17} strokeWidth={2.6} />
          </a>
        )}
        <Link
          href={done.trackHref}
          className={buttonStyles({
            variant: "ghost",
            size: "lg",
            className: "mx-auto mt-3 w-full max-w-[320px]",
          })}
        >
          {t("orderStatus")}
          <ArrowUpRight size={17} strokeWidth={2.6} />
        </Link>
      </div>
    );
  }

  return (
    <>
      <div className="grid grid-cols-1 gap-8 pb-24 lg:grid-cols-[1.5fr_1fr] lg:pb-0">
        {/* selection + fields */}
        <div>
          <h2 className="font-display text-xl font-bold tracking-[-0.02em]">{t("packsTitle")}</h2>
          {products.map((product) => (
            <div key={product.id} className="mt-5">
              {products.length > 1 && (
                <div className="text-tx-mute mb-3 text-sm font-semibold">{product.name}</div>
              )}
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                {product.skus.map((sku) => {
                  const active = sku.id === skuId;
                  const img = sku.image_url ?? product.image_url;
                  return (
                    <button
                      key={sku.id}
                      type="button"
                      aria-pressed={active}
                      onClick={() => {
                        setSkuId(sku.id);
                      }}
                      className={`focus-visible:ring-primary focus-visible:ring-offset-bg flex flex-col items-start gap-2 rounded-[14px] border p-3 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 ${
                        active
                          ? "border-primary bg-primary/10"
                          : "border-border bg-card hover:border-border-2"
                      }`}
                    >
                      <span className="relative h-12 w-12 overflow-hidden rounded-[10px]">
                        {img && (
                          <Image
                            src={img}
                            alt=""
                            fill
                            unoptimized
                            sizes="48px"
                            className="object-contain"
                          />
                        )}
                      </span>
                      <span className="font-display text-[15px] font-bold leading-tight tracking-[-0.01em]">
                        {sku.denomination ?? sku.sku_code}
                      </span>
                      <span className="text-tx-mute font-mono text-[12px]">
                        {skuPrice(locale, sku)}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </div>

        {/* summary + payment + pay */}
        <aside ref={asideRef} className="scroll-mt-[88px] lg:sticky lg:top-[100px] lg:self-start">
          <div className="border-border rounded-xl border bg-[linear-gradient(135deg,hsl(var(--card)),hsl(var(--bg)))] p-6">
            <h2 className="font-display text-lg font-bold tracking-[-0.02em]">
              {t("summaryTitle")}
            </h2>

            <div className="border-border/70 mt-4 flex items-center justify-between border-b pb-4">
              {selSku ? (
                <>
                  <span className="text-[15px] font-semibold">
                    {selSku.denomination ?? selSku.sku_code}
                  </span>
                  <span className="font-display text-lg font-bold">{skuPrice(locale, selSku)}</span>
                </>
              ) : (
                <span className="text-tx-mute text-sm">{t("selectPack")}</span>
              )}
            </div>

            <label className="mt-5 block">
              <span className="text-tx-mute mb-1.5 block text-[13px] font-semibold">
                {t("emailLabel")} <span className="text-primary">*</span>
              </span>
              <input
                type="email"
                inputMode="email"
                autoComplete="email"
                required
                aria-required="true"
                value={email}
                placeholder={t("emailPlaceholder")}
                onChange={(e) => {
                  setEmail(e.target.value);
                }}
                className="border-border bg-card focus:border-primary h-[46px] w-full rounded-[12px] border px-3.5 text-[15px] outline-none transition"
              />
            </label>

            {fields.length > 0 && (
              <div className="mt-5 flex flex-col gap-4">
                {fields.map((f) => (
                  <label key={f.key} className="block">
                    <span className="text-tx-mute mb-1.5 block text-[13px] font-semibold">
                      {label(f.label)}
                      {f.required && <span className="text-primary"> *</span>}
                    </span>
                    {f.type === "select" ? (
                      <select
                        required={f.required}
                        aria-required={f.required}
                        value={form[f.key] ?? ""}
                        onChange={(e) => {
                          setForm((s) => ({ ...s, [f.key]: e.target.value }));
                        }}
                        className="border-border bg-card focus:border-primary h-[46px] w-full rounded-[12px] border px-3.5 text-[15px] outline-none transition"
                      >
                        <option value="">—</option>
                        {f.options?.map((o) => (
                          <option key={o.value} value={o.value}>
                            {label(o.label)}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <input
                        type={f.type === "number" ? "text" : f.type}
                        inputMode={f.type === "number" ? "numeric" : undefined}
                        required={f.required}
                        aria-required={f.required}
                        value={form[f.key] ?? ""}
                        placeholder={label(f.placeholder)}
                        onChange={(e) => {
                          setForm((s) => ({ ...s, [f.key]: e.target.value }));
                        }}
                        className="border-border bg-card focus:border-primary h-[46px] w-full rounded-[12px] border px-3.5 text-[15px] outline-none transition"
                      />
                    )}
                    {f.help_text && (
                      <span className="text-tx-dim mt-1 block text-xs">{label(f.help_text)}</span>
                    )}
                    {f.check && selProduct && (
                      <PlayerCheckControl
                        productId={selProduct.id}
                        value={form[f.key] ?? ""}
                        pattern={f.pattern}
                        serverId={
                          f.check.server_field ? (form[f.check.server_field] ?? null) : null
                        }
                        t={t}
                      />
                    )}
                  </label>
                ))}
              </div>
            )}

            <div className="mt-5">
              <span className="text-tx-mute mb-2 block text-[13px] font-semibold">
                {t("paymentTitle")}
              </span>
              <div className="grid grid-cols-2 gap-2">
                {METHODS.map((m) => {
                  const active = m.id === methodId;
                  return (
                    <button
                      key={m.id}
                      type="button"
                      aria-label={m.name}
                      aria-pressed={active}
                      onClick={() => {
                        setMethodId(m.id);
                      }}
                      className={`focus-visible:ring-primary focus-visible:ring-offset-bg flex items-center justify-center rounded-[12px] border px-3 py-3 transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 ${
                        active
                          ? "border-primary bg-primary/10"
                          : "border-border bg-card hover:border-border-2"
                      }`}
                    >
                      <Image
                        src={m.icon}
                        alt={m.name}
                        title={m.name}
                        width={m.w}
                        height={m.h}
                        unoptimized
                        style={{ width: "auto", height: 20 }}
                        className="object-contain"
                      />
                    </button>
                  );
                })}
              </div>
            </div>

            <button
              type="button"
              disabled={!canPay}
              onClick={() => void pay()}
              className={buttonStyles({ size: "lg", className: "mt-6 w-full" })}
            >
              {loading ? (
                <Loader2 size={18} className="animate-spin" />
              ) : (
                <>
                  {t("pay")}
                  {selSku && ` · ${skuPrice(locale, selSku)}`}
                </>
              )}
            </button>

            {!canPay && !loading && !error && payHint && (
              <p className="text-tx-dim mt-2.5 text-center text-[12px]">{payHint}</p>
            )}

            {error && <p className="mt-3 text-center text-[13px] text-[#FF6B6B]">{error}</p>}

            <div className="border-border/70 text-tx-mute mt-5 flex items-start gap-2.5 border-t pt-5 text-[12px] leading-relaxed">
              {t("securityNote")}
            </div>
          </div>
        </aside>
      </div>

      {/* Mobile sticky checkout bar — brings the total + pay CTA up so the
          customer doesn't scroll past the whole form. Pays when ready, else
          jumps to the form (which shows what's still missing). */}
      {selSku && (
        <div className="border-border bg-bg/95 fixed inset-x-0 bottom-0 z-40 border-t px-4 py-3 backdrop-blur-xl lg:hidden">
          <div className="mx-auto flex max-w-[1200px] items-center justify-between gap-4">
            <div className="min-w-0">
              <div className="text-tx-mute text-[11px] font-semibold">{t("summaryTitle")}</div>
              <div className="font-display truncate text-lg font-bold leading-tight">
                {skuPrice(locale, selSku)}
              </div>
            </div>
            <button
              type="button"
              onClick={() => {
                if (canPay) void pay();
                else asideRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
              }}
              className={buttonStyles({ size: "lg", className: "shrink-0" })}
            >
              {loading ? <Loader2 size={18} className="animate-spin" /> : t("pay")}
            </button>
          </div>
        </div>
      )}
    </>
  );
}
