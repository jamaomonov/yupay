/**
 * Renders the form schema defined on a catalog Product (``required_fields``):
 * a list of typed inputs (text/email/number/select) with per-field help.
 *
 * The Telegram Mini App world expects a flat, tap-friendly layout, so each
 * field is its own labelled card with a "Где найти?" sheet when help_text is
 * available.
 */

import { HelpCircle, History, X } from "lucide-react";
import { useId, useState } from "react";

import type { FormField } from "@/lib/catalog";

import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";

const LOCALE = "ru";

function t(map: Record<string, string> | null | undefined, fallback = ""): string {
  if (!map) return fallback;
  return map[LOCALE] ?? Object.values(map)[0] ?? fallback;
}

export interface DynamicFieldsProps {
  fields: FormField[];
  values: Record<string, string>;
  onChange: (key: string, value: string) => void;
  /** Per-field values from the customer's last checkout, offered as a
   *  tap-to-fill suggestion. Never auto-applied — the user decides. */
  suggestions?: Record<string, string>;
}

export function DynamicFields({ fields, values, onChange, suggestions }: DynamicFieldsProps) {
  if (fields.length === 0) return null;
  return (
    <div className="space-y-3">
      {fields.map((field) => (
        <DynamicField
          key={field.key}
          field={field}
          value={values[field.key] ?? ""}
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
  field,
  value,
  onChange,
  suggestion,
}: {
  field: FormField;
  value: string;
  onChange: (v: string) => void;
  suggestion: string | null;
}) {
  const [helpOpen, setHelpOpen] = useState(false);
  // Stable per-instance id so the visible <label> and the underlying control
  // can be tied together for screen readers (WCAG 3.3.2). useId is React 18+
  // safe across SSR — important once we share components with apps/web.
  const fieldId = useId();
  const helpId = `${fieldId}-help`;

  const label = t(field.label, field.key);
  const placeholder = t(field.placeholder ?? null, "");
  const help = t(field.help_text ?? null, "");
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
            onClick={() => {
              setHelpOpen(true);
            }}
            aria-label={`Где найти ${label}`}
            aria-controls={helpId}
            aria-expanded={helpOpen}
            className="flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-semibold transition-opacity active:opacity-70"
            style={{
              background: "hsl(var(--primary) / 0.12)",
              border: "1px solid hsl(var(--primary) / 0.35)",
              color: "hsl(var(--primary))",
            }}
          >
            <HelpCircle size={11} aria-hidden="true" />
            Где найти?
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
          field={field}
          value={value}
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
              Где найти «{label}»
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
  field,
  value,
  onChange,
  placeholder,
  fieldId,
  required,
  suggestion,
}: {
  field: FormField;
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
  fieldId: string;
  required: boolean;
  suggestion: string | null;
}) {
  const inputType = field.type === "email" ? "email" : field.type === "number" ? "tel" : "text";
  const inputMode = field.type === "number" ? "numeric" : field.type === "email" ? "email" : "text";
  const filled = value.trim().length > 0;
  // Offer the last-used value only while the field is still empty — once the
  // customer starts typing we get out of the way.
  const showSuggestion = suggestion !== null && suggestion.length > 0 && !filled;

  const handleChange = (v: string) => {
    if (field.type === "number") {
      onChange(v.replace(/[^\d]/g, ""));
    } else {
      onChange(v);
    }
  };

  return (
    <div>
      <div className="relative">
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
            className="absolute right-3.5 top-1/2 flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded-full bg-white/10"
            aria-label="Очистить"
          >
            <X size={12} className="text-white/60" />
          </button>
        )}
      </div>
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
            Прошлый раз
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
  const options = field.options ?? [];
  const filled = value.length > 0;
  return (
    <div
      id={fieldId}
      className="grid grid-cols-2 gap-2"
      role="radiogroup"
      aria-required={required}
      aria-label={t(field.label, field.key)}
    >
      {options.length === 0 ? (
        <div className="col-span-2 rounded-2xl border border-dashed border-white/15 p-3 text-center text-sm text-white/40">
          {placeholder || "Опций пока нет"}
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
              {t(opt.label, opt.value)}
            </button>
          );
        })
      )}
      {!filled && options.length > 0 && (
        <div className="col-span-2 px-1 text-[11px] text-white/40">Выберите вариант</div>
      )}
    </div>
  );
}
