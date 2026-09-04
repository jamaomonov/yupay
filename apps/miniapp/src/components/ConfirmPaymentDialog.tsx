import { useEffect, useState } from "react";

import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useT } from "@/lib/i18n";
import { haptic } from "@/lib/telegram";

/**
 * Last look before an irreversible payment.
 *
 * Tapping pay handed the buyer straight to the acquirer. A mistyped game id is
 * the most expensive mistake in this category — the top-up lands on a
 * stranger's account and the refund policy says so — and the web checkout
 * already got this guard, while the Mini App, where most of the volume is, did
 * not.
 *
 * Where the supplier can verify the id it already has (the resolved nickname
 * shows in the field). Where it cannot — Genshin and Honkai Star Rail, which
 * g2b reports as "no validation required" — this dialog is the only place a
 * typo can still be caught, so it asks the buyer to attest and holds the
 * button until they do.
 */
export interface ConfirmRow {
  label: string;
  value: string;
}

export function ConfirmPaymentDialog({
  open,
  rows,
  total,
  warning,
  needsAttestation,
  attestLabel,
  onConfirm,
  onOpenChange,
}: {
  open: boolean;
  rows: ConfirmRow[];
  total: string;
  /** Caller picks the wording — a top-up warns the account can't be changed
   *  after payment, a gift card has no account to get that warning wrong. */
  warning: string;
  needsAttestation: boolean;
  /** What the attestation checkbox actually asks the buyer to re-check —
   *  defaults to `topup.confirmAttest` ("I checked the in-game data is
   *  correct"), which is wrong for a flow with no in-game data at all: a
   *  gift's only re-checkable fact is the recipient's profile link, and a
   *  buyer who ticks a box that doesn't mention it isn't re-checking
   *  anything (2026-09-04 review round 1). `TopUp` never passes this, so
   *  its rendering is byte-identical to before. */
  attestLabel?: string;
  onConfirm: () => void;
  onOpenChange: (next: boolean) => void;
}) {
  const { t } = useT();
  const [attested, setAttested] = useState(false);

  // Each opening starts unticked: the buyer may have gone back to edit the id,
  // and a tick carried over would attest to the old one.
  useEffect(() => {
    if (open) setAttested(false);
  }, [open]);

  const blocked = needsAttestation && !attested;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-[340px] sm:rounded-2xl">
        <DialogHeader>
          <DialogTitle className="text-left">{t("topup.confirmTitle")}</DialogTitle>
        </DialogHeader>

        <dl className="border-border divide-border divide-y border-y">
          {rows.map((row) => (
            <div key={row.label} className="flex items-start justify-between gap-3 py-2">
              <dt className="text-[12px] text-white/50">{row.label}</dt>
              <dd className="min-w-0 break-words text-right text-[13px] font-semibold text-white">
                {row.value}
              </dd>
            </div>
          ))}
          <div className="flex items-baseline justify-between gap-3 py-2.5">
            <dt className="text-[12px] text-white/50">{t("topup.confirmTotal")}</dt>
            <dd className="text-base font-extrabold text-white">{total}</dd>
          </div>
        </dl>

        <p className="text-[12px] leading-snug text-white/55">{warning}</p>

        {needsAttestation && (
          <label className="border-border bg-card flex items-start gap-2.5 rounded-xl border p-3 text-[12px] leading-snug text-white/80">
            <input
              type="checkbox"
              checked={attested}
              onChange={(e) => {
                setAttested(e.target.checked);
              }}
              className="accent-primary mt-0.5 h-4 w-4 shrink-0"
            />
            <span>{attestLabel ?? t("topup.confirmAttest")}</span>
          </label>
        )}

        <div className="flex gap-2.5">
          <button
            type="button"
            onClick={() => {
              onOpenChange(false);
            }}
            className="border-border flex-1 rounded-xl border py-3 text-sm font-semibold text-white/75"
          >
            {t("topup.confirmCancel")}
          </button>
          <button
            type="button"
            disabled={blocked}
            onClick={() => {
              haptic("press");
              onConfirm();
            }}
            className="bg-primary text-primary-foreground flex-1 rounded-xl py-3 text-sm font-bold disabled:opacity-45"
          >
            {t("topup.confirmCta")}
          </button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
