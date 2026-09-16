"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { formatMoney } from "@yupay/utils";
import { ArrowUpRight, Check, Info, Loader2, X } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { type ReactNode, useCallback, useEffect, useId, useMemo, useRef, useState } from "react";

import { ConfirmPurchaseModal } from "./ConfirmPurchaseModal";
import { type AppliedPromo, PromoField } from "./PromoField";
import { WhereToFindModal } from "./WhereToFindModal";

import type { FormField, ProductDetail, SkuOut } from "@/lib/catalog";
import type { PlayerCheckResult } from "@/lib/player-check";

import { WalletMark } from "@/components/icons/WalletMark";
import { useAuth } from "@/lib/auth";
import { buttonStyles } from "@/lib/button";
import { ApiError, getAccessToken, SURFACE } from "@/lib/client";
import { collectClientHints } from "@/lib/client-hints";
import { mintGuestToken } from "@/lib/guest";
import { saveGuestOrder } from "@/lib/guest-orders";
import { isOptimizable } from "@/lib/image";
import {
  methodVisibility,
  providerStatusMap,
  selectActiveMethodId,
  type ProviderStatus,
  type ProvidersOut,
} from "@/lib/payment-providers";
import { withAutoOpen } from "@/lib/payment-return";
import {
  blocksCheckout,
  checkBlocker,
  checkUnavailable,
  currentCheck,
  runPlayerCheck,
  type PlayerCheckVerdict,
} from "@/lib/player-check-state";
import { formatUzs, pathFor } from "@/lib/seo";
import { packagePrice, starLayers, visibleStarPackages } from "@/lib/star-packages";
import {
  amountError,
  boundToUnits,
  parseAmount,
  tierPrice,
  toUsd,
  unitAmountError,
  unitsPerUsd,
} from "@/lib/variable-amount";
import { getWallet, WALLET_CURRENCY } from "@/lib/wallet";
import { spendableBalance, walletTile } from "@/lib/wallet-balance";
import { useLoginModal } from "@/store/useLoginModal";

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
/** Not an acquirer: the balance is our own ledger, and `WalletGateway`
 *  settles it synchronously inside `create_intent`. Kept out of `METHODS`
 *  so provider-availability logic, which is about upstream acquirers,
 *  never reasons about it. */
const WALLET_METHOD_ID = "wallet";

// Payme first, deliberately — this order also picks the default, since
// `selectActiveMethodId` takes the first active method. Measured on
// production over the 14 days to 2026-09-06: of orders that reached an
// acquirer, Payme converted 149 and lost 84 (36% abandoned), Click
// converted 69 and lost 100 (59%), Uzum converted 19 and lost 33 (63%).
// The pattern behind it is visible in the switches: 20 buyers abandoned
// Click and re-ordered through Payme, and 11 of those then paid — they
// could pay, just not there. The reverse move happened 4 times and never
// converted. The structural difference is what each hands the buyer:
// Payme opens `checkout.paycom.uz`, a web page that takes a card from
// anyone; Click's `my.click.uz/services/pay` effectively wants their
// account, and Uzum's is an app deeplink with no web form at all.
// Deliberately NOT applied to the mini app: inside Telegram the Click
// integration loses only 39%, close to Payme's, because the bank's app is
// already on the phone. Revisit if those numbers move.
const METHODS: Method[] = [
  {
    id: "payme",
    name: "Payme",
    provider: "payme",
    icon: "/payment/payme-mark.png",
    w: 160,
    h: 160,
  },
  {
    id: "click",
    name: "Click",
    provider: "click",
    icon: "/payment/click-mark.png",
    w: 160,
    h: 160,
  },
  { id: "uzum", name: "Uzum", provider: "uzum", icon: "/payment/uzum-mark.png", w: 160, h: 160 },
];

/** A fixed-price SKU's display price. Never call this for a variable-amount
 *  SKU — its `display_price` is the rate for ONE dollar, not a total, and
 *  its `price_usd` is a `1`-placeholder; use `selectedPriceLabel` instead. */
function skuPrice(locale: string, sku: SkuOut): string {
  if (sku.display_price) return formatUzs(locale, Math.round(Number(sku.display_price.amount)));
  return formatMoney(sku.price_usd, "USD", locale);
}

/**
 * Sold as a typed (or tapped) integer quantity of `amount_unit` — Telegram
 * Stars — checkout out as `{ sku_id, qty }` with no `amount_usd`. Mirrors
 * `yupay.modules.catalog.unit_sku.is_unit_sku` on the server: `variable_amount`
 * false and `amount_unit`/`min_qty`/`max_qty` all present. Until the Stars
 * seed lands (a later task), `tg-stars-any` is still `variable_amount`, so it
 * takes `VariableAmountCard` below rather than this path — the two are
 * mutually exclusive by construction, same as on the server.
 */
function isUnitSku(sku: SkuOut): boolean {
  return (
    !(sku.variable_amount ?? false) &&
    sku.amount_unit != null &&
    sku.min_qty != null &&
    sku.max_qty != null
  );
}

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

/** What one press of «Проверить» asks about: everything G2B is given, and so
 *  everything the answer is about. `PlayerCheckVerdict` is this plus the
 *  answer; `CheckablePlayerField` also holds it for the in-flight press. */
interface Question {
  brandSlug: string;
  playerId: string;
  serverId: string | null;
}

function sameQuestion(a: Question, b: Question): boolean {
  return a.brandSlug === b.brandSlug && a.playerId === b.playerId && a.serverId === b.serverId;
}

/**
 * The checkable player-id field: a pill input paired with an advisory
 * nickname lookup (`f.check` on the catalog schema). Everything about
 * *asking* — the blocker hints, the in-flight button, the confirmation pill —
 * is owned here; the two things that flow out are the value (`onChange`) and
 * the check's verdict (`onCheckResult`), which is what gates Pay. A resolved
 * id collapses the input into a confirmation pill; a wrong id or a lookup
 * fault never blocks checkout — the customer can pay regardless.
 */
