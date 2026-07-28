"use client";

import { formatMoney } from "@yupay/utils";
import { ArrowUpRight, Check, Info, Loader2, X } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";

import type { FormField, ProductDetail, SkuOut } from "@/lib/catalog";

import { useAuth } from "@/lib/auth";
import { buttonStyles } from "@/lib/button";
import { getAccessToken } from "@/lib/client";
import { canCheck, IDLE, runPlayerCheck, type CheckState } from "@/lib/player-check-state";
import { formatUzs, pathFor } from "@/lib/seo";
import { amountError, parseAmount } from "@/lib/variable-amount";

const API = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");

interface Method {
  id: string;
  name: string;
  provider: string;
  icon: string;
  w: number;
  h: number;
}

/** In-scope acquirers (UZ rails). Real gateways are still stubs in dev,
 * so checkout falls back to the live `mock` provider when the chosen one isn't
 * available yet — the UI stays honest while the flow works end-to-end. */
const METHODS: Method[] = [
  { id: "click", name: "Click", provider: "click", icon: "/payment/click.svg", w: 157, h: 40 },
  { id: "payme", name: "Payme", provider: "payme", icon: "/payment/payme.png", w: 454, h: 179 },
  { id: "uzum", name: "Uzum", provider: "uzum", icon: "/payment/uzum.png", w: 506, h: 148 },
];

/** A fixed-price SKU's display price. Never call this for a variable-amount
 *  SKU — its `display_price` is the rate for ONE dollar, not a total, and
 *  its `price_usd` is a `1`-placeholder; use `selectedPriceLabel` instead. */
function skuPrice(locale: string, sku: SkuOut): string {
  if (sku.display_price) return formatUzs(locale, Math.round(Number(sku.display_price.amount)));
  return formatMoney(sku.price_usd, "USD", locale);
}

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

/**
 * The checkable player-id field: a pill input paired with an advisory
 * nickname lookup (`f.check` on the catalog schema). Owns its own check state
 * via the shared `player-check-state` unit; the value still flows up through
 * `onChange` so checkout gating is unchanged. A resolved id collapses the
 * input into a confirmation pill; a wrong id or a lookup fault never blocks
 * checkout — the customer can pay regardless.
 */
function CheckablePlayerField({
  productId,
  label,
  value,
  onChange,
  pattern,
  required,
  serverId,
  help,
  t,
}: {
  productId: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  pattern?: string | null | undefined;
  required: boolean;
  serverId: string | null;
  help: string | null;
  t: (key: string, values?: Record<string, string>) => string;
}) {
  const [state, setState] = useState<CheckState>(IDLE);
  const [helpOpen, setHelpOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    setState(IDLE);
  }, [value]);
  const enabled = canCheck(value, pattern);

  async function onCheck() {
    setState({ phase: "loading" });
    setState(await runPlayerCheck(productId, { playerId: value, serverId }));
  }
  function edit() {
    setState(IDLE);
    requestAnimationFrame(() => inputRef.current?.focus());
  }

  const done = state.phase === "done" ? state.result : null;

  // Confirmed-hit pill — nickname + the id it resolved to.
  if (done?.status === "valid") {
    return (
      <div>
        <FieldLabel label={label} required={required} />
        <div className="flex items-center gap-2.5 rounded-[12px] border border-emerald-500/40 bg-emerald-500/[0.06] py-1.5 pl-1.5 pr-4">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-400">
            <Check size={17} strokeWidth={3} />
          </span>
          <div className="min-w-0 flex-1 leading-tight">
            <div className="truncate text-[14px] font-bold">{done.name}</div>
            <div className="truncate font-mono text-[12px] text-emerald-400">{value}</div>
          </div>
          <button
            type="button"
            onClick={edit}
            className="text-tx-dim hover:text-tx-mute shrink-0 text-[13px] font-medium transition"
          >
            {t("checkEdit")}
          </button>
        </div>
      </div>
    );
  }

  // Wrong id — the customer mistyped it; offer to fix it, never block.
  if (done?.status === "invalid") {
    return (
      <div>
        <FieldLabel label={label} required={required} />
        <div className="flex items-center gap-2.5 rounded-[12px] border border-red-500/40 bg-red-500/[0.06] py-1.5 pl-1.5 pr-4">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-red-500/15 text-red-400">
            <X size={17} strokeWidth={3} />
          </span>
          <div className="min-w-0 flex-1 leading-tight">
            <div className="truncate text-[13.5px] font-semibold text-red-300">
              {t("checkNotFound")}
            </div>
            <div className="text-tx-dim truncate font-mono text-[12px]">{value}</div>
          </div>
          <button
            type="button"
            onClick={edit}
            className="text-tx-dim hover:text-tx-mute shrink-0 text-[13px] font-medium transition"
          >
            {t("checkEdit")}
          </button>
        </div>
      </div>
    );
  }

  // Idle / loading / our-or-provider fault: show the input + check button.
  return (
    <div>
      <FieldLabel label={label} required={required} />
      <div className="flex items-center gap-2.5">
        <div className="relative min-w-0 flex-1">
          <input
            ref={inputRef}
            type="text"
            inputMode="numeric"
            required={required}
            aria-required={required}
            value={value}
            placeholder={t("playerIdPlaceholder")}
            onChange={(e) => {
              onChange(e.target.value);
            }}
            className={`border-border-2 bg-card focus:border-primary/60 placeholder:text-tx-dim h-[46px] w-full rounded-[12px] border pl-4 text-[15px] outline-none transition ${help ? "pr-11" : "pr-4"}`}
          />
          {help && (
            <button
              type="button"
              onClick={() => {
                setHelpOpen((o) => !o);
              }}
              aria-label={t("whereToFind")}
              aria-expanded={helpOpen}
              className="bg-muted text-tx-mute hover:text-primary hover:bg-primary/10 absolute right-2 top-1/2 flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-full transition"
            >
              <Info size={15} />
            </button>
          )}
        </div>
        <button
          type="button"
          disabled={!enabled || state.phase === "loading"}
          onClick={() => void onCheck()}
          className="border-primary/35 bg-primary/[0.12] text-primary hover:bg-primary/20 inline-flex h-[46px] shrink-0 items-center justify-center gap-2 rounded-[12px] border px-5 text-[14px] font-semibold transition disabled:pointer-events-none disabled:opacity-40"
        >
          {state.phase === "loading" && <Loader2 size={16} className="animate-spin" />}
          {state.phase === "loading" ? t("checking") : t("check")}
        </button>
      </div>
      {help && helpOpen && (
        <p className="text-tx-dim mt-2 px-1 text-[13px] leading-relaxed">{help}</p>
      )}
      {done?.status === "error" && (
        <p className="text-tx-dim mt-2 px-1 text-[13px]">
          {t("checkFailed")} ·{" "}
          <button
            type="button"
            onClick={() => void onCheck()}
            className="text-primary hover:text-primary-2 font-medium"
          >
            {t("checkRetry")}
          </button>
        </p>
      )}
    </div>
  );
}

