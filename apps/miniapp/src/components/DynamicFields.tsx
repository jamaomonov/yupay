/**
 * Renders the form schema defined on a catalog Product (``required_fields``):
 * a list of typed inputs (text/email/number/select) with per-field help.
 *
 * The Telegram Mini App world expects a flat, tap-friendly layout, so each
 * field is its own labelled card with a "Где найти?" sheet when help_text is
 * available.
 */

import { Check, HelpCircle, History, Loader2, X } from "lucide-react";
import { useId, useRef, useState } from "react";

import type { FormField } from "@/lib/catalog";
import type { PlayerCheckResult } from "@/lib/player-check";
import type { Locale } from "@yupay/i18n";

import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { useT } from "@/lib/i18n";
import {
  canCheck,
  checkUnavailable,
  currentFieldCheck,
  runPlayerCheck,
  serverIdFor,
  type PlayerCheckVerdict,
} from "@/lib/player-check-state";
import { haptic } from "@/lib/telegram";

/** Picks the active-locale value out of a server-provided multilingual map,
 *  falling back to the first available translation, then to ``fallback``. */
export function pickLocalized(
  map: Record<string, string> | null | undefined,
  locale: Locale,
  fallback = "",
): string {
  if (!map) return fallback;
  return map[locale] ?? Object.values(map)[0] ?? fallback;
}

export interface DynamicFieldsProps {
  /** Product these fields belong to — required for the player-check button,
   *  which looks up the nickname against this specific product's provider. */
  productId: string;
  fields: FormField[];
  values: Record<string, string>;
  onChange: (key: string, value: string) => void;
  /** Per-field values from the customer's last checkout, offered as a
   *  tap-to-fill suggestion. Never auto-applied — the user decides. */
  suggestions?: Record<string, string>;
  /** Reports a checkable field's fresh verdict, filed under the question it
   *  was asked (product + id + server), or `null` when «Изменить» drops it.
   *  Only fired for fields that carry a `check` config; lets the parent gate
   *  checkout on "verified", not just "typed something", and show the
   *  resolved nickname elsewhere (order summary).
   *
   *  Reported straight from the check handler rather than mirrored up from an
   *  effect: an effect lands a commit later, and this verdict gates the CTA
   *  (see `currentCheck`). */
  onCheckResult: (key: string, verdict: PlayerCheckVerdict | null) => void;
  /** The parent's verdict store, read back through `currentFieldCheck` — the
   *  same function the CTA gate and the review screen's nickname use, so no
   *  reader can disagree with another about whose account this is.
   *
   *  Owning it in the parent also fixes what a `knownResults` seed used to
   *  paper over: `TopUp`'s review stage unmounts this whole form (it lives
   *  behind `stage === "select"`), and state kept in the field would forget a
   *  verified pill the moment the buyer taps back. */
  checkResults: Record<string, PlayerCheckVerdict | null>;
}

export function DynamicFields({
  productId,
  fields,
  values,
  onChange,
  suggestions,
  onCheckResult,
  checkResults,
}: DynamicFieldsProps) {
  const { locale } = useT();
  if (fields.length === 0) return null;
  return (
    <div className="space-y-3">
      {fields.map((field) => {
        // Present only when `check.server_field` names a sibling — doubles
        // as "server is required for this check" and as the hint text.
        const serverLabel = field.check?.server_field
          ? pickLocalized(
              fields.find((f) => f.key === field.check?.server_field)?.label,
              locale,
              field.check.server_field,
            )
          : null;
        return (
          <DynamicField
            key={field.key}
            productId={productId}
            field={field}
            value={values[field.key] ?? ""}
            allValues={values}
            serverLabel={serverLabel}
            suggestion={suggestions?.[field.key] ?? null}
            onChange={(v) => {
              onChange(field.key, v);
            }}
            onCheckResult={onCheckResult}
            check={currentFieldCheck(checkResults, productId, values, field)}
          />
        );
      })}
    </div>
  );
}