function CheckablePlayerField({
  brandSlug,
  label,
  value,
  onChange,
  pattern,
  required,
  serverId,
  serverLabel,
  help,
  placeholder,
  check,
  onCheckResult,
  siblingHint,
  t,
}: {
  brandSlug: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  pattern?: string | null | undefined;
  required: boolean;
  serverId: string | null;
  /** The sibling server field's own label (e.g. "ID сервера"), present only
   *  when `check.server_field` names one — doubles as "server is required
   *  for this check" and as the text for the "fill it in first" hint below. */
  serverLabel: string | null;
  help: string | null;
  placeholder: string;
  /** The verdict that currently applies to `value` under `brandSlug`, or
   *  `null` when none does (`currentCheck`). Handed down rather than kept
   *  here — and reported back up from the check handler rather than mirrored
   *  with an effect — because the panel gates Pay on it: an effect lands a
   *  commit later, which left Pay payable while this field had already
   *  stopped standing behind the id. */
  check: PlayerCheckResult | null;
  /** Reports a fresh verdict, filed under the product + id it was asked
   *  about, or `null` when the pill's «Изменить» drops it. Lets the panel
   *  require a real "valid" before Pay, not just a filled-in box. */
  onCheckResult: (verdict: PlayerCheckVerdict | null) => void;
  /** The sibling-region brand's page, when this brand is one half of a
   *  `<slug>` / `<slug>-ru` pair — the panel resolves it once (it already
   *  has `locale` for `pathFor`) and hands down a ready `href`, so this field
   *  needs no `locale` prop of its own. `null` when the brand has no twin. */
  siblingHint: { href: string; name: string } | null;
  t: (key: string, values?: Record<string, string>) => string;
}) {
  // Pick the mobile keyboard from the field's pattern: a letter-bearing
  // pattern (e.g. a Steam login `[A-Za-z0-9_-]`) needs the full text keyboard,
  // while a digits-only id (a game player id) gets the numeric pad.
  const inputMode = pattern && !/[A-Za-z]/.test(pattern) ? "numeric" : "text";
  // The question currently in flight, or `null` when none is. Held as the
  // question rather than as a bare `true` so the spinner goes stale on exactly
  // the terms the verdict does: `checkPlayer` sets no deadline of its own, so
  // switching package mid-check would otherwise leave the button spinning,
  // disabled, on a lookup whose answer is already going to be discarded.
  const [asking, setAsking] = useState<Question | null>(null);
  const checking =
    asking !== null && sameQuestion(asking, { brandSlug, playerId: value, serverId });
  // The same value, readable from inside an in-flight check: `asking` there is
  // whatever this press captured, so only a ref can say whether a *later*
  // press has since superseded it. Written and cleared in lockstep with the
  // state above, so the two cannot drift.
  const latestAsk = useRef<Question | null>(null);
  const [helpOpen, setHelpOpen] = useState(false);
  const closeHelp = useCallback(() => {
    setHelpOpen(false);
  }, []);
  const inputRef = useRef<HTMLInputElement>(null);
  // Ties the visible caption to the input; without it the field announces as
  // an unnamed "edit text" and the checkout cannot be completed by voice or
  // screen reader.
  const fieldId = useId();
  const blocker = checkBlocker({
    value,
    pattern,
    server: { required: serverLabel !== null, id: serverId },
  });
  // Set when the customer presses a button that cannot fire yet. A dimmed
  // control that swallows the click teaches nothing; pressing it should say
  // what is missing. The two blockers the customer can see coming (no package
  // picked, empty sibling server field) are announced without waiting for
  // that press — only "you have not typed the id yet" would be noise before
  // they have tried.
  const [attempted, setAttempted] = useState(false);
  const hint = blocker !== null && (blocker !== "playerId" || attempted) ? blocker : null;

  async function onCheck(): Promise<void> {
    if (blocker !== null) {
      setAttempted(true);
      return;
    }
    // What the answer will be filed under: the brand, the id and the server
    // as they are at the moment of the press, never as they are when it lands.
    // A check that comes back after the customer has retyped is then simply
    // not read back (`currentCheck`), instead of being shown against an id
    // they no longer mean.
    const asked: Question = { brandSlug, playerId: value, serverId };
    latestAsk.current = asked;
    setAsking(asked);
    try {
      // `runPlayerCheck` folds every fault into a `result`, so it cannot
      // reject: this reports at most once, and never throws past the caller.
      const result = await runPlayerCheck(brandSlug, { playerId: value, serverId });
      // Reported straight from here, not from an effect — this verdict is the
      // one thing Pay reasons about, and an effect lands a commit later — and
      // only if this press is still the latest. Two checks can be in flight
      // (editing the id re-enables the button), and if the newer one answers
      // first, letting the older one report would file *its* question over the
      // fresh verdict: the pill would vanish and Pay re-block with the id on
      // screen unchanged and nothing to explain it.
      if (latestAsk.current === asked) onCheckResult({ ...asked, result });
    } finally {
      // By identity, so a check started after this one keeps its own spinner:
      // only the press that is still the latest one clears it.
      if (latestAsk.current === asked) latestAsk.current = null;
      setAsking((current) => (current === asked ? null : current));
    }
  }
  function edit(): void {
    // Explicitly drops the verdict rather than leaning on the id changing:
    // the customer is about to retype, and until they do the id is unchanged,
    // so nothing else would clear it.
    onCheckResult(null);
    requestAnimationFrame(() => inputRef.current?.focus());
  }

  // Confirmed-hit pill — nickname + the id it resolved to.
  if (check?.status === "valid") {
    return (
      <div>
        <FieldLabel label={label} required={required} />
        <div className="rounded-btn flex items-center gap-2.5 border border-emerald-500/40 bg-emerald-500/[0.06] py-1.5 pl-1.5 pr-4">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-400">
            <Check size={17} strokeWidth={3} />
          </span>
          <div className="min-w-0 flex-1 leading-tight">
            <div className="truncate text-[14px] font-bold">{check.name}</div>
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
  if (check?.status === "invalid") {
    return (
      <div>
        <FieldLabel label={label} required={required} />
        <div className="rounded-btn flex items-center gap-2.5 border border-red-500/40 bg-red-500/[0.06] py-1.5 pl-1.5 pr-4">
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
        {siblingHint && (
          <Link
            href={siblingHint.href}
            className="text-primary mt-2 inline-block text-[13px] underline-offset-4 hover:underline"
          >
            {t("checkTryRegion", { name: siblingHint.name })}
          </Link>
        )}
      </div>
    );
  }

  // Idle / loading / our-or-provider fault: show the input + check button.
  return (
    <div>
      <FieldLabel label={label} required={required} htmlFor={fieldId} />
      <div className="flex flex-col gap-2.5 sm:flex-row sm:items-center">
        <div className="relative min-w-0 flex-1">
          <input
            id={fieldId}
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
            className={`border-border-2 bg-card focus:border-primary/60 placeholder:text-tx-dim rounded-btn h-[46px] w-full border pl-4 text-[15px] outline-none transition ${help ? "pr-11" : "pr-4"}`}
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
          // `aria-disabled`, not `disabled`: a real `disabled` button drops the
          // click, so there is no moment at which to explain why nothing
          // happens. This one still looks inert and stays out of the tab order
          // for the same reason it always did, but pressing it answers.
          aria-disabled={blocker !== null}
          disabled={checking}
          onClick={() => void onCheck()}
          // Neutral on purpose: this is advisory (a failed lookup never blocks
          // checkout), and in lime it read as the main action while the real
          // CTA below sat dimmed. The green confirmation pill still marks a
          // successful check.
          className={`border-border-2 text-tx-mute hover:border-tx-dim hover:text-foreground hover:bg-muted rounded-btn inline-flex h-[46px] shrink-0 items-center justify-center gap-2 border px-5 text-[14px] font-semibold transition disabled:pointer-events-none disabled:opacity-40 ${
            blocker !== null ? "opacity-40" : ""
          }`}
        >
          {checking && <Loader2 size={16} className="animate-spin" />}
          {checking ? t("checking") : t("check")}
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
      {checkUnavailable(check) && (
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
      {hint && (
        <p role="status" className="text-tx-dim mt-2 px-1 text-[13px]">
          {hint === "serverId"
            ? t("checkNeedsServer", { label: serverLabel ?? "" })
            : t("checkNeedsId", { label })}
        </p>
      )}
    </div>
  );
}

/**
 * A plain (non-checkable) required field — text/email/number input or a
 * select. `help_text` used to render as an always-visible paragraph under
 * the control; it's now a "Где найти?" pill next to the label that opens
 * the same `WhereToFindModal` the checkable id field uses, so a select like
 * "Сервер" doesn't push three lines of copy under every field on the page.
 */
function PlainField({
  type,
  required,
  value,
  onChange,
  labelText,
  placeholder,
  help,
  options,
  t,
}: {
  type: FormField["type"];
  required: boolean;
  value: string;
  onChange: (v: string) => void;
  labelText: string;
  placeholder: string;
  help: string | null;
  options: { value: string; text: string }[];
  t: (key: string, values?: Record<string, string>) => string;
}) {
  const [helpOpen, setHelpOpen] = useState(false);
  const fieldId = useId();

  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <label htmlFor={fieldId} className="text-tx-mute text-[13px] font-semibold">
          {labelText}
          {required && <span className="text-primary"> *</span>}
        </label>
        {help && (
          <button
            type="button"
            onClick={() => {
              setHelpOpen(true);
            }}
            aria-haspopup="dialog"
            className="text-tx-dim hover:text-primary inline-flex shrink-0 items-center gap-1 text-[12px] font-medium transition"
          >
            <Info size={12} />
            {t("whereToFindGeneric")}
          </button>
        )}
      </div>
      {type === "select" ? (
        <select
          id={fieldId}
          required={required}
          aria-required={required}
          value={value}
          onChange={(e) => {
            onChange(e.target.value);
          }}
          className="border-border bg-card focus:border-primary rounded-btn h-[46px] w-full border px-3.5 text-[15px] outline-none transition"
        >
          <option value="">—</option>
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.text}
            </option>
          ))}
        </select>
      ) : (
        <input
          id={fieldId}
          type={type === "number" ? "text" : type}
          inputMode={type === "number" ? "numeric" : undefined}
          required={required}
          aria-required={required}
          value={value}
          placeholder={placeholder}
          onChange={(e) => {
            onChange(e.target.value);
          }}
          className="border-border bg-card focus:border-primary rounded-btn h-[46px] w-full border px-3.5 text-[15px] outline-none transition"
        />
      )}
      {help && (
        <WhereToFindModal
          open={helpOpen}
          title={t("whereToFindTitle", { label: labelText })}
          body={help}
          closeLabel={t("close")}
          onClose={() => {
            setHelpOpen(false);
          }}
        />
      )}
    </div>
  );
}

/**
 * Caption above a checkout field.
 *
 * `htmlFor` turns it into a real `<label>`. Without it this stays a `<span>`,
 * which is correct for the two states where it captions a resolved-nickname
 * pill rather than an input — a `<label>` pointing at nothing is worse than
 * none. The input states must always pass it: a field announced as "edit text"
 * with no name is a field a screen-reader user cannot fill in.
 */
function FieldLabel({
  label,
  required,
  htmlFor,
}: {
  label: string;
  required: boolean;
  htmlFor?: string;
}) {
  const className = "text-tx-dim mb-2 block text-[12px] font-semibold uppercase tracking-[0.08em]";
  const content = (
    <>
      {label}
      {required && <span className="text-primary"> *</span>}
    </>
  );
  return htmlFor ? (
    <label htmlFor={htmlFor} className={className}>
      {content}
    </label>
  ) : (
    <span className={className}>{content}</span>
  );
}

/**
 * The free-amount field of a product that carries a variable-amount SKU: the
 * customer types how much they want instead of picking a denomination.
 *
 * It renders ABOVE the package grid, and the two are mutually exclusive — a
 * package tap clears the field (via the parent's `skuId` effect), typing in the
 * field selects this SKU. `selected` is what makes that visible, so the card
 * carries the same lime accent an active package tile does.
 *
 * Everything on screen is denominated in the SKU's own `amount_unit` (Stars)
 * when it has one, and in dollars when it doesn't (the Steam wallet, where the
 * dollar IS the unit). Dollars stay internal for a unit-priced SKU: quoting a
 * rate at someone buying Stars answers a question they did not ask, which is
 * why there is no rate, fee or limit line here — only what they typed, what it
 * costs, and how far the field can go.
 *
 * `sku.display_price` is the localised price of ONE dollar (its `price_usd`
 * is a `1`-placeholder) — `null` means the FX trust gate rejected the live
 * rate, so the product isn't sellable right now and we render that instead
 * of a price of zero.
 */
