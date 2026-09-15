"use client";

import { useId } from "react";

/**
 * A labelled input.
 *
 * The label is a real `<label>` bound by id rather than a placeholder: a
 * placeholder disappears the moment someone types, which leaves a half-filled
 * form with no way to tell what each box was for.
 */
export function Field({
  label,
  type = "text",
  value,
  onChange,
  hint,
  autoComplete,
  required = true,
  minLength,
}: {
  label: string;
  type?: "text" | "email" | "password";
  value: string;
  onChange: (value: string) => void;
  hint?: string;
  autoComplete?: string;
  required?: boolean;
  minLength?: number;
}) {
  const id = useId();
  const hintId = `${id}-hint`;
  return (
    <div className="mb-4">
      <label htmlFor={id} className="text-tx-mute mb-1.5 block text-sm">
        {label}
      </label>
      <input
        id={id}
        type={type}
        value={value}
        required={required}
        minLength={minLength}
        autoComplete={autoComplete}
        onChange={(event) => {
          onChange(event.target.value);
        }}
        // The hint was a loose paragraph beside the field: "не короче 10
        // символов" is a *requirement*, and a screen reader never heard it
        // before the user submitted and failed.
        aria-describedby={hint ? hintId : undefined}
        className="border-border bg-card rounded-btn w-full border px-3.5 py-2.5 text-sm"
      />
      {hint ? (
        <p id={hintId} className="text-tx-dim mt-1.5 text-xs">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

export function SubmitButton({ label, busy }: { label: string; busy: boolean }) {
  return (
    <button
      type="submit"
      disabled={busy}
      className="bg-primary text-primary-foreground rounded-btn w-full py-2.5 text-sm font-semibold disabled:opacity-60"
    >
      {label}
    </button>
  );
}

export function FormError({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p role="alert" className="text-danger mb-4 text-sm leading-relaxed">
      {message}
    </p>
  );
}