function DynamicField({
  productId,
  field,
  value,
  allValues,
  serverLabel,
  onChange,
  suggestion,
  onCheckResult,
  check,
}: {
  productId: string;
  field: FormField;
  value: string;
  allValues: Record<string, string>;
  serverLabel: string | null;
  onChange: (v: string) => void;
  suggestion: string | null;
  onCheckResult: (key: string, verdict: PlayerCheckVerdict | null) => void;
  check: PlayerCheckResult | null;
}) {
  const { t, locale } = useT();
  const [helpOpen, setHelpOpen] = useState(false);
  // Stable per-instance id so the visible <label> and the underlying control
  // can be tied together for screen readers (WCAG 3.3.2). useId is React 18+
  // safe across SSR — important once we share components with apps/web.
  const fieldId = useId();
  const helpId = `${fieldId}-help`;

  const label = pickLocalized(field.label, locale, field.key);
  const placeholder = pickLocalized(field.placeholder ?? null, locale, "");
  const help = pickLocalized(field.help_text ?? null, locale, "");
  const hasHelp = help.length > 0;
  const required = field.required;

  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between gap-2 px-1">
        <label
          htmlFor={fieldId}
          className="text-xs font-semibold uppercase tracking-wide text-white/75"
        >
          {label}
          {required && (
            <span className="text-primary ml-1" aria-hidden="true">
              *
            </span>
          )}
        </label>
        {hasHelp && (
          <button
            type="button"
            // Invisible padding rather than a bigger chip: this is the only
            // hint telling a newcomer where to find their game id, and at
            // ~24px it was under any reasonable thumb target.
            onClick={() => {
              setHelpOpen(true);
            }}
            aria-label={t("field.whereToFindLabel", { label })}
            aria-controls={helpId}
            aria-expanded={helpOpen}
            className="relative flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-semibold transition-opacity after:absolute after:-inset-2.5 after:content-[''] active:opacity-70"
            style={{
              background: "hsl(var(--primary) / 0.12)",
              border: "1px solid hsl(var(--primary) / 0.35)",
              color: "hsl(var(--primary))",
            }}
          >
            <HelpCircle size={11} aria-hidden="true" />
            {t("field.whereToFind")}
          </button>
        )}
      </div>

      {field.type === "select" ? (
        <SelectField
          field={field}
          value={value}
          onChange={onChange}
          placeholder={placeholder}
          fieldId={fieldId}
          required={required}
        />
      ) : (
        <TextLikeField
          productId={productId}
          field={field}
          value={value}
          allValues={allValues}
          serverLabel={serverLabel}
          onChange={onChange}
          placeholder={placeholder}
          fieldId={fieldId}
          required={required}
          suggestion={suggestion}
          onCheckResult={onCheckResult}
          check={check}
        />
      )}

      <Sheet open={helpOpen} onOpenChange={setHelpOpen}>
        <SheetContent side="bottom" className="rounded-t-3xl" id={helpId}>
          <SheetHeader>
            <SheetTitle className="flex items-center gap-2">
              <HelpCircle size={16} className="text-primary" aria-hidden="true" />
              {t("field.whereToFindTitle", { label })}
            </SheetTitle>
            <SheetDescription className="whitespace-pre-wrap text-left leading-relaxed text-white/70">
              {help}
            </SheetDescription>
          </SheetHeader>
        </SheetContent>
      </Sheet>
    </div>
  );
}

/** What one press of «Проверить» asks about: everything G2B is given, and so
 *  everything the answer is about. `PlayerCheckVerdict` is this plus the
 *  answer; the field also holds it for the press currently in flight. */
type PlayerCheckQuestion = Omit<PlayerCheckVerdict, "result">;