function VariableAmountCard({
  sku,
  value,
  selected,
  onChange,
  onFocus,
  locale,
  t,
}: {
  sku: SkuOut;
  value: string;
  /** True while this SKU is the current selection — drives the active accent. */
  selected: boolean;
  onChange: (v: string) => void;
  onFocus: () => void;
  locale: string;
  t: (key: string, values?: Record<string, string>) => string;
}) {
  const amountId = useId();
  const rate = sku.display_price;
  if (!rate) {
    return (
      <div className="border-border bg-card text-tx-mute rounded-lg border border-dashed p-6 text-center text-sm">
        {t("priceUnavailable")}
      </div>
    );
  }
  const rateUzs = Number(rate.amount); // one dollar, in UZS
  const minUsd = sku.min_amount_usd != null ? Number.parseFloat(sku.min_amount_usd) : 1;
  const maxUsd = sku.max_amount_usd != null ? Number.parseFloat(sku.max_amount_usd) : 0;
  // Non-null when the field is denominated in something else — stars, say.
  // Everything the customer sees is then in that unit; only the wire is USD.
  const perUsd = unitsPerUsd(sku);
  const unit = perUsd !== null ? (sku.amount_unit ?? "") : null;
  const min = perUsd !== null ? boundToUnits(minUsd, perUsd, "min") : minUsd;
  const max = perUsd !== null ? boundToUnits(maxUsd, perUsd, "max") : maxUsd;
  const parsed = parseAmount(value);
  const error =
    parsed !== null
      ? perUsd !== null
        ? unitAmountError(parsed, min, max)
        : amountError(parsed, min, max)
      : null;
  const total =
    parsed !== null ? (perUsd !== null ? toUsd(parsed, perUsd) : parsed) * rateUzs : null;
  /** A bound as the customer reads it: a plain unit count, or a dollar sum. */
  const bound = (n: number) =>
    unit ? n.toLocaleString(locale) : formatMoney(n.toFixed(2), "USD", locale);
  const errorMessage =
    error === "below"
      ? t("amountBelow", { min: unit ? `${bound(min)} ${unit}` : bound(min) })
      : error === "above"
        ? t("amountAbove", { max: unit ? `${bound(max)} ${unit}` : bound(max) })
        : error === "precision"
          ? // A fraction of a star does not exist, which is a different
            // complaint from "more than two decimal places" on a dollar amount.
            unit
            ? t("amountWhole")
            : t("amountPrecision")
          : null;

  // Hard-cap the typed amount at the SKU's max ($300 for Steam, 50 000 Stars):
  // the field would otherwise accept a number the server is bound to refuse.
  const handleAmountChange = (raw: string) => {
    const n = parseAmount(raw);
    onChange(n !== null && n > max ? String(max) : raw);
  };

  return (
    <div className="border-border bg-card rounded-xl border p-4 transition sm:p-5">
      <label htmlFor={amountId} className="text-tx-mute mb-2 block text-[13px]">
        {unit ? t("amountUnitLabel", { unit }) : t("amountOwn")}
      </label>
      <div
        className={`rounded-btn bg-card-2 flex items-center gap-2 border px-3.5 transition ${
          selected ? "border-primary" : "border-border focus-within:border-primary"
        }`}
      >
        {/* The dollar SKU (Steam) carries its unit as a prefix, the way money is
            written; a named unit reads as a suffix after the count. Both are
            decorative — the label above already names the unit. */}
        {unit === null && (
          <span className="text-tx-dim text-[18px] font-bold" aria-hidden="true">
            $
          </span>
        )}
        <input
          id={amountId}
          aria-invalid={errorMessage ? true : undefined}
          aria-describedby={errorMessage ? `${amountId}-error` : undefined}
          type="text"
          // Whole units only (half a star does not exist) → the numeric pad;
          // dollars take cents, so they keep the decimal one.
          inputMode={unit ? "numeric" : "decimal"}
          value={value}
          onFocus={onFocus}
          onChange={(e) => {
            handleAmountChange(e.target.value);
          }}
          // A plain number, not "e.g. 10": the placeholder doubles as the
          // smallest amount the field accepts. Dollars keep today's wording.
          placeholder={unit ? String(min) : t("amountPlaceholder")}
          // 52px tall and 20px of type: above the 44px tap target, and above
          // the 16px below which iOS Safari zooms the page on focus.
          className="h-[52px] min-w-0 flex-1 bg-transparent text-[20px] font-extrabold outline-none"
        />
        {unit !== null && (
          <span className="text-tx-dim shrink-0 text-[15px] font-semibold" aria-hidden="true">
            {unit}
          </span>
        )}
      </div>
      {/* The only two numbers under the field: how far it can go, and what the
          typed amount costs. No rate, no fee, no margin copy — see the
          component docstring. */}
      <div className="text-tx-dim mt-2 flex items-center justify-between gap-3 text-[12px]">
        <span>{t("amountRange", { min: bound(min), max: bound(max) })}</span>
        {total !== null && (
          <span className="text-foreground shrink-0 font-mono text-[13px] font-semibold tabular-nums">
            {formatUzs(locale, Math.round(total))}
          </span>
        )}
      </div>
      {/* Tied to the input: a rejected amount that only exists as loose text
          below the card is invisible to anyone who reached the field by
          keyboard or screen reader. */}
      {errorMessage && (
        <p id={`${amountId}-error`} className="mt-2 text-[12px] text-[#FF6B6B]">
          {errorMessage}
        </p>
      )}
    </div>
  );
}

/**
 * The free-typed-quantity field for a genuine unit SKU (Telegram Stars sold
 * as `{ sku_id, qty }`) — the sibling of `VariableAmountCard` for a SKU whose
 * bounds are already whole units (`min_qty`/`max_qty`), not a USD range to
 * convert. No `unitsPerUsd`/`toUsd` here: what's typed IS the quantity, and
 * `sku.display_price` prices it directly via `packagePrice` — see that
 * function's docstring for why there's no volume-discount band like
 * `tierPrice`'s packages.
 *
 * Renders above the package tiles the same way `VariableAmountCard` renders
 * above `fixedSkus` — typing and tapping a tile both just set this SKU's
 * selection and its quantity.
 */
function UnitPackCard({
  sku,
  value,
  selected,
  onChange,
  onFocus,
  locale,
  t,
}: {
  sku: SkuOut;
  value: string;
  selected: boolean;
  onChange: (v: string) => void;
  onFocus: () => void;
  locale: string;
  t: (key: string, values?: Record<string, string>) => string;
}) {
  const amountId = useId();
  const rate = sku.display_price;
  const unit = sku.amount_unit ?? "";
  const min = sku.min_qty ?? 0;
  const max = sku.max_qty ?? 0;
  if (!rate) {
    return (
      <div className="border-border bg-card text-tx-mute rounded-lg border border-dashed p-6 text-center text-sm">
        {t("priceUnavailable")}
      </div>
    );
  }
  const parsed = parseAmount(value);
  const error = parsed !== null ? unitAmountError(parsed, min, max) : null;
  const total = parsed !== null ? packagePrice(parsed, Number(rate.amount)) : null;
  const bound = (n: number) => n.toLocaleString(locale);
  const errorMessage =
    error === "below"
      ? t("amountBelow", { min: `${bound(min)} ${unit}` })
      : error === "above"
        ? t("amountAbove", { max: `${bound(max)} ${unit}` })
        : error === "precision"
          ? t("amountWhole")
          : null;

  // Same hard-cap as `VariableAmountCard`: never let the field hold a number
  // the server is bound to refuse.
  const handleAmountChange = (raw: string) => {
    const n = parseAmount(raw);
    onChange(n !== null && n > max ? String(max) : raw);
  };

  return (
    <div className="border-border bg-card rounded-xl border p-4 transition sm:p-5">
      <label htmlFor={amountId} className="text-tx-mute mb-2 block text-[13px]">
        {t("amountUnitLabel", { unit })}
      </label>
      <div
        className={`rounded-btn bg-card-2 flex items-center gap-2 border px-3.5 transition ${
          selected ? "border-primary" : "border-border focus-within:border-primary"
        }`}
      >
        <input
          id={amountId}
          aria-invalid={errorMessage ? true : undefined}
          aria-describedby={errorMessage ? `${amountId}-error` : undefined}
          type="text"
          inputMode="numeric"
          value={value}
          onFocus={onFocus}
          onChange={(e) => {
            handleAmountChange(e.target.value);
          }}
          placeholder={String(min)}
          className="h-[52px] min-w-0 flex-1 bg-transparent text-[20px] font-extrabold outline-none"
        />
        <span className="text-tx-dim shrink-0 text-[15px] font-semibold" aria-hidden="true">
          {unit}
        </span>
      </div>
      <div className="text-tx-dim mt-2 flex items-center justify-between gap-3 text-[12px]">
        <span>{t("amountRange", { min: bound(min), max: bound(max) })}</span>
        {total !== null && (
          <span className="text-foreground shrink-0 font-mono text-[13px] font-semibold tabular-nums">
            {formatUzs(locale, Math.round(total))}
          </span>
        )}
      </div>
      {errorMessage && (
        <p id={`${amountId}-error`} className="mt-2 text-[12px] text-[#FF6B6B]">
          {errorMessage}
        </p>
      )}
    </div>
  );
}

