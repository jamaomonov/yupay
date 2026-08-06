/**
 * Renders the form schema defined on a catalog Product (``required_fields``):
 * a list of typed inputs (text/email/number/select) with per-field help.
 *
 * The Telegram Mini App world expects a flat, tap-friendly layout, so each
 * field is its own labelled card with a "Где найти?" sheet when help_text is
 * available.
 */

import { Check, HelpCircle, History, Loader2, X } from "lucide-react";
import { useEffect, useId, useState } from "react";

import type { FormField } from "@/lib/catalog";
import type { Locale } from "@yupay/i18n";

import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { useT } from "@/lib/i18n";
import { canCheck, IDLE, runPlayerCheck, type CheckState } from "@/lib/player-check-state";
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
}

export function DynamicFields({
  productId,
  fields,
  values,
  onChange,
  suggestions,
}: DynamicFieldsProps) {
  if (fields.length === 0) return null;
  return (
    <div className="space-y-3">
      {fields.map((field) => (
        <DynamicField
          key={field.key}
          productId={productId}
          field={field}
          value={values[field.key] ?? ""}
          allValues={values}
          suggestion={suggestions?.[field.key] ?? null}
          onChange={(v) => {
            onChange(field.key, v);
          }}
        />
      ))}
    </div>
  );
}

function DynamicField({
  productId,
  field,
  value,
  allValues,
  onChange,
  suggestion,
}: {
  productId: string;
  field: FormField;
  value: string;
  allValues: Record<string, string>;
  onChange: (v: string) => void;
  suggestion: string | null;
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
          onChange={onChange}
          placeholder={placeholder}
          fieldId={fieldId}
          required={required}
          suggestion={suggestion}
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

function TextLikeField({
  productId,
  field,
  value,
  allValues,
  onChange,
  placeholder,
  fieldId,
  required,
  suggestion,
}: {
  productId: string;
  field: FormField;
  value: string;
  allValues: Record<string, string>;
  onChange: (v: string) => void;
  placeholder: string;
  fieldId: string;
  required: boolean;
  suggestion: string | null;
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
  const [check, setCheck] = useState<CheckState>(IDLE);
  useEffect(() => {
    setCheck(IDLE);
  }, [value]);
  const canRunCheck = canCheck(value, field.pattern);

  const handleCheck = async () => {
    setCheck({ phase: "loading" });
    const serverId = checkConfig?.server_field
      ? (allValues[checkConfig.server_field] ?? null)
      : null;
    const result = await runPlayerCheck(productId, { playerId: value, serverId });
    // A resolved nickname is the strongest "we see your account" signal in the
    // flow; a rejection is the cheapest moment to catch a typo. Both deserve
    // the same tactile confirmation a native app would give.
    if (result.phase === "done") haptic(result.result.status === "valid" ? "ok" : "error");
    setCheck(result);
  };

  const handleChange = (v: string) => {
    if (field.type === "number") {
      onChange(v.replace(/[^\d]/g, ""));
    } else {
      onChange(v);
    }
  };

  const checkDone = checkConfig && check.phase === "done" ? check.result : null;

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
          onClick={() => {
            setCheck(IDLE);
          }}
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
          onClick={() => {
            setCheck(IDLE);
          }}
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
            disabled={!canRunCheck || check.phase === "loading"}
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
            {check.phase === "loading" && <Loader2 size={15} className="animate-spin" />}
            {check.phase === "loading" ? t("field.checking") : t("field.check")}
          </button>
        )}
      </div>
      {checkConfig && check.phase === "done" && check.result.status === "error" && (
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