function FieldLabel({ label, required }: { label: string; required: boolean }) {
  return (
    <span className="text-tx-dim mb-2 block text-[12px] font-semibold uppercase tracking-[0.08em]">
      {label}
      {required && <span className="text-primary"> *</span>}
    </span>
  );
}

/**
 * Replaces the SKU grid for a variable-amount product (Steam wallet top-up):
 * the customer types a dollar amount instead of picking a denomination.
 * `sku.display_price` is the localised price of ONE dollar (its `price_usd`
 * is a `1`-placeholder) — `null` means the FX trust gate rejected the live
 * rate, so the product isn't sellable right now and we render that instead
 * of a price of zero.
 */
function VariableAmountCard({
  sku,
  value,
  onChange,
  onFocus,
  locale,
  t,
}: {
  sku: SkuOut;
  value: string;
  onChange: (v: string) => void;
  onFocus: () => void;
  locale: string;
  t: (key: string, values?: Record<string, string>) => string;
}) {
  const rate = sku.display_price;
  if (!rate) {
    return (
      <div className="border-border bg-card text-tx-mute rounded-[14px] border border-dashed p-6 text-center text-sm">
        {t("priceUnavailable")}
      </div>
    );
  }
  const min = sku.min_amount_usd != null ? Number.parseFloat(sku.min_amount_usd) : 0;
  const max = sku.max_amount_usd != null ? Number.parseFloat(sku.max_amount_usd) : 0;
  const parsed = parseAmount(value);
  const error = parsed !== null ? amountError(parsed, min, max) : null;
  const total = parsed !== null ? parsed * Number(rate.amount) : null;
  const errorMessage =
    error === "below"
      ? t("amountBelow", { min: formatMoney(min.toFixed(2), "USD", locale) })
      : error === "above"
        ? t("amountAbove", { max: formatMoney(max.toFixed(2), "USD", locale) })
        : error === "precision"
          ? t("amountPrecision")
          : null;

  return (
    <div className="border-border bg-card rounded-[14px] border p-4">
      <label className="block">
        <span className="text-tx-mute mb-1.5 block text-[13px] font-semibold">
          {t("amountLabel")}
        </span>
        <div className="relative">
          <span
            className="text-tx-dim pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-[15px] font-bold"
            aria-hidden="true"
          >
            $
          </span>
          <input
            type="text"
            inputMode="decimal"
            value={value}
            onFocus={onFocus}
            onChange={(e) => {
              onChange(e.target.value);
            }}
            placeholder={t("amountPlaceholder")}
            className="border-border bg-bg focus:border-primary h-[46px] w-full rounded-[12px] border pl-7 pr-3.5 text-[15px] font-semibold outline-none transition"
          />
        </div>
        {errorMessage && <p className="mt-1.5 text-[12px] text-[#FF6B6B]">{errorMessage}</p>}
      </label>
      <div className="border-border/70 mt-3 flex items-center justify-between rounded-[10px] border bg-[hsl(var(--bg))] px-3 py-2.5">
        <div className="flex min-w-0 items-center gap-2">
          <span className="text-tx-mute truncate text-[12px]">
            {t("ratePerDollar", { rate: formatUzs(locale, Math.round(Number(rate.amount))) })}
          </span>
          <span className="bg-primary/15 text-primary flex-shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-bold">
            {t("zeroFee")}
          </span>
        </div>
        {total !== null && (
          <span className="flex-shrink-0 text-[14px] font-bold">
            {formatUzs(locale, Math.round(total))}
          </span>
        )}
      </div>
    </div>
  );
}