/**
 * Quick-pick tiles for a unit SKU, built from `visibleStarPackages` — not
 * separate SKUs (there are none): tapping one just sets `UnitPackCard`'s
 * quantity, the same field both render into.
 */
/**
 * The pack thumbnail: one star image, piled up.
 *
 * Every tile used to carry the same single star, so the art said nothing about
 * size and the number underneath did all the work. Copies of the *same* asset
 * offset behind each other give the thumbnail a second reading of the pack
 * size — no new artwork, and it scales to whatever packs the list holds.
 *
 * Drawn back-to-front so the front copy sits on top without z-index juggling,
 * and each one further back is smaller, dimmer and nudged up-left, which is
 * how a stack of physical things actually recedes. `aria-hidden` on the lot:
 * the pile is a restatement of the label beside it, and a screen reader
 * announcing four images called "" would be noise.
 */
function StarStack({ src, layers }: { src: string | null; layers: number }) {
  if (!src) return <span className="rounded-btn block h-12 w-12" />;
  // Back-to-front: index 0 renders last and sits on top.
  const depths = Array.from({ length: layers }, (_, i) => layers - 1 - i);
  return (
    <span className="rounded-btn relative block h-12 w-12" aria-hidden="true">
      {depths.map((depth) => (
        <Image
          key={depth}
          src={src}
          alt=""
          fill
          unoptimized={!isOptimizable(src)}
          sizes="48px"
          className="object-contain"
          style={{
            transform: `translate(${String(depth * -14)}%, ${String(depth * -10)}%) scale(${String(1 - depth * 0.09)})`,
            // Darkened rather than faded. Fading a gold star toward a dark
            // tile turns it grey — the pile stopped reading as stars at all.
            // Brightness keeps the hue and still recedes, which is what an
            // overlapped object actually does.
            filter: `brightness(${String(1 - depth * 0.18)})`,
            opacity: 1 - depth * 0.08,
          }}
        />
      ))}
    </span>
  );
}

