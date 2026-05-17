/**
 * Renders the form schema defined on a catalog Product (``required_fields``):
 * a list of typed inputs (text/email/number/select) with per-field help.
 *
 * The Telegram Mini App world expects a flat, tap-friendly layout, so each
 * field is its own labelled card with a "Где найти?" sheet when help_text is
 * available.
 */

import { useState } from "react";
import { HelpCircle, X } from "lucide-react";

import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import type { FormField } from "@/lib/catalog";

const LOCALE = "ru";

function t(map: Record<string, string> | null | undefined, fallback = ""): string {
  if (!map) return fallback;
  return map[LOCALE] ?? Object.values(map)[0] ?? fallback;
}

export interface DynamicFieldsProps {
  fields: FormField[];
  values: Record<string, string>;
  onChange: (key: string, value: string) => void;
}

export function DynamicFields({ fields, values, onChange }: DynamicFieldsProps) {
  if (fields.length === 0) return null;
  return (
    <div className="space-y-3">
      {fields.map((field) => (
        <DynamicField
          key={field.key}
          field={field}
          value={values[field.key] ?? ""}
          onChange={(v) => onChange(field.key, v)}
        />
      ))}
    </div>
  );
}

function DynamicField({
  field,
  value,
  onChange,
}: {
  field: FormField;
  value: string;
  onChange: (v: string) => void;
}) {
  const [helpOpen, setHelpOpen] = useState(false);

  const label = t(field.label, field.key);
  const placeholder = t(field.placeholder ?? null, "");
  const help = t(field.help_text ?? null, "");
  const hasHelp = help.length > 0;
  const required = field.required;

  return (
    <div>
      <div className="flex items-center justify-between mb-1.5 px-1 gap-2">
        <label className="text-xs font-semibold text-white/75 uppercase tracking-wide">
          {label}
          {required && <span className="text-primary ml-1">*</span>}
        </label>
        {hasHelp && (
          <button
            type="button"
            onClick={() => setHelpOpen(true)}
            aria-label={`Где найти ${label}`}
            className="flex items-center gap-1 text-[11px] font-semibold rounded-full px-2.5 py-1 transition-opacity active:opacity-70"
            style={{
              background: "hsl(var(--primary) / 0.12)",
              border: "1px solid hsl(var(--primary) / 0.35)",
              color: "hsl(var(--primary))",
            }}
          >
            <HelpCircle size={11} />
            Где найти?
          </button>
        )}
      </div>

      {field.type === "select" ? (
        <SelectField field={field} value={value} onChange={onChange} placeholder={placeholder} />
      ) : (
        <TextLikeField field={field} value={value} onChange={onChange} placeholder={placeholder} />
      )}

      <Sheet open={helpOpen} onOpenChange={setHelpOpen}>
        <SheetContent side="bottom" className="rounded-t-3xl">
          <SheetHeader>
            <SheetTitle className="flex items-center gap-2">
              <HelpCircle size={16} className="text-primary" />
              Где найти «{label}»
            </SheetTitle>
            <SheetDescription className="whitespace-pre-wrap text-left text-white/70 leading-relaxed">
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
}: {
  field: FormField;
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
}) {
  const inputType =
    field.type === "email" ? "email" : field.type === "number" ? "tel" : "text";
  const inputMode =
    field.type === "number" ? "numeric" : field.type === "email" ? "email" : "text";
  const filled = value.trim().length > 0;

  const handleChange = (v: string) => {
    if (field.type === "number") {
      onChange(v.replace(/[^\d]/g, ""));
    } else {
      onChange(v);
    }
  };

  return (
    <div className="relative">
      <input
        type={inputType}
        inputMode={inputMode as "text" | "email" | "numeric"}
        value={value}
        onChange={(e) => handleChange(e.target.value)}
        placeholder={placeholder || field.key}
        className="w-full rounded-2xl px-4 py-3.5 text-base text-white placeholder:text-white/25 outline-none transition-all"
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
          onClick={() => onChange("")}
          className="absolute right-3.5 top-1/2 -translate-y-1/2 w-6 h-6 rounded-full bg-white/10 flex items-center justify-center"
          aria-label="Очистить"
        >
          <X size={12} className="text-white/60" />
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
}: {
  field: FormField;
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
}) {
  const options = field.options ?? [];
  const filled = value.length > 0;
  return (
    <div className="grid grid-cols-2 gap-2">
      {options.length === 0 ? (
        <div className="col-span-2 rounded-2xl p-3 text-center text-sm text-white/40 border border-dashed border-white/15">
          {placeholder || "Опций пока нет"}
        </div>
      ) : (
        options.map((opt) => {
          const active = opt.value === value;
          return (
            <button
              key={opt.value}
              type="button"
              onClick={() => onChange(opt.value)}
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
        <div className="col-span-2 text-[11px] text-white/40 px-1">
          Выберите вариант
        </div>
      )}
    </div>
  );
}
