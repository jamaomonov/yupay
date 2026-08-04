"use client";

import { formatMoney } from "@yupay/utils";
import { ArrowUpRight, Check, Info, Loader2, X } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

import { WhereToFindModal } from "./WhereToFindModal";

import type { FormField, ProductDetail, SkuOut } from "@/lib/catalog";

import { useAuth } from "@/lib/auth";
import { buttonStyles } from "@/lib/button";
import { getAccessToken } from "@/lib/client";
import { mintGuestToken } from "@/lib/guest";
import { saveGuestOrder } from "@/lib/guest-orders";
import {
  methodVisibility,
  providerStatusMap,
  selectActiveMethodId,
  type ProviderStatus,
  type ProvidersOut,
} from "@/lib/payment-providers";
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
  placeholder,
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
  placeholder: string;
  t: (key: string, values?: Record<string, string>) => string;
}) {
  // Pick the mobile keyboard from the field's pattern: a letter-bearing
  // pattern (e.g. a Steam login `[A-Za-z0-9_-]`) needs the full text keyboard,
  // while a digits-only id (a game player id) gets the numeric pad.
  const inputMode = pattern && !/[A-Za-z]/.test(pattern) ? "numeric" : "text";
  const [state, setState] = useState<CheckState>(IDLE);
  const [helpOpen, setHelpOpen] = useState(false);
  const closeHelp = useCallback(() => {
    setHelpOpen(false);
  }, []);
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
            inputMode={inputMode}
            autoComplete="off"
            required={required}
            aria-required={required}
            value={value}
            placeholder={placeholder}
            onChange={(e) => {
              onChange(e.target.value);
            }}
            className={`border-border-2 bg-card focus:border-primary/60 placeholder:text-tx-dim h-[46px] w-full rounded-[12px] border pl-4 text-[15px] outline-none transition ${help ? "pr-11" : "pr-4"}`}
          />
          {help && (
            <button
              type="button"
              onClick={() => {
                setHelpOpen(true);
              }}
              aria-label={t("whereToFind")}
              aria-haspopup="dialog"
              className="bg-muted text-tx-mute hover:text-primary hover:bg-primary/10 absolute right-1.5 top-1/2 flex h-9 w-9 -translate-y-1/2 items-center justify-center rounded-full transition"
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
      {help && (
        <WhereToFindModal
          open={helpOpen}
          title={t("whereToFind")}
          body={help}
          closeLabel={t("close")}
          onClose={closeHelp}
        />
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
  const rateUzs = Number(rate.amount); // one dollar, in UZS
  const min = sku.min_amount_usd != null ? Number.parseFloat(sku.min_amount_usd) : 1;
  const max = sku.max_amount_usd != null ? Number.parseFloat(sku.max_amount_usd) : 0;
  const parsed = parseAmount(value);
  const error = parsed !== null ? amountError(parsed, min, max) : null;
  const total = parsed !== null ? parsed * rateUzs : null;
  const errorMessage =
    error === "below"
      ? t("amountBelow", { min: formatMoney(min.toFixed(2), "USD", locale) })
      : error === "above"
        ? t("amountAbove", { max: formatMoney(max.toFixed(2), "USD", locale) })
        : error === "precision"
          ? t("amountPrecision")
          : null;

  // Quick-pick presets, clamped to the SKU's own [min, max]. $10 is the nudge.
  const PRESETS = [5, 10, 20, 30, 50, 100].filter((a) => a >= min && a <= max);
  const HIT = 10;
  const sliderVal = Math.min(max, Math.max(min, parsed ?? min));
  const pick = (amount: number) => {
    onFocus();
    onChange(String(amount));
  };
  // Hard-cap the typed amount at the SKU's max ($300 for Steam). The slider is
  // already bounded; the text input would otherwise accept a larger number.
  const handleAmountChange = (raw: string) => {
    const n = parseAmount(raw);
    onChange(n !== null && n > max ? String(max) : raw);
  };
  const rateLine = t("ratePerDollar", { rate: formatUzs(locale, Math.round(rateUzs)) });

  return (
    <div className="border-border overflow-hidden rounded-[18px] border bg-[linear-gradient(135deg,hsl(var(--card)),hsl(var(--bg)))]">
      {/* header band: title + subtitle */}
      <div className="border-border/70 border-b p-5">
        <h2 className="font-display text-xl font-bold tracking-[-0.02em]">{t("amountTitle")}</h2>
        <p className="text-tx-mute mt-1 text-[13px]">{t("amountSubtitle")}</p>
      </div>

      {/* custom amount first — stays neutral; the selected preset (or nothing)
          carries the lime accent, never this block */}
      <div className="p-5 pb-0">
        <div className="border-border bg-card rounded-[16px] border p-5">
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            {/* left: label + input + slider */}
            <div className="lg:border-border/70 lg:border-r lg:pr-6">
              <span className="text-tx-mute mb-2 block text-[13px]">{t("amountOwn")}</span>
              <div className="border-border bg-bg focus-within:border-primary flex items-center gap-2 rounded-[12px] border px-3.5 transition">
                <span className="text-tx-dim text-[18px] font-bold" aria-hidden="true">
                  $
                </span>
                <input
                  type="text"
                  inputMode="decimal"
                  value={value}
                  onFocus={onFocus}
                  onChange={(e) => {
                    handleAmountChange(e.target.value);
                  }}
                  placeholder={t("amountPlaceholder")}
                  className="h-[52px] min-w-0 flex-1 bg-transparent text-[22px] font-extrabold outline-none"
                />
                {total !== null && (
                  <span className="text-tx-mute shrink-0 font-mono text-[13px]">
                    {formatUzs(locale, Math.round(total))}
                  </span>
                )}
              </div>
              <input
                type="range"
                min={min}
                max={max}
                step={1}
                value={sliderVal}
                onFocus={onFocus}
                onChange={(e) => {
                  pick(Number(e.target.value));
                }}
                aria-label={t("amountOwn")}
                className="mt-4 w-full"
                style={{ accentColor: "hsl(var(--primary))" }}
              />
              <div className="text-tx-dim mt-1.5 flex justify-between text-[12px]">
                <span>${min}</span>
                <span>${max}</span>
              </div>
            </div>

            {/* right: rate / fee / limit */}
            <dl className="flex flex-col justify-center gap-3 text-[14px]">
              <div className="flex items-center justify-between gap-3">
                <dt className="text-tx-mute">{t("rateLabel")}</dt>
                <dd className="font-mono font-semibold">{rateLine}</dd>
              </div>
              <div className="flex items-center justify-between gap-3">
                <dt className="text-tx-mute">{t("feeLabel")}</dt>
                <dd className="text-primary font-mono font-bold">0%</dd>
              </div>
              <div className="flex items-center justify-between gap-3">
                <dt className="text-tx-mute">{t("limitLabel")}</dt>
                <dd className="font-mono font-semibold">
                  ${min} — ${max}
                </dd>
              </div>
            </dl>
          </div>
          {errorMessage && <p className="mt-3 text-[12px] text-[#FF6B6B]">{errorMessage}</p>}
        </div>
      </div>

      {/* quick-pick preset grid — hidden on phones (below sm) so the custom
          amount input + slider is the single, uncluttered way to choose; the
          presets return as a convenience on wider screens. */}
      {PRESETS.length > 0 && (
        <div className="hidden gap-3 p-5 sm:grid sm:grid-cols-3">
          {PRESETS.map((amount) => {
            const active = parsed === amount;
            return (
              <button
                key={amount}
                type="button"
                aria-pressed={active}
                onClick={() => {
                  pick(amount);
                }}
                className={`focus-visible:ring-primary focus-visible:ring-offset-bg relative flex flex-col items-start gap-3 rounded-[16px] border p-4 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 ${
                  active
                    ? "border-primary bg-primary/[0.06]"
                    : "border-border bg-card hover:border-border-2"
                }`}
              >
                <div className="flex w-full items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span
                      className="border-border/60 size-9 rounded-[10px] border bg-[hsl(var(--card-2))] bg-gradient-to-br from-white/[0.04] to-transparent"
                      aria-hidden="true"
                    />
                    <span className="text-tx-dim font-mono text-[12px] tracking-[0.08em]">USD</span>
                  </div>
                  {amount === HIT && (
                    <span className="bg-primary text-primary-foreground rounded-full px-2 py-0.5 text-[10px] font-bold">
                      {t("popular")}
                    </span>
                  )}
                </div>
                <div className="font-display text-2xl font-extrabold">${amount}</div>
                <div className="text-tx-mute font-mono text-[12px]">
                  {formatUzs(locale, Math.round(amount * rateUzs))}
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function PurchasePanel({
  products,
  locale,
  children,
}: {
  products: ProductDetail[];
  locale: string;
  /** Server-rendered sections (how-to, about, FAQ) placed in the left column
   *  below the pick, so the sticky order sidebar scrolls alongside them. */
  children?: ReactNode;
}) {
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
  // Admin-controlled provider availability (`GET /payments/providers`). `null`
  // until the fetch resolves — `methodVisibility` treats that as "fail open"
  // so the method grid never blanks out on a slow network.
  const [providerStatus, setProviderStatus] = useState<Map<string, ProviderStatus> | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<{
    orderId: string;
    intentUrl: string | null;
    trackHref: string;
  } | null>(null);
  // The mobile sticky pay bar scrolls here when the form isn't complete yet.
  const asideRef = useRef<HTMLElement>(null);

  // Hide the mobile pay bar whenever the real order form (the aside) or the
  // page footer is on screen: the bar is a shortcut to a CTA that's scrolled
  // away, so it should never duplicate the visible one — nor sit on top of the
  // footer at the end of the page (the reported overlap).
  const [barHidden, setBarHidden] = useState(false);
  useEffect(() => {
    // No observer (jsdom/old browsers) → leave the bar always visible.
    if (typeof IntersectionObserver === "undefined") return;
    const footer = document.querySelector("footer");
    const targets: Element[] = [];
    if (asideRef.current) targets.push(asideRef.current);
    if (footer) targets.push(footer);
    if (targets.length === 0) return;
    const visible = new Set<Element>();
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) visible.add(e.target);
          else visible.delete(e.target);
        }
        setBarHidden(visible.size > 0);
      },
      { threshold: 0 },
    );
    targets.forEach((el) => {
      io.observe(el);
    });
    return () => {
      io.disconnect();
    };
  }, []);

  // Load provider availability once on mount so the method grid below can
  // hide admin-disabled providers and grey out ones under maintenance before
  // the customer ever tries to pay.
  useEffect(() => {
    let cancelled = false;
    fetch(`${API}/api/v1/payments/providers`)
      .then((r) => r.json() as Promise<ProvidersOut>) // narrows a known-shape JSON response
      .then((data) => {
        if (!cancelled) setProviderStatus(providerStatusMap(data));
      })
      .catch(() => {
        // Leave `providerStatus` as `null` — fails open, see its declaration.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Once live status lands, make sure the selection reflects it: the
  // hardcoded default (`METHODS[0]`) may itself be under maintenance or
  // admin-disabled. Reselect the first `active` method, or clear the
  // selection entirely when none are — `canPay` below then keeps Pay
  // disabled rather than ever letting a non-active provider be submitted.
  useEffect(() => {
    if (!providerStatus) return;
    setMethodId((current) => selectActiveMethodId(METHODS, current, providerStatus) ?? "");
  }, [providerStatus]);

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
  // Not just "a method id is set" — the selected method's *provider* must
  // currently be `active`. Combined with the reselection effect above, this
  // is the belt-and-suspenders guarantee that Pay can never submit a
  // maintenance/admin-disabled provider (`methodVisibility` fails open while
  // `providerStatus` is still loading, matching the method grid's own render).
  const selectedProvider = METHODS.find((m) => m.id === methodId)?.provider;
  const selectedMethodActive =
    selectedProvider !== undefined &&
    methodVisibility(selectedProvider, providerStatus) === "active";
  // When every acquirer is admin-disabled/unavailable the grid renders empty;
  // show an explicit "no methods" line instead of a bare heading. Fails open
  // while `providerStatus` loads, so it never flashes during the initial fetch.
  const anyMethodVisible = METHODS.some(
    (m) => methodVisibility(m.provider, providerStatus) !== "hidden",
  );
  // Logged-in users don't need to supply an email — the account email is used server-side.
  const canPay =
    Boolean(selSku) &&
    (user !== null || emailOk) &&
    fieldsOk &&
    selectedMethodActive &&
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
      // The early return above (`!canPay`) guarantees `selectedMethodActive`,
      // which in turn guarantees `selectedProvider !== undefined` — but that's
      // a runtime guarantee only. Checking a separate boolean doesn't narrow
      // `selectedProvider`'s type (it stays `string | undefined` to TS); no
      // fallback is needed because the early return has already ensured it's
      // defined by the time we get here.
      const provider = selectedProvider;

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
        const access_token = await mintGuestToken(email);
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

      // Absolute URL the acquirer redirects the customer back to after they
      // pay — the server validates + defaults it, but the order page (with
      // the guest `?email=` suffix, when applicable) is always the right target.
      const trackHref = pathFor(locale, `/orders/${order.id}${emailSuffix}`);
      const returnUrl = `${window.location.origin}${trackHref}`;

      const intentRes = await fetch(intentsUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": crypto.randomUUID(),
          ...auth,
        },
        body: JSON.stringify({ order_id: order.id, provider, return_url: returnUrl }),
      });
      if (!intentRes.ok) throw new Error("intent");
      const intent = (await intentRes.json()) as { intent_url: string | null };

      if (!isLoggedIn) {
        // Guests have no account to list orders against — remember this one
        // in localStorage so a later guest order list can render it.
        const brand = selProduct?.brand ?? products[0]?.brand;
        if (brand) {
          saveGuestOrder({
            orderId: order.id,
            email,
            brandSlug: brand.slug,
            brandName: brand.name,
            createdAt: new Date().toISOString(),
          });
        }
      }

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
        <div className="lg:col-start-1 lg:row-start-1">
          {/* Variable products (Steam) render their own titled "Сумма пополнения"
              card, so the section heading is only for the fixed-denomination grid. */}
          {!primaryIsVariable && (
            <h2 className="font-display text-xl font-bold tracking-[-0.02em]">{t("packsTitle")}</h2>
          )}
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

        {/* summary + payment + pay — placed in DOM before the how-to/about/FAQ
            so that on mobile (single-column auto-flow) the order form sits right
            under the pick, not at the very end of the page. On desktop it's the
            right column, spanning both rows so the sticky sidebar scrolls
            alongside the secondary content below. */}
        <aside
          ref={asideRef}
          className="scroll-mt-[88px] lg:sticky lg:top-[100px] lg:col-start-2 lg:row-span-2 lg:row-start-1 lg:self-start"
        >
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
                      placeholder={f.placeholder ? label(f.placeholder) : t("playerIdPlaceholder")}
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
              {!anyMethodVisible && (
                <p className="border-border bg-card text-tx-dim rounded-[12px] border px-3 py-3 text-[13px]">
                  {t("paymentNone")}
                </p>
              )}
              <div className="grid grid-cols-2 gap-2">
                {METHODS.map((m) => {
                  // Absent from the providers response → admin-disabled, not
                  // offered at all. `maintenance` still renders, but greyed
                  // out and non-clickable via the native `disabled` attribute.
                  const visibility = methodVisibility(m.provider, providerStatus);
                  if (visibility === "hidden") return null;
                  const disabled = visibility === "maintenance";
                  const active = !disabled && m.id === methodId;
                  return (
                    <button
                      key={m.id}
                      type="button"
                      aria-label={m.name}
                      aria-pressed={active}
                      disabled={disabled}
                      onClick={() => {
                        setMethodId(m.id);
                      }}
                      className={`focus-visible:ring-primary focus-visible:ring-offset-bg flex flex-col items-center justify-center gap-1 rounded-[12px] border px-3 py-3 transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 ${
                        disabled
                          ? "border-border bg-card"
                          : active
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
                      {disabled && (
                        <span className="text-tx-dim text-[10px] font-semibold uppercase tracking-[0.04em]">
                          {t("paymentMaintenance")}
                        </span>
                      )}
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

        {/* How-to / about / FAQ — desktop: left column, row 2, so the sticky
            aside scrolls alongside it; mobile: after the order form. */}
        {children && <div className="lg:col-start-1 lg:row-start-2">{children}</div>}
      </div>

      {/* Mobile sticky checkout bar — brings the total + pay CTA up so the
          customer doesn't scroll past the whole form. Pays when ready, else
          jumps to the form (which shows what's still missing). */}
      {selSku && (
        <div
          className={`border-border bg-bg/95 fixed inset-x-0 bottom-0 z-40 border-t px-4 pt-3 backdrop-blur-xl transition-transform duration-200 [padding-bottom:calc(0.75rem+env(safe-area-inset-bottom))] lg:hidden ${
            barHidden ? "pointer-events-none translate-y-full" : "translate-y-0"
          }`}
        >
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