export function PurchasePanel({ products, locale }: { products: ProductDetail[]; locale: string }) {
  const t = useTranslations("web.store");
  const { user } = useAuth();
  // Anchor the default on a mid-tier pack, not the cheapest, and badge it as
  // the recommended "Хит" — a default nudge on grids with several packs. Only
  // applies to a fixed-denomination primary product with 3+ SKUs; a
  // variable-amount product (Steam) or a 1–2 SKU brand gets no badge and falls
  // back to the first SKU.
  const primarySkus = products[0]?.skus ?? [];
  const primaryIsVariable =
    primarySkus.length > 0 && primarySkus.every((s) => s.variable_amount ?? false);
  const recommendedSkuId =
    !primaryIsVariable && primarySkus.length >= 3
      ? primarySkus[Math.floor(primarySkus.length / 2)]?.id
      : undefined;
  const [skuId, setSkuId] = useState<string | undefined>(
    recommendedSkuId ?? products[0]?.skus[0]?.id,
  );
  const [form, setForm] = useState<Record<string, string>>({});
  const [email, setEmail] = useState("");
  // The dollar amount typed for a variable-amount SKU. Raw string, not a
  // number — see `@/lib/variable-amount` for parsing/validation.
  const [amountInput, setAmountInput] = useState("");
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

  // Typed amount is per-SKU — clear it on a selection switch so a leftover
  // "10" from a previous variable-amount SKU never bleeds into the next.
  useEffect(() => {
    setAmountInput("");
  }, [skuId]);

  const selSkuVariable = selSku?.variable_amount ?? false;
  const variableRate = selSkuVariable ? (selSku?.display_price ?? null) : null;
  const parsedAmount = selSkuVariable ? parseAmount(amountInput) : null;
  const minUsd = selSku?.min_amount_usd != null ? Number.parseFloat(selSku.min_amount_usd) : 0;
  const maxUsd = selSku?.max_amount_usd != null ? Number.parseFloat(selSku.max_amount_usd) : 0;
  const variableAmountErr =
    selSkuVariable && parsedAmount !== null ? amountError(parsedAmount, minUsd, maxUsd) : null;
  // Client-side total for display only — the server recomputes the
  // authoritative price from `amount_usd` at checkout.
  const variableTotal =
    selSkuVariable && parsedAmount !== null && variableRate
      ? parsedAmount * Number(variableRate.amount)
      : null;
  // Gates the CTA for a variable-amount SKU: a live rate (the FX trust gate
  // didn't reject it) and a parsed, in-bounds, two-decimals-or-fewer amount.
  const variableAmountOk =
    !selSkuVariable ||
    (variableRate !== null && parsedAmount !== null && variableAmountErr === null);

  const emailOk = EMAIL_RE.test(email);
  const fieldsOk = fields.every((f) => !f.required || (form[f.key]?.trim() ?? "") !== "");
  // Logged-in users don't need to supply an email — the account email is used server-side.
  const canPay =
    Boolean(selSku) &&
    (user !== null || emailOk) &&
    fieldsOk &&
    Boolean(methodId) &&
    variableAmountOk &&
    !loading;
  // Tell the user *why* the pay button is inactive instead of leaving a dimmed
  // button with no explanation.
  const payHint = !selSku
    ? t("selectPack")
    : selSkuVariable && variableRate === null
      ? t("priceUnavailable")
      : selSkuVariable && parsedAmount === null
        ? t("amountRequired")
        : selSkuVariable && variableAmountErr === "below"
          ? t("amountBelow", { min: formatMoney(minUsd.toFixed(2), "USD", locale) })
          : selSkuVariable && variableAmountErr === "above"
            ? t("amountAbove", { max: formatMoney(maxUsd.toFixed(2), "USD", locale) })
            : selSkuVariable && variableAmountErr === "precision"
              ? t("amountPrecision")
              : !user && !emailOk
                ? t("payHintEmail")
                : !fieldsOk
                  ? t("payHintFields")
                  : null;

  // The price shown in the summary header, the pay button, and the mobile
  // sticky bar. A variable-amount SKU has no fixed `skuPrice` — its total
  // depends on the customer's typed amount, so it's computed from
  // `variableTotal` instead, with the "not for sale" / "not typed yet"
  // states handled explicitly rather than falling back to a placeholder.
  const selectedPriceLabel = !selSku
    ? ""
    : !selSkuVariable
      ? skuPrice(locale, selSku)
      : variableRate === null
        ? t("priceUnavailable")
        : variableTotal !== null
          ? formatUzs(locale, Math.round(variableTotal))
          : "—";
  // `selectedPriceLabel` holds the full "temporarily unavailable" sentence
  // when the FX trust gate rejected the rate — that sentence belongs on the
  // card/hint, never glued onto "Оплатить" or the mobile summary line.
  const priceUnavailable = selSkuVariable && variableRate === null;

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

      // Sent as a fixed-2-decimal string so the server never has to round-trip
      // a client float — the server re-validates and re-prices from it
      // regardless (see `pricing.variable.validate_amount`).
      const orderItem = {
        sku_id: selSku.id,
        qty: 1,
        fulfillment_data: form,
        ...(selSkuVariable && parsedAmount !== null ? { amount_usd: parsedAmount.toFixed(2) } : {}),
      };
      const orderBody = isLoggedIn
        ? { currency: "UZS", items: [orderItem] }
        : { currency: "UZS", guest_email: email, items: [orderItem] };

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
      const trackHref = pathFor(locale, `/orders/${order.id}${emailSuffix}`);
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
          <h2 className="font-display text-xl font-bold tracking-[-0.02em]">
            {t(primaryIsVariable ? "amountTitle" : "packsTitle")}
          </h2>
          {products.map((product) => {
            // A variable-amount product (Steam wallet top-up) has exactly one
            // SKU with nothing to pick — the customer types the amount, so
            // the denomination grid is replaced with the amount card.
            const isVariableProduct =
              product.skus.length > 0 && product.skus.every((s) => s.variable_amount ?? false);
            const variableSku = isVariableProduct ? product.skus[0] : undefined;
            return (
              <div key={product.id} className="mt-5">
                {products.length > 1 && (
                  <div className="text-tx-mute mb-3 text-sm font-semibold">{product.name}</div>
                )}
                {variableSku ? (
                  <VariableAmountCard
                    sku={variableSku}
                    value={skuId === variableSku.id ? amountInput : ""}
                    onChange={setAmountInput}
                    onFocus={() => {
                      setSkuId(variableSku.id);
                    }}
                    locale={locale}
                    t={t}
                  />
                ) : (
                  <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                    {product.skus.map((sku) => {
                      const active = sku.id === skuId;
                      const recommended = sku.id === recommendedSkuId;
                      const img = sku.image_url ?? product.image_url;
                      return (
                        <button
                          key={sku.id}
                          type="button"
                          aria-pressed={active}
                          onClick={() => {
                            setSkuId(sku.id);
                          }}
                          className={`focus-visible:ring-primary focus-visible:ring-offset-bg relative flex flex-col items-start gap-2 rounded-[14px] border p-3 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 ${
                            active
                              ? "border-primary bg-primary/10"
                              : "border-border bg-card hover:border-border-2"
                          }`}
                        >
                          {recommended && (
                            <span className="bg-primary text-primary-foreground absolute right-2 top-2 rounded-full px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-[0.06em]">
                              {t("popular")}
                            </span>
                          )}
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
                )}
              </div>
            );
          })}
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
                  <span className="font-display text-lg font-bold">{selectedPriceLabel}</span>
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
                {fields.map((f) =>
                  f.check && selProduct ? (
                    <CheckablePlayerField
                      key={f.key}
                      productId={selProduct.id}
                      label={label(f.label)}
                      value={form[f.key] ?? ""}
                      onChange={(v) => {
                        setForm((s) => ({ ...s, [f.key]: v }));
                      }}
                      pattern={f.pattern}
                      required={f.required}
                      serverId={f.check.server_field ? (form[f.check.server_field] ?? null) : null}
                      help={f.help_text ? label(f.help_text) : null}
                      t={t}
                    />
                  ) : (
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
                    </label>
                  ),
                )}
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
                  {selSku &&
                    selectedPriceLabel &&
                    selectedPriceLabel !== "—" &&
                    !priceUnavailable &&
                    ` · ${selectedPriceLabel}`}
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
                {priceUnavailable ? "—" : selectedPriceLabel}
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
