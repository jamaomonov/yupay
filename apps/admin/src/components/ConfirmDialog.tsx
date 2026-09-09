/**
 * Reusable confirmation dialog for actions that can't be undone.
 *
 * Replaces `window.confirm` for anything consequential: it can show the actual
 * numbers being committed (an amount, a recipient, a direction) rather than a
 * yes/no sentence, it is styled like the rest of the admin, and it inherits
 * `useDialog`'s focus trap / Esc handling / focus restoration.
 *
 * Modelled on the dispatch confirmation in `BroadcastComposerPage`, which was
 * the only screen doing this properly.
 */

import { Button } from "@yupay/ui";
import { useId, useRef } from "react";

import { useDialog } from "@/lib/useDialog";

interface Props {
  title: string;
  /** Body — pass JSX to show the concrete values being committed. */
  children?: React.ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  /** `danger` for irreversible / money-moving actions. */
  tone?: "default" | "danger";
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({
  title,
  children,
  confirmLabel,
  cancelLabel = "Отмена",
  tone = "default",
  busy = false,
  onConfirm,
  onCancel,
}: Props) {
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const confirmRef = useRef<HTMLButtonElement | null>(null);
  const titleId = useId();

  // While the action is in flight, **every** way out is closed, not just the
  // Cancel button. Esc and a backdrop click used to call `onCancel`
  // unconditionally, which on a money dialog is a real hole rather than a
  // cosmetic one: `lib/api.ts` sets no client timeout, so a wifi blip leaves
  // the request hanging, the operator presses Esc, the request later rejects,
  // and the next attempt mints a **new** idempotency key. If the first one had
  // landed and not yet committed, both pre-reads see nothing returned and the
  // deposit is credited twice. Found in M3c fix round 1 on the settle card,
  // and fixed here because `MerchantDetail`'s credit form has the same door.
  const dismiss = () => {
    if (busy) return;
    onCancel();
  };

  useDialog({
    open: true,
    onClose: dismiss,
    containerRef: dialogRef,
    // Focus the confirm button, not the backdrop: the operator arrived here
    // deliberately, and Esc/Tab still get them out.
    initialFocus: () => confirmRef.current?.focus(),
  });

  return (
    <div
      ref={dialogRef}
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 px-4 pt-[12vh] backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      onClick={(e) => {
        // Backdrop click cancels — safe here because a confirm dialog holds no
        // typed input worth losing. Not while `busy`: see `dismiss`.
        if (e.target === e.currentTarget) dismiss();
      }}
    >
      <div className="w-full max-w-md rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] p-4 text-[var(--text-primary)] shadow-[var(--shadow-md)]">
        <h2 id={titleId} className="mb-3 text-sm font-semibold">
          {title}
        </h2>
        {children ? <div className="text-sm text-[var(--text-secondary)]">{children}</div> : null}
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" onClick={dismiss} disabled={busy}>
            {cancelLabel}
          </Button>
          <Button
            ref={confirmRef}
            variant={tone === "danger" ? "danger" : "primary"}
            onClick={onConfirm}
            disabled={busy}
          >
            {busy ? "Выполняем…" : confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}
