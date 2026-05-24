/**
 * Field — a labelled form-field wrapper that wires up label / hint / error
 * relationships for assistive tech without each form re-inventing them.
 *
 * Render-prop API: the consumer provides the actual `<input>` / `<select>` /
 * `<textarea>` (or a wrapping component like `@yupay/ui`'s `Input`) and
 * receives back the `id`, `aria-describedby`, and `aria-invalid` props it
 * should spread on the control. The wrapper then renders the label, hint,
 * and error in the right places.
 *
 * Usage:
 *
 *     <Field label="Имя сегмента" hint="не длиннее 80 символов" error={localError}>
 *       {({ inputProps }) => (
 *         <Input {...inputProps} value={name} onChange={…} maxLength={80} />
 *       )}
 *     </Field>
 */

import { useId, type ReactNode } from "react";

export interface FieldRenderProps {
  inputProps: {
    id: string;
    "aria-describedby"?: string;
    "aria-invalid"?: true;
    "aria-required"?: true;
  };
}

interface Props {
  label: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  required?: boolean;
  /** Optional className for the outer wrapper. */
  className?: string;
  children: (props: FieldRenderProps) => ReactNode;
}

export function Field({ label, hint, error, required, className, children }: Props) {
  const baseId = useId();
  const inputId = `${baseId}-input`;
  const hintId = hint ? `${baseId}-hint` : undefined;
  const errorId = error ? `${baseId}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined;

  return (
    <div className={["block", className ?? ""].join(" ")}>
      <label
        htmlFor={inputId}
        className="mb-1 block text-xs font-medium uppercase tracking-wide text-[var(--text-secondary)]"
      >
        {label}
        {required && (
          <span className="ml-1 text-[var(--danger)]" aria-hidden>
            *
          </span>
        )}
      </label>
      {children({
        inputProps: {
          id: inputId,
          ...(describedBy ? { "aria-describedby": describedBy } : {}),
          ...(error ? { "aria-invalid": true as const } : {}),
          ...(required ? { "aria-required": true as const } : {}),
        },
      })}
      {hint && !error && (
        <p id={hintId} className="mt-1 text-xs text-[var(--text-secondary)]">
          {hint}
        </p>
      )}
      {error && (
        <p id={errorId} className="mt-1 text-xs text-[var(--danger-fg)]">
          {error}
        </p>
      )}
    </div>
  );
}