function TextLikeField({
  productId,
  field,
  value,
  allValues,
  serverLabel,
  onChange,
  placeholder,
  fieldId,
  required,
  suggestion,
  onCheckResult,
  check,
}: {
  productId: string;
  field: FormField;
  value: string;
  allValues: Record<string, string>;
  /** The sibling server field's own label, present only when `check.server_field`
   *  names one — doubles as "server is required for this check" and as the
   *  text for the "fill it in first" hint below the Проверить button. */
  serverLabel: string | null;
  onChange: (v: string) => void;
  placeholder: string;
  fieldId: string;
  required: boolean;
  suggestion: string | null;
  onCheckResult: (key: string, verdict: PlayerCheckVerdict | null) => void;
  /** The verdict that currently applies to this field's value under this
   *  product and server, or `null` when none does — derived by the parent
   *  through `currentFieldCheck`. See `DynamicFieldsProps.checkResults`. */
  check: PlayerCheckResult | null;
}) {
  const { t } = useT();
  const inputType = field.type === "email" ? "email" : field.type === "number" ? "tel" : "text";
  const inputMode = field.type === "number" ? "numeric" : field.type === "email" ? "email" : "text";
  const filled = value.trim().length > 0;
  // Offer the last-used value only while the field is still empty — once the
  // customer starts typing we get out of the way.
  const showSuggestion = suggestion !== null && suggestion.length > 0 && !filled;

  // Advisory player-id lookup (e.g. Steam/game nickname preview). Only
  // rendered when the catalog schema marks this field as checkable.
  const checkConfig = field.check;
  // The question currently in flight, or `null` when none is. Held as the
  // question rather than as a bare `true` so the spinner goes stale on exactly
  // the terms the verdict does: `checkPlayer` sets no deadline of its own, so
  // switching product mid-check would otherwise leave the button spinning,
  // disabled, on a lookup whose answer is already going to be discarded.
  const [asking, setAsking] = useState<PlayerCheckQuestion | null>(null);
  // The same value, readable from inside an in-flight check — `asking` there
  // is whatever that press captured, so only a ref can say whether a later
  // press has superseded it. Written and cleared in lockstep with the state.
  const latestAsk = useRef<PlayerCheckQuestion | null>(null);
  const serverId = serverIdFor(field, allValues);
  const checking =
    asking !== null &&
    asking.productId === productId &&
    asking.playerId === value &&
    asking.serverId === serverId;
  const idOk = canCheck(value, field.pattern);
  const canRunCheck = canCheck(value, field.pattern, {
    required: serverLabel !== null,
    id: serverId,
  });
  // A valid id sitting next to an empty server field would otherwise just
  // disable the button with no explanation — say what's missing.
  const missingServer = idOk && serverLabel !== null && (serverId ?? "").trim().length === 0;

  const handleCheck = async () => {
    // What the answer will be filed under: the product, the id and the server
    // as they are at the moment of the press, never as they are when it lands.
    const asked: PlayerCheckQuestion = { productId, playerId: value, serverId };
    latestAsk.current = asked;
    setAsking(asked);
    try {
      const result = await runPlayerCheck(productId, { playerId: value, serverId });
      // Only if this press is still the latest. Two checks can be in flight
      // (editing the id re-enables the button), and letting an older one
      // report would file its question over the fresh verdict — the pill would
      // vanish and the CTA re-block with nothing on screen to explain it.
      if (latestAsk.current !== asked) return;
      // A resolved nickname is the strongest "we see your account" signal in
      // the flow; a rejection is the cheapest moment to catch a typo. Both
      // deserve the same tactile confirmation a native app would give.
      haptic(result.status === "valid" ? "ok" : "error");
      // Reported straight from here, not from an effect: this verdict gates
      // the CTA, and an effect lands a commit later.
      onCheckResult(field.key, { ...asked, result });
    } finally {
      if (latestAsk.current === asked) latestAsk.current = null;
      setAsking((current) => (current === asked ? null : current));
    }
  };

  const handleChange = (v: string) => {
    if (field.type === "number") {
      onChange(v.replace(/[^\d]/g, ""));
    } else {
      onChange(v);
    }
  };

  const checkDone = checkConfig ? check : null;
  /** Drops the standing verdict and puts the input back. Explicit, rather
   *  than leaning on the id changing: the buyer is about to retype, and until
   *  they do the question is unchanged, so nothing else would clear it. */
  const editAgain = () => {
    onCheckResult(field.key, null);
  };

  // Resolved id → collapse the input into a confirmation pill (nickname + id).
  if (checkDone?.status === "valid") {
    return (
      <div className="flex items-center gap-2.5 rounded-2xl border border-emerald-500/40 bg-emerald-500/[0.06] py-1.5 pl-1.5 pr-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-400">
          <Check size={17} strokeWidth={3} />
        </span>
        <div className="min-w-0 flex-1 leading-tight">
          <div className="truncate text-[14px] font-bold text-white">{checkDone.name}</div>
          <div className="truncate font-mono text-[12px] text-emerald-400">{value}</div>
        </div>
        <button
          type="button"
          onClick={editAgain}
          className="shrink-0 text-[13px] font-medium text-white/45 active:opacity-70"
        >
          {t("field.checkEdit")}
        </button>
      </div>
    );
  }

  // Wrong id — the customer mistyped it; offer to fix, never block checkout.
  if (checkDone?.status === "invalid") {
    return (
      <div className="flex items-center gap-2.5 rounded-2xl border border-red-500/40 bg-red-500/[0.06] py-1.5 pl-1.5 pr-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-red-500/15 text-red-400">
          <X size={17} strokeWidth={3} />
        </span>
        <div className="min-w-0 flex-1 leading-tight">
          <div className="truncate text-[13.5px] font-semibold text-red-300">
            {t("field.checkNotFound")}
          </div>
          <div className="truncate font-mono text-[12px] text-white/40">{value}</div>
        </div>
        <button
          type="button"
          onClick={editAgain}
          className="shrink-0 text-[13px] font-medium text-white/45 active:opacity-70"
        >
          {t("field.checkEdit")}
        </button>
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-stretch gap-2">
        <div className="relative min-w-0 flex-1">
          <input
            id={fieldId}
            type={inputType}
            inputMode={inputMode}
            value={value}
            onChange={(e) => {
              handleChange(e.target.value);
            }}
            placeholder={placeholder || field.key}
            required={required}
            aria-required={required}
            className="w-full rounded-2xl px-4 py-3.5 text-base text-white outline-none transition-all placeholder:text-white/25"
            style={{
              background: "hsl(var(--surface-2))",
              border: filled
                ? "1.5px solid hsl(var(--primary) / 0.7)"
                : "1px solid hsl(var(--border))",
              color: filled ? "hsl(var(--primary))" : "white",
              letterSpacing: field.type === "number" && filled ? "0.08em" : "normal",
            }}
          />
          {value && (
            <button
              type="button"
              onClick={() => {
                onChange("");
              }}
              className="absolute right-3 top-1/2 flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded-full bg-white/10"
              aria-label={t("field.clear")}
            >
              <X size={12} className="text-white/60" />
            </button>
          )}
        </div>
        {checkConfig && (
          <button
            type="button"
            disabled={!canRunCheck || checking}
            onClick={() => {
              void handleCheck();
            }}
            aria-label={t("field.check")}
            className="inline-flex shrink-0 items-center justify-center gap-2 rounded-2xl px-5 text-[13px] font-semibold transition-opacity active:opacity-70 disabled:opacity-40"
            style={{
              background: "hsl(var(--primary) / 0.12)",
              border: "1px solid hsl(var(--primary) / 0.35)",
              color: "hsl(var(--primary))",
            }}
          >
            {checking && <Loader2 size={15} className="animate-spin" />}
            {checking ? t("field.checking") : t("field.check")}
          </button>
        )}
      </div>
      {checkUnavailable(checkDone) && (
        <p className="mt-1.5 px-1 text-[12px] text-white/40">
          {t("field.checkFailed")} ·{" "}
          <button
            type="button"
            onClick={() => {
              void handleCheck();
            }}
            className="font-medium"
            style={{ color: "hsl(var(--primary) / 1)" }}
          >
            {t("field.checkRetry")}
          </button>
        </p>
      )}
      {missingServer && (
        <p className="mt-1.5 px-1 text-[12px] text-white/40">
          {t("field.checkNeedsServer", { label: serverLabel })}
        </p>
      )}
      {showSuggestion && (
        <button
          type="button"
          onClick={() => {
            onChange(suggestion);
          }}
          className="mt-1.5 flex w-full items-center justify-between gap-2 rounded-xl px-3 py-2 text-left transition-opacity active:opacity-70"
          style={{
            background: "hsl(var(--surface-2))",
            border: "1px dashed hsl(var(--border))",
          }}
        >
          <span className="flex shrink-0 items-center gap-1.5 text-[11px] font-medium text-white/45">
            <History size={11} aria-hidden="true" />
            {t("field.lastTime")}
          </span>
          <span className="truncate text-[13px] font-medium text-white/80">{suggestion}</span>
        </button>
      )}
    </div>
  );
}

function SelectField({
  field,
  value,
  onChange,
  placeholder,
  fieldId,
  required,
}: {
  field: FormField;
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
  fieldId: string;
  required: boolean;
}) {
  const { t, locale } = useT();
  const options = field.options ?? [];
  const filled = value.length > 0;
  return (
    <div
      id={fieldId}
      className="grid grid-cols-2 gap-2"
      role="radiogroup"
      aria-required={required}
      aria-label={pickLocalized(field.label, locale, field.key)}
    >
      {options.length === 0 ? (
        <div className="col-span-2 rounded-2xl border border-dashed border-white/15 p-3 text-center text-sm text-white/40">
          {placeholder || t("field.noOptions")}
        </div>
      ) : (
        options.map((opt) => {
          const active = opt.value === value;
          return (
            <button
              key={opt.value}
              type="button"
              role="radio"
              aria-checked={active}
              onClick={() => {
                onChange(opt.value);
              }}
              className="relative rounded-2xl px-3 py-3 text-sm font-semibold transition-all duration-150"
              style={{
                background: active ? "hsl(var(--surface-3))" : "hsl(var(--surface-2))",
                border: active
                  ? "1.5px solid hsl(var(--primary) / 0.8)"
                  : "1px solid hsl(var(--border))",
                color: active ? "white" : "rgba(255,255,255,0.7)",
              }}
            >
              {pickLocalized(opt.label, locale, opt.value)}
            </button>
          );
        })
      )}
      {!filled && options.length > 0 && (
        <div className="col-span-2 px-1 text-[11px] text-white/40">{t("field.chooseOption")}</div>
      )}
    </div>
  );
}