function UnitPackTiles({
  sku,
  qty,
  onPick,
  locale,
  fallbackImage,
}: {
  sku: SkuOut;
  /** The field's currently parsed quantity, or `null` — used only to mark a
   *  tile active when it matches what's typed. */
  qty: number | null;
  onPick: (n: number) => void;
  locale: string;
  /** Product art when the unit SKU itself has no `image_url` — same fallback
   *  the fixed-SKU grid uses. */
  fallbackImage: string | null;
}) {
  const packs = visibleStarPackages(sku.min_qty ?? 0, sku.max_qty ?? 0);
  if (packs.length === 0) return null;
  const rate = sku.display_price ? Number(sku.display_price.amount) : null;
  const img = sku.image_url ?? fallbackImage;
  return (
    <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
      {packs.map((n) => {
        const active = qty === n;
        const price = rate !== null ? packagePrice(n, rate) : null;
        return (
          <button
            key={n}
            type="button"
            aria-pressed={active}
            onClick={() => {
              onPick(n);
            }}
            className={`focus-visible:ring-primary focus-visible:ring-offset-bg relative flex flex-col items-start gap-2 rounded-lg border p-3 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 ${
              active
                ? "border-primary bg-primary/10"
                : "border-border bg-card hover:border-border-2"
            }`}
          >
            <StarStack src={img} layers={starLayers(n)} />
            <span className="font-display block text-[14px] font-semibold tracking-[-0.01em]">
              {n.toLocaleString(locale)} {sku.amount_unit}
            </span>
            {price !== null && (
              <span className="text-foreground font-mono text-[13.5px] font-semibold tabular-nums">
                {formatUzs(locale, Math.round(price))}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

export function PurchasePanel({
  products,
  locale,
  regionSibling,
  children,
}: {
  products: ProductDetail[];
  locale: string;
  /** The other region's brand, when this brand is one half of a `<slug>` /
   *  `<slug>-ru` pair (see `@/lib/region-sibling`). `null`/absent for every
   *  other brand — the field then renders no hint at all. */
  regionSibling?: { slug: string; name: string } | null;
  /** Server-rendered sections (how-to, about, FAQ) placed in the left column
   *  below the pick, so the sticky order sidebar scrolls alongside them. */
  children?: ReactNode;
}) {
  const t = useTranslations("web.store");
  // Resolved once here (not in the field) because only the panel already
  // carries `locale` for `pathFor` — the field stays locale-agnostic.
  const siblingHint = regionSibling
    ? { href: pathFor(locale, `/store/${regionSibling.slug}`), name: regionSibling.name }
    : null;
  const router = useRouter();
  const { user, isLoading: authLoading } = useAuth();
  // Nothing is preselected on a grid the buyer still has to choose from. The
  // panel used to open on the middle SKU — `floor(len/2)`, i.e. a position in
  // the list, not a popularity — so a PUBG visitor's first number was "Ваш
  // заказ 449 632 UZS" sitting next to a "от 12 609 UZS" chip, an anchor 36×
  // the entry price. A product with a single SKU, or a variable-amount one
  // (Steam, where the SKU carries the amount field), has nothing to choose and
  // stays selected.
  const primarySkus = products[0]?.skus ?? [];
  const primaryIsVariable =
    primarySkus.length > 0 && primarySkus.every((s) => s.variable_amount ?? false);
  const [skuId, setSkuId] = useState<string | undefined>(() => {
    // Auto-select only when there is nothing to choose. A single sold-out SKU
    // must not become the selection: the panel would look ready to pay and
    // then fail at the button, since the API refuses out-of-stock lines.
    if (!(primaryIsVariable || primarySkus.length === 1)) return undefined;
    const only = primarySkus[0];
    return only && only.in_stock !== false ? only.id : undefined;
  });
  const [form, setForm] = useState<Record<string, string>>({});
  // Each checkable field's latest player-check verdict, reported by
  // `CheckablePlayerField` from the check itself and filed under the product +
  // id it was asked about. Lets `canPay` require a real verification instead
  // of a filled-in box — a mistyped id otherwise redirects straight to the
  // acquirer, and the refund policy says that's unrecoverable. Read back only
  // through `currentFieldCheck`, never directly: a stored verdict outlives the
  // question it answers, and answering the wrong question is the whole failure
  // mode this gate exists to prevent.
  const [checkResults, setCheckResults] = useState<Record<string, PlayerCheckVerdict | null>>({});
  const [email, setEmail] = useState("");
  // Signed-in customers were shown the same required email field and had what
  // they typed dropped on the way out, so they were asked for an address and
  // then mailed nothing. Prefill it from the account — their delivery address
  // if they have set one, else the address they sign in with — and leave it
  // editable, because one order going somewhere else is a normal thing to want.
  // Only seeds an untouched field: re-running on every `user` change would
  // overwrite what they are in the middle of typing.
  const [emailTouched, setEmailTouched] = useState(false);
  useEffect(() => {
    if (emailTouched || email !== "") return;
    const fromAccount = user?.delivery_email ?? user?.email ?? "";
    if (fromAccount) setEmail(fromAccount);
  }, [user, email, emailTouched]);
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
    /** A balance payment is settled already; every other rail still needs the
     *  customer to finish at the acquirer. The copy differs accordingly. */
    paidFromBalance: boolean;
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
    fetch(`${API}/api/v1/payments/providers`, { headers: { "X-Yupay-Surface": SURFACE } })
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
    setMethodId((current) => {
      // The wallet is not in METHODS, so `selectActiveMethodId` cannot find it,
      // falls past its "keep the current one" guard and answers with the first
      // active acquirer instead. A customer who picked "pay from balance"
      // before this fetch landed would have had that swapped for a card
      // without being told. Its readiness is `walletState`, not `providerStatus`.
      if (current === WALLET_METHOD_ID) return current;
      return selectActiveMethodId(METHODS, current, providerStatus) ?? "";
    });
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
  // The account fields belong to the brand's catalogue, not to the price the
  // buyer happens to pick — so they render from the first product until a
  // selection narrows it down. Hanging them off `selProduct` alone meant that
  // removing the default denomination also hid the "ID игрока" field until
  // something was chosen, turning one form into two sequential steps.
  const fieldsProduct = selProduct ?? products[0];
  const fields: FormField[] = fieldsProduct?.required_fields ?? [];
  /** The sibling server field's current value for a checkable field, or `null`
   *  when its `check` names no sibling. One expression, read by the derivation
   *  below and passed to the field as its `serverId` prop: they are the two
   *  halves of one question, and if they ever computed it differently the
   *  verdict would never read back. */
  const serverIdFor = (f: FormField): string | null =>
    f.check?.server_field ? (form[f.check.server_field] ?? null) : null;
  // Keyed by brand: every package of a brand is the same game (ADR-0079), so
  // a verdict survives a package switch and dies only with the id or the
  // server.
  //
  // The single derivation behind both the field's pill and `canPay` below,
  // evaluated in the render that changes either input, so no commit can show
  // a verified pill next to a Pay button the same commit still considers
  // payable.
  const currentFieldCheck = (f: FormField): PlayerCheckResult | null =>
    // The `!f.check` guard is not dead weight: both call sites pre-filter today,
    // but this file is queued for the same extraction the gift panel got, and a
    // field without a check config has no verdict to read back by definition.
    // The mini app's twin carries it; safer to agree than to rely on callers.
    !f.check
      ? null
      : currentCheck(
          checkResults[f.key],
          fieldsProduct?.brand.slug ?? "",
          form[f.key] ?? "",
          serverIdFor(f),
        );
  // A gift card has no account field at all — the "зачисление на аккаунт"
  // copy (and the attestation checkbox below) only make sense when there's
  // one to fill in.
  const accountRequired = fields.length > 0;
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
  // Non-null when the customer types units rather than dollars (Telegram
  // Stars). The typed number is then a unit count, and only the wire stays
  // in dollars.
  const perUsd = selSku ? unitsPerUsd(selSku) : null;
  const amountAsUsd =
    parsedAmount === null ? null : perUsd !== null ? toUsd(parsedAmount, perUsd) : parsedAmount;
  const variableAmountErr =
    selSkuVariable && parsedAmount !== null
      ? perUsd !== null
        ? unitAmountError(
            parsedAmount,
            boundToUnits(minUsd, perUsd, "min"),
            boundToUnits(maxUsd, perUsd, "max"),
          )
        : amountError(parsedAmount, minUsd, maxUsd)
      : null;
  // Client-side total for display only — the server recomputes the
  // authoritative price from `amount_usd` at checkout.
  // Packages the typed amount is priced from, in the currency being shown —
  // so a per-currency override on a pack carries through to the field.
  const tierPacks = useMemo(
    () =>
      (products[0]?.skus ?? [])
        .filter((s) => !(s.variable_amount ?? false) && s.units != null && s.display_price)
        .map((s) => ({ units: s.units ?? 0, price: Number(s.display_price?.amount ?? 0) })),
    [products],
  );
  const variableTotal = !selSkuVariable
    ? null
    : parsedAmount === null
      ? null
      : // Priced from the packages when there are any — the page must show what
        // checkout will bill, and that is `orders.service.tier_price_usd`.
        tierPacks.length > 0
        ? tierPrice(parsedAmount, tierPacks)
        : amountAsUsd !== null && variableRate
          ? amountAsUsd * Number(variableRate.amount)
          : null;
  // Gates the CTA for a variable-amount SKU: a live rate (the FX trust gate
  // didn't reject it) and a parsed, in-bounds, two-decimals-or-fewer amount.
  const variableAmountOk =
    !selSkuVariable ||
    (variableRate !== null && parsedAmount !== null && variableAmountErr === null);
  /** A dollar bound as the buyer reads it — a unit count for a unit-priced SKU,
   *  where quoting "$0.77" back at someone buying Stars is a non-answer. */
  const boundLabel = (usd: number, edge: "min" | "max"): string =>
    perUsd !== null
      ? `${boundToUnits(usd, perUsd, edge).toLocaleString(locale)} ${selSku?.amount_unit ?? ""}`
      : formatMoney(usd.toFixed(2), "USD", locale);

  // Same shape as the variable-amount block above, but for a genuine unit SKU
  // (Telegram Stars sold as `{ sku_id, qty }`, no `amount_usd`): the
  // typed/tapped number IS the quantity, `min_qty`/`max_qty` are already
  // whole units, and there is no `unitsPerUsd`/`toUsd` conversion to run.
  const selSkuUnit = selSku ? isUnitSku(selSku) : false;
  const unitRate = selSkuUnit ? (selSku?.display_price ?? null) : null;
  const parsedQty = selSkuUnit ? parseAmount(amountInput) : null;
  const qtyMin = selSku?.min_qty ?? 0;
  const qtyMax = selSku?.max_qty ?? 0;
  const qtyErr =
    selSkuUnit && parsedQty !== null ? unitAmountError(parsedQty, qtyMin, qtyMax) : null;
  // `packagePrice` — a flat per-unit rate, never a guessed one.
  const qtyTotal =
    selSkuUnit && parsedQty !== null && unitRate
      ? packagePrice(parsedQty, Number(unitRate.amount))
      : null;
  // Gates the CTA for a unit SKU: a live rate and a parsed, in-bounds, whole quantity.
  const qtyOk = !selSkuUnit || (unitRate !== null && parsedQty !== null && qtyErr === null);

  // The heading over the whole choice. A free amount alongside packages is
  // "pick one or type one"; a lone free amount (Steam) or a lone unit SKU
  // (Stars, once it stops being `variable_amount`) keeps its own title.
  const hasVariableSku = products.some((p) => p.skus.some((s) => s.variable_amount ?? false));
  const hasUnitSku = products.some((p) => p.skus.some((s) => isUnitSku(s)));
  const hasFixedSku = products.some((p) =>
    p.skus.some((s) => !(s.variable_amount ?? false) && !isUnitSku(s)),
  );
  const chooseTitle =
    !hasVariableSku && !hasUnitSku
      ? t("packsTitle")
      : hasFixedSku
        ? t("pickPackOrAmount")
        : t("amountTitle");

  // The same figure `selectedPriceLabel` formats, kept numeric so the wallet
  // tile compares against exactly what checkout will bill rather than parsing
  // a currency string back out.
  const orderTotalUzs: number | null = !selSku
    ? null
    : selSkuVariable
      ? variableTotal
      : selSkuUnit
        ? qtyTotal
        : selSku.display_price
          ? Number(selSku.display_price.amount)
          : null;

  // The cart line, built once. The promo preview and the order that follows
  // must price the *same* thing — two places assembling this is exactly how a
  // quote and its order come to disagree.
  const orderItem = useMemo(
    () =>
      !selSku
        ? null
        : {
            sku_id: selSku.id,
            // A unit SKU (Telegram Stars) is bought as a real quantity, not the
            // usual single line + `amount_usd`.
            qty: selSkuUnit ? (parsedQty ?? 1) : 1,
            fulfillment_data: form,
            ...(selSkuVariable && amountAsUsd !== null
              ? // Always dollars on the wire. Six decimals because one unit is
                // rarely a round cent; the server snaps it back to a whole unit.
                { amount_usd: amountAsUsd.toFixed(perUsd !== null ? 6 : 2) }
              : {}),
          },
    [selSku, selSkuUnit, parsedQty, form, selSkuVariable, amountAsUsd, perUsd],
  );

  // A render-time signal for the promo field. Deliberately *not* the handler's
  // own `isLoggedIn`, which also checks the access token at submit time: that
  // check stays exactly as it was, because it guards the money path.
  const isSignedIn = user !== null;
  const [promo, setPromo] = useState<AppliedPromo | null>(null);
  const [promoDropped, setPromoDropped] = useState(false);

  // Only fetched for signed-in customers: a guest has no wallet, and asking
  // would 401 on every brand page.
  const walletQuery = useQuery({
    queryKey: ["wallet"],
    queryFn: getWallet,
    enabled: user !== null,
    staleTime: 30_000,
  });
  const walletState = walletTile({
    // `isLoading` matters: the access token is memory-only, so a cold load
    // re-mints it and `user` is null for a beat. Treating that as "guest" told
    // signed-in customers to sign in, and opened a login modal if they tapped.
    isLoggedIn: user !== null || authLoading,
    balance: spendableBalance(walletQuery.data?.balances ?? null, WALLET_CURRENCY),
    total: orderTotalUzs,
  });
  const payingFromBalance = methodId === WALLET_METHOD_ID;

  const openLogin = useLoginModal((st) => st.open);
  const queryClient = useQueryClient();

  const emailOk = EMAIL_RE.test(email);
  // A signed-in buyer may leave this blank — 68% of accounts sign in through
  // Telegram or Steam and have no address on file, so `email` seeds to "".
  // What they may not do is pay with something half-typed in it: the server
  // validates `delivery_email` as an address, and an invalid one fails the
  // whole order with a 422 that reads to the buyer as "order not created".
  // Blank is a choice (no mail); malformed is a mistake, and the button says so.
  const deliveryEmailOk = user === null ? emailOk : email === "" || emailOk;
  const fieldsOk = fields.every((f) => !f.required || (form[f.key]?.trim() ?? "") !== "");
  // A checkable field (`f.check`) with something typed that the check has not
  // cleared — never pressed, came back not-found, or answered about an id or a
  // product the field no longer points at (`currentFieldCheck`). A check that
  // could not *run* does not count: see `blocksCheckout`.
  const uncheckedFieldKey = fields.find((f) => {
    if (!f.check) return false;
    const v = (form[f.key] ?? "").trim();
    if (v.length === 0) return false;
    return blocksCheckout(currentFieldCheck(f));
  })?.key;
  const fieldsVerified = uncheckedFieldKey === undefined;
  // Not just "a method id is set" — the selected method's *provider* must
  // currently be `active`. Combined with the reselection effect above, this
  // is the belt-and-suspenders guarantee that Pay can never submit a
  // maintenance/admin-disabled provider (`methodVisibility` fails open while
  // `providerStatus` is still loading, matching the method grid's own render).
  // The balance is not an acquirer: `providerStatus` describes upstream
  // availability, and our own ledger is up whenever the API is. Its readiness
  // is `walletState` instead.
  const selectedProvider = payingFromBalance
    ? WALLET_METHOD_ID
    : METHODS.find((m) => m.id === methodId)?.provider;
  const selectedMethodActive = payingFromBalance
    ? walletState.state === "ready"
    : selectedProvider !== undefined &&
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
    deliveryEmailOk &&
    fieldsOk &&
    fieldsVerified &&
    selectedMethodActive &&
    variableAmountOk &&
    qtyOk &&
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
          ? t("amountBelow", { min: boundLabel(minUsd, "min") })
          : selSkuVariable && variableAmountErr === "above"
            ? t("amountAbove", { max: boundLabel(maxUsd, "max") })
            : selSkuVariable && variableAmountErr === "precision"
              ? // Half a star does not exist; a fraction of a dollar cent does.
                t(perUsd !== null ? "amountWhole" : "amountPrecision")
              : selSkuUnit && unitRate === null
                ? t("priceUnavailable")
                : selSkuUnit && parsedQty === null
                  ? t("amountRequired")
                  : selSkuUnit && qtyErr === "below"
                    ? t("amountBelow", {
                        min: `${qtyMin.toLocaleString(locale)} ${selSku.amount_unit ?? ""}`,
                      })
                    : selSkuUnit && qtyErr === "above"
                      ? t("amountAbove", {
                          max: `${qtyMax.toLocaleString(locale)} ${selSku.amount_unit ?? ""}`,
                        })
                      : selSkuUnit && qtyErr === "precision"
                        ? t("amountWhole")
                        : !deliveryEmailOk
                          ? t("payHintEmail")
                          : !fieldsOk
                            ? t("payHintFields")
                            : !fieldsVerified
                              ? t("payHintVerify")
                              : payingFromBalance && walletState.state === "short"
                                ? t("payFromBalanceShort", {
                                    amount: formatUzs(locale, walletState.missing),
                                  })
                                : null;

  // The price shown in the summary header, the pay button, and the mobile
  // sticky bar. A variable-amount SKU has no fixed `skuPrice` — its total
  // depends on the customer's typed amount, so it's computed from
  // `variableTotal` instead, with the "not for sale" / "not typed yet"
  // states handled explicitly rather than falling back to a placeholder.
  const selectedPriceLabel = !selSku
    ? ""
    : selSkuVariable
      ? variableRate === null
        ? t("priceUnavailable")
        : variableTotal !== null
          ? formatUzs(locale, Math.round(variableTotal))
          : "—"
      : selSkuUnit
        ? unitRate === null
          ? t("priceUnavailable")
          : qtyTotal !== null
            ? formatUzs(locale, Math.round(qtyTotal))
            : "—"
        : skuPrice(locale, selSku);
  // `selectedPriceLabel` holds the full "temporarily unavailable" sentence
  // when the FX trust gate rejected the rate — that sentence belongs on the
  // card/hint, never glued onto "Оплатить" or the mobile summary line.
  const priceUnavailable =
    (selSkuVariable && variableRate === null) || (selSkuUnit && unitRate === null);

  // Nothing in the flow ever asked the buyer to look at what they typed before
  // the money left. `pay()` redirects to the acquirer on the next line, and a
  // mistyped game id is unrecoverable — the refund policy says so.
  const [confirmOpen, setConfirmOpen] = useState(false);

  // A product whose fields the supplier can verify (`f.check`) has already had
  // the id resolved to a nickname. Where it cannot — Genshin and Honkai Star
  // Rail, where the supplier reports "no validation required" — the dialog is
  // the only place a typo can still be caught, so it asks the buyer to attest.
  const hasVerifiableField = fields.some((f) => Boolean(f.check));

  const confirmRows = [
    {
      label: t("confirmItem"),
      value: [selProduct?.name, selSku?.denomination].filter(Boolean).join(" · "),
    },
    ...fields
      .filter((f) => (form[f.key]?.trim() ?? "") !== "")
      .map((f) => ({ label: label(f.label), value: form[f.key] ?? "" })),
  ];

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

      // Built above, so the promo preview and this order price the same cart.
      // `canPay` already guarantees it is non-null by the time we get here.
      if (!orderItem) return;
      // Collected at submit, not at mount: the value that matters is the one in
      // force when the purchase was made. Omitted entirely when the browser
      // yields nothing, so the server stores {} rather than a bag of nulls.
      const hints = collectClientHints();
      const orderBody = {
        currency: "UZS",
        items: [orderItem],
        // `guest_email` is the guest's identity on the order and cannot be
        // set for a signed-in buyer; `delivery_email` is where their mail
        // goes. Sending neither is what left them without their codes.
        // Only when there is one. An absent key means "mail it nowhere"; an
        // empty string is not an address and the server rejects the order over
        // it — which is how a buyer with no address on file got
        // "order not created" instead of a sale.
        ...(isLoggedIn ? (email ? { delivery_email: email } : {}) : { guest_email: email }),
        ...(hints ? { client_hints: hints } : {}),
        // The server resolves this again for itself — the preview above was
        // for display only, so a code that went stale in between yields an
        // order at full price rather than the price the button showed.
        ...(promo ? { affiliate_code: promo.code } : {}),
      };

      const ord = await fetch(`${API}/api/v1/orders`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Accept-Language": locale,
          "Idempotency-Key": crypto.randomUUID(),
          // This is the call that writes `orders.source`. Without it the row
          // records `unknown`, which is what every web order did while the
          // mini app — which sends the header — recorded `miniapp`.
          "X-Yupay-Surface": SURFACE,
          ...auth,
        },
        body: JSON.stringify(orderBody),
      });
      if (!ord.ok) {
        // Mirrors what `apiFetch` does internally (this call is a raw
        // `fetch`, not `apiFetch`) so the RFC 7807 `type` reaches the catch
        // block below the same way it does everywhere else in the app.
        let type: string | undefined;
        try {
          const body: unknown = await ord.json();
          if (body && typeof body === "object" && "type" in body && typeof body.type === "string") {
            type = body.type;
          }
        } catch {
          /* non-JSON or empty error body — leave `type` undefined */
        }
        throw new ApiError(ord.status, "/orders", type);
      }
      const order = (await ord.json()) as { id: string; discount_charged?: string };
      // Authoritative. A code the server refused leaves this at zero, and
      // saying so beats silently charging more than the button promised.
      if (promo && Number(order.discount_charged ?? 0) === 0) {
        setPromoDropped(true);
      }

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
          // Not read here today, but the deposit path already picks Click's
          // per-surface merchant off this header; sending it keeps the two
          // sides of checkout declaring the same thing.
          "X-Yupay-Surface": SURFACE,
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

      // The order exists from here on: record it before anything else can go
      // wrong. Whatever happens to the navigation below, the confirmation
      // screen this renders tells the buyer their order is real and how to
      // reach it — losing a created order silently is the failure this whole
      // path used to cause.
      setDone({
        orderId: order.id,
        intentUrl: intent.intent_url,
        trackHref,
        paidFromBalance: payingFromBalance,
      });
      if (intent.intent_url && provider !== "mock") {
        // Real acquirer → the ORDER PAGE, flagged to open the acquirer from
        // there. Assigning the acquirer URL here left the tab on the product
        // page: a phone opens the bank app instead of navigating, none of our
        // acquirers return the customer to us, and the buyer came back to the
        // product they were about to buy with no sign an order existed — it
        // then expired ten minutes later. See `lib/payment-return.ts`.
        // A wallet payment is settled already and the dev `mock` provider's
        // URL resolves nowhere: both keep the confirmation screen and never
        // touch this path.
        try {
          router.push(withAutoOpen(trackHref));
        } catch {
          // The confirmation screen above is the fallback, links and all.
        }
      }
    } catch (err) {
      // The pre-charge geo veto (ADR-0063) refuses a foreign guest/fresh
      // account before the order is even created — say so specifically
      // rather than the generic "couldn't create the order".
      setError(
        err instanceof ApiError && err.type?.endsWith("/payment-unavailable-abroad")
          ? t("errAbroad")
          : t("payError"),
      );
    } finally {
      // Whatever happened, the balance we hold may no longer be the one the
      // ledger holds: a wallet payment just spent from it, and a failure may
      // have been the server refusing on a balance we had cached as
      // sufficient. Re-read rather than leave the tile promising a payment
      // that will be refused again.
      if (payingFromBalance) {
        void queryClient.invalidateQueries({ queryKey: ["wallet"] });
      }
      setLoading(false);
    }
  }

  if (done) {
    return (
      <div className="border-primary/30 rounded-2xl border bg-[linear-gradient(135deg,hsl(var(--primary)/0.08),hsl(var(--card)))] p-8 text-center">
        <span className="bg-primary mx-auto flex h-14 w-14 items-center justify-center rounded-full">
          <Check size={28} strokeWidth={3} className="text-primary-foreground" />
        </span>
        {/* A wallet payment is already settled by the time this renders — the
            gateway charges inside `create_intent`. The default copy ("перейдите
            к оплате") told someone who had just paid that they had not, and the
            lime CTA it refers to is skipped because there is no `intent_url`. */}
        <h2 className="font-display mt-5 text-2xl font-bold tracking-[-0.02em]">
          {done.paidFromBalance ? t("successPaidTitle") : t("successTitle")}
        </h2>
        <p className="text-tx-mute mx-auto mt-2 max-w-[420px] text-[15px] leading-relaxed">
          {done.paidFromBalance ? t("successPaidNote") : t("successNote")}
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
          {/* One heading over the whole choice, whatever shape it takes: a free
              amount and a package grid are two ways of answering the same
              question, and two competing titles made them look like two steps. */}
          <h2 className="font-display text-xl font-bold tracking-[-0.02em]">{chooseTitle}</h2>
          {products.map((product) => {
            // A variable-amount product (Steam wallet top-up) has exactly one
            // SKU with nothing to pick — the customer types the amount, so
            // there is no denomination grid at all, only the amount field.
            // A product can carry both: Telegram Stars sells eleven packages
            // *and* a free amount, so the field and the grid coexist rather
            // than one replacing the other. Steam has only the field.
            const variableSku = product.skus.find((s) => s.variable_amount ?? false);
            // No pack SKUs sit alongside a unit SKU — see `isUnitSku`'s
            // docstring — so there is at most one per product, unlike
            // `variableSku`+`fixedSkus`.
            const unitSku = product.skus.find((s) => isUnitSku(s));
            const fixedSkus = product.skus.filter(
              (s) => !(s.variable_amount ?? false) && s.id !== unitSku?.id,
            );
            return (
              <div key={product.id} className="mt-5">
                {products.length > 1 && (
                  <div className="text-tx-mute mb-3 text-sm font-semibold">{product.name}</div>
                )}
                {/* The typed amount comes first and the packages read as its
                    presets underneath — the other way round, the field looked
                    like an afterthought below a wall of tiles. */}
                {variableSku && (
                  <VariableAmountCard
                    sku={variableSku}
                    value={skuId === variableSku.id ? amountInput : ""}
                    selected={skuId === variableSku.id}
                    onChange={setAmountInput}
                    onFocus={() => {
                      setSkuId(variableSku.id);
                    }}
                    locale={locale}
                    t={t}
                  />
                )}
                {unitSku && (
                  <>
                    <UnitPackCard
                      sku={unitSku}
                      value={skuId === unitSku.id ? amountInput : ""}
                      selected={skuId === unitSku.id}
                      onChange={setAmountInput}
                      onFocus={() => {
                        setSkuId(unitSku.id);
                      }}
                      locale={locale}
                      t={t}
                    />
                    <UnitPackTiles
                      sku={unitSku}
                      qty={skuId === unitSku.id ? parseAmount(amountInput) : null}
                      onPick={(n) => {
                        setSkuId(unitSku.id);
                        setAmountInput(String(n));
                      }}
                      locale={locale}
                      fallbackImage={product.image_url}
                    />
                  </>
                )}
                {fixedSkus.length > 0 && (
                  <div
                    className={`grid grid-cols-2 gap-3 sm:grid-cols-3 ${variableSku || unitSku ? "mt-3" : ""}`}
                  >
                    {fixedSkus.map((sku) => {
                      const active = sku.id === skuId;
                      const img = sku.image_url ?? product.image_url;
                      // Gift cards run out. `in_stock` is absent on an older
                      // API, so anything but an explicit `false` stays sellable
                      // — a missing field must never empty the shelf.
                      const soldOut = sku.in_stock === false;
                      return (
                        <button
                          key={sku.id}
                          type="button"
                          aria-pressed={active}
                          disabled={soldOut}
                          onClick={() => {
                            setSkuId(sku.id);
                          }}
                          className={`focus-visible:ring-primary focus-visible:ring-offset-bg relative flex flex-col items-start gap-2 rounded-lg border p-3 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 ${
                            soldOut
                              ? "border-border bg-card cursor-not-allowed opacity-45"
                              : active
                                ? "border-primary bg-primary/10"
                                : "border-border bg-card hover:border-border-2"
                          }`}
                        >
                          <span className="rounded-btn relative h-12 w-12 overflow-hidden">
                            {img && (
                              <Image
                                src={img}
                                alt=""
                                fill
                                unoptimized={!isOptimizable(img)}
                                sizes="48px"
                                className="object-contain"
                              />
                            )}
                          </span>
                          {/* The price is what a buyer scans a 12-card grid for; it used to be
                              12px muted mono under a 15px bold name. Names also
                              clamp to two lines, so "Advanced Battle Pass
                              Activation Card" no longer makes its row 370px tall
                              while "100 Bonds" makes the next one 250px, which
                              left the prices at different heights per row. */}
                          <span
                            title={sku.denomination ?? sku.sku_code}
                            className="font-display line-clamp-2 min-h-[2.4em] text-[14px] font-semibold leading-tight tracking-[-0.01em]"
                          >
                            {sku.denomination ?? sku.sku_code}
                          </span>
                          <span className="text-foreground font-mono text-[13.5px] font-semibold tabular-nums">
                            {soldOut ? t("outOfStock") : skuPrice(locale, sku)}
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
                  setEmailTouched(true);
                  setEmail(e.target.value);
                }}
                className="border-border bg-card focus:border-primary rounded-btn h-[46px] w-full border px-3.5 text-[15px] outline-none transition"
              />
            </label>

            {fields.length > 0 && (
              <div className="mt-5 flex flex-col gap-4">
                {fields.map((f) =>
                  f.check && fieldsProduct ? (
                    <CheckablePlayerField
                      key={f.key}
                      brandSlug={fieldsProduct.brand.slug}
                      label={label(f.label)}
                      value={form[f.key] ?? ""}
                      onChange={(v) => {
                        setForm((s) => ({ ...s, [f.key]: v }));
                      }}
                      pattern={f.pattern}
                      required={f.required}
                      serverId={serverIdFor(f)}
                      serverLabel={
                        f.check.server_field
                          ? label(fields.find((x) => x.key === f.check?.server_field)?.label) ||
                            null
                          : null
                      }
                      help={f.help_text ? label(f.help_text) : null}
                      placeholder={f.placeholder ? label(f.placeholder) : t("playerIdPlaceholder")}
                      check={currentFieldCheck(f)}
                      onCheckResult={(verdict) => {
                        // A plain overwrite: this fires from the check handler
                        // and from «Изменить», never from a render-keyed
                        // effect, so it cannot feed itself a new render.
                        setCheckResults((prev) => ({ ...prev, [f.key]: verdict }));
                      }}
                      siblingHint={siblingHint}
                      t={t}
                    />
                  ) : (
                    <PlainField
                      key={f.key}
                      type={f.type}
                      required={f.required}
                      value={form[f.key] ?? ""}
                      onChange={(v) => {
                        setForm((s) => ({ ...s, [f.key]: v }));
                      }}
                      labelText={label(f.label)}
                      placeholder={label(f.placeholder)}
                      help={f.help_text ? label(f.help_text) : null}
                      options={
                        f.options?.map((o) => ({ value: o.value, text: label(o.label) })) ?? []
                      }
                      t={t}
                    />
                  ),
                )}
              </div>
            )}

            <div className="mt-5">
              <span className="text-tx-mute mb-2 block text-[13px] font-semibold">
                {t("paymentTitle")}
              </span>
              {!anyMethodVisible && (
                <p className="border-border bg-card text-tx-dim rounded-btn border px-3 py-3 text-[13px]">
                  {t("paymentNone")}
                </p>
              )}
              {/* Full width, above the acquirer grid: this tile carries a
                  balance and a status line, and squeezing that into a third of
                  the row is what made the grid go ragged when an acquirer was
                  down. It also separates "your own money" from "a card". */}
              <button
                type="button"
                // Only a toggle when there is something to toggle: in the
                // guest state this button signs you in, and announcing it as
                // "not pressed" describes a choice that is not on offer.
                aria-pressed={walletState.state === "guest" ? undefined : payingFromBalance}
                disabled={walletState.state !== "ready" && walletState.state !== "guest"}
                onClick={() => {
                  if (walletState.state === "guest") {
                    openLogin();
                    return;
                  }
                  setMethodId(WALLET_METHOD_ID);
                }}
                className={`focus-visible:ring-primary focus-visible:ring-offset-bg rounded-btn mb-2 flex w-full items-center gap-3 border px-3 py-3 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 disabled:cursor-not-allowed ${
                  payingFromBalance && walletState.state === "ready"
                    ? "border-primary bg-primary/10"
                    : "border-border bg-card hover:border-border-2"
                }`}
              >
                <span
                  className={`bg-muted flex h-9 w-9 shrink-0 items-center justify-center rounded-md ${
                    walletState.state === "ready" || walletState.state === "guest"
                      ? "text-primary"
                      : "text-tx-dim"
                  }`}
                >
                  <WalletMark size={18} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-[13px] font-semibold">{t("payFromBalance")}</span>
                  <span className="text-tx-dim block text-[12px]">
                    {walletState.state === "guest"
                      ? t("payFromBalanceGuest")
                      : walletState.state === "short"
                        ? t("payFromBalanceShort", {
                            amount: formatUzs(locale, walletState.missing),
                          })
                        : walletState.state === "ready"
                          ? formatUzs(locale, Math.round(walletState.balance))
                          : walletState.state === "noTotal"
                            ? t("payFromBalanceUnknown")
                            : t("payFromBalanceLoading")}
                  </span>
                </span>
              </button>

              {/* "Не хватает 45 000" is a fact; this is what to do about it.
                  A new tab so the typed player id and the chosen package
                  survive the trip. */}
              {walletState.state === "short" && (
                <Link
                  href={pathFor(locale, "/account/wallet/top-up")}
                  target="_blank"
                  rel="noreferrer"
                  className="text-primary hover:text-primary-2 mb-2 inline-flex items-center gap-1 text-[13px] font-semibold"
                >
                  {t("payFromBalanceTopUp")}
                  <ArrowUpRight size={14} />
                </Link>
              )}

              <div className="grid grid-cols-3 gap-2">
                {METHODS.map((m) => {
                  // Absent from the providers response → admin-disabled, not
                  // offered at all. `maintenance` still renders, but greyed
                  // out and non-clickable via the native `disabled` attribute.
                  const visibility = methodVisibility(m.provider, providerStatus);
                  if (visibility === "hidden") return null;
                  const disabled = visibility === "maintenance";
                  const active = !disabled && m.id === methodId;
                  const statusId = `pay-method-status-${m.id}`;
                  return (
                    <button
                      key={m.id}
                      type="button"
                      // Kept as the bare provider name: the status rides
                      // `aria-describedby` instead, so the accessible name of a
                      // tile doesn't change when an acquirer goes down.
                      aria-label={m.name}
                      aria-pressed={active}
                      aria-describedby={disabled ? statusId : undefined}
                      title={disabled ? t("paymentMaintenance") : undefined}
                      disabled={disabled}
                      onClick={() => {
                        setMethodId(m.id);
                      }}
                      className={`focus-visible:ring-primary focus-visible:ring-offset-bg rounded-btn relative flex flex-col items-center justify-center gap-1 overflow-hidden border px-3 py-3 transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 disabled:cursor-not-allowed ${
                        disabled
                          ? "border-border bg-card"
                          : active
                            ? "border-primary bg-primary/10"
                            : "border-border bg-card hover:border-border-2"
                      }`}
                    >
                      {/* Overlaid, not stacked: a third line of text inside the
                          tile grew this one taller than its neighbours, so the
                          whole row went ragged whenever an acquirer was down.
                          A strip pinned to the top edge stays out of the flow
                          and, unlike a floating pill, clears the mark below it
                          instead of covering it. */}
                      {disabled && (
                        <span
                          id={statusId}
                          className="border-border bg-bg/95 text-tx-dim absolute inset-x-0 top-0 z-10 border-b py-[3px] text-center text-[9px] font-bold uppercase leading-none tracking-[0.06em]"
                        >
                          {t("paymentMaintenanceShort")}
                        </span>
                      )}
                      <span
                        className={`flex h-9 w-9 shrink-0 items-center justify-center overflow-hidden rounded-md ${
                          disabled ? "opacity-60 grayscale" : ""
                        }`}
                      >
                        <Image
                          src={m.icon}
                          alt=""
                          width={m.w}
                          height={m.h}
                          className="h-full w-full object-cover"
                        />
                      </span>
                      <span
                        className={`text-[13px] font-semibold ${
                          disabled ? "text-tx-dim" : "text-foreground"
                        }`}
                      >
                        {m.name}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Rendered before a package is picked too, with an empty cart: a
                buyer holding a code should not have to guess whether this
                checkout takes one. The field says what it is waiting for. */}
            <PromoField
              locale={locale}
              items={orderItem ? [orderItem] : []}
              currency="UZS"
              isLoggedIn={isSignedIn}
              onChange={(next) => {
                setPromo(next);
                setPromoDropped(false);
              }}
            />

            <button
              type="button"
              disabled={!canPay}
              onClick={() => {
                setConfirmOpen(true);
              }}
              className={buttonStyles({ size: "lg", className: "mt-6 w-full" })}
            >
              {loading ? (
                <Loader2 size={18} className="animate-spin" />
              ) : (
                <>
                  {t("pay")}
                  {/* The discounted total once a code applies — and it is the
                      server's number, not one computed here, so the button
                      cannot promise a price the order will not honour. */}
                  {promo
                    ? ` · ${formatUzs(locale, Math.round(Number(promo.totalAfter)))}`
                    : selSku &&
                      selectedPriceLabel &&
                      selectedPriceLabel !== "—" &&
                      !priceUnavailable &&
                      ` · ${selectedPriceLabel}`}
                </>
              )}
            </button>

            {promoDropped && (
              <p className="text-danger mt-2.5 text-center text-[12px]">{t("promoDropped")}</p>
            )}

            {!canPay && !loading && !error && payHint && (
              <p className="text-tx-dim mt-2.5 text-center text-[12px]">{payHint}</p>
            )}

            {/* A guest has no account to come back to, and the next screen is
                the acquirer's — say what happens after it, before they leave.
                The one place this was ever written was a post-checkout screen
                that production never reaches (a real acquirer redirects
                immediately). */}
            {/* `canPay` already excludes the loading state. */}
            {canPay && !error && (
              <p className="text-tx-dim mt-2.5 text-center text-[12px] leading-[17px]">
                {t("afterPayNote")}
              </p>
            )}

            {error && (
              <p className="mt-3 text-center text-[13px] text-[#FF6B6B]">
                {/* "напишите в поддержку" was plain text — advice with nothing
                    to act on. Link the word in place when the message contains
                    it; any other error renders unchanged. */}
                {(() => {
                  const word = t("payErrorSupportWord");
                  const [before, after] = error.split(word);
                  if (after === undefined) return error;
                  return (
                    <>
                      {before}
                      <a
                        href="https://t.me/yupay_support"
                        target="_blank"
                        rel="noreferrer noopener"
                        className="underline underline-offset-2"
                      >
                        {word}
                      </a>
                      {after}
                    </>
                  );
                })()}
              </p>
            )}

            {/* Says "данным аккаунта" rather than naming the field. It used
                to claim "по публичному ID" everywhere, which contradicted the
                Steam form asking for a login — and interpolating the label
                instead produced "по Логин Steam", because a Russian
                prepositional phrase needs a case the label doesn't carry. */}
            <div className="border-border/70 text-tx-mute mt-5 flex items-start gap-2.5 border-t pt-5 text-[12px] leading-relaxed">
              {accountRequired ? t("securityNote") : t("securityNoteVoucher")}
            </div>
          </div>
        </aside>

        {/* How-to / about / FAQ — desktop: left column, row 2, so the sticky
            aside scrolls alongside it; mobile: after the order form. */}
        {children && <div className="lg:col-start-1 lg:row-start-2">{children}</div>}
      </div>

      <ConfirmPurchaseModal
        open={confirmOpen}
        title={t("confirmTitle")}
        rows={confirmRows}
        totalLabel={t("confirmTotal")}
        totalValue={selectedPriceLabel}
        warning={accountRequired ? t("confirmWarning") : t("confirmWarningVoucher")}
        // A field-less product (a gift card) has nothing to attest to — the
        // old `!hasVerifiableField` alone was true for it too (`.some()` on
        // an empty array), which blocked checkout on a checkbox that
        // referenced an account field the buyer never saw.
        attestation={accountRequired && !hasVerifiableField ? t("confirmAttest") : undefined}
        confirmLabel={t("confirmCta")}
        cancelLabel={t("confirmCancel")}
        onConfirm={() => {
          setConfirmOpen(false);
          void pay();
        }}
        onClose={() => {
          setConfirmOpen(false);
        }}
      />

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
              {/* When the order can't be paid yet, this line says what is
                  missing instead of a generic caption — the same reason the
                  real button already shows below the form. */}
              <div className="text-tx-mute truncate text-[11px] font-semibold">
                {canPay || !payHint ? t("summaryTitle") : payHint}
              </div>
              <div className="font-display truncate text-lg font-bold leading-tight">
                {priceUnavailable ? "—" : selectedPriceLabel}
              </div>
            </div>
            {/* The bar used to paint a full-lime "Оплатить" whichever state the
                form was in, while the actual pay button below sat dimmed. The
                loudest element on the screen promised payment and then merely
                scrolled — read as a failed charge. It now looks like what it
                does: pays when it can, otherwise takes you to the form. */}
            <button
              type="button"
              onClick={() => {
                if (canPay) setConfirmOpen(true);
                else asideRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
              }}
              className={buttonStyles({
                size: "lg",
                variant: canPay ? "primary" : "ghost",
                className: "shrink-0",
              })}
            >
              {loading ? (
                <Loader2 size={18} className="animate-spin" />
              ) : canPay ? (
                t("pay")
              ) : (
                t("goToPay")
              )}
            </button>
          </div>
        </div>
      )}
    </>
  );
}
