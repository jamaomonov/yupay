"use client";

import { Check, Copy, Gift } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { toast } from "@/store/useToast";

/**
 * Top-level artifact keys the API's customer-facing whitelist ever emits
 * (mirrors `BUYER_SAFE_ARTIFACT_KEYS` in `fulfillment/service.py`). This is
 * the security ceiling: we only ever render a strict subset of these, never a
 * raw `Object.entries(artifact)` dump — even if the server-side whitelist
 * regressed, this component still could not surface an internal field
 * (`source`, `sku_id`, `external_order_id`, …).
 */
const ARTIFACT_KEYS = [
  "code",
  "codes",
  "key",
  "pin",
  "serial",
  "steam_login",
  "login",
  "message",
  "note",
  "fulfillment_data",
] as const;
type ArtifactKey = (typeof ARTIFACT_KEYS)[number];

/**
 * The ONLY keys that represent a real deliverable the customer redeems — a
 * voucher code or a license key. `steam_login`/`login` are the TARGET account
 * the buyer typed at checkout (not something we deliver) and now render in the
 * order composition instead; `fulfillment_data` likewise. This block never
 * surfaces them, so a top-up's login is never dressed up as "Ваша выдача".
 */
const DELIVERABLE_NAMES = new Set<string>(["code", "codes", "key", "pin", "serial"]);
// Derived by filtering the whitelist so the render set is provably a subset of
// ARTIFACT_KEYS at runtime, not just at compile time.
const DELIVERABLE_KEYS: readonly ArtifactKey[] = ARTIFACT_KEYS.filter((k) =>
  DELIVERABLE_NAMES.has(k),
);

/** Free-text delivery notes shown (non-copyable) alongside a real deliverable —
 *  e.g. redemption instructions attached to a key. Never shown on their own. */
const NOTE_NAMES = new Set<string>(["message", "note"]);
const NOTE_KEYS: readonly ArtifactKey[] = ARTIFACT_KEYS.filter((k) => NOTE_NAMES.has(k));

function isScalar(v: unknown): v is string | number {
  return typeof v === "string" || typeof v === "number";
}

/** One copyable deliverable rendered as a monospace chip with a copy button. */
function CopyChip({ value }: { value: string }) {
  const t = useTranslations("web.orders");
  const [copied, setCopied] = useState(false);
  const onCopy = () => {
    void navigator.clipboard
      .writeText(value)
      .then(() => {
        setCopied(true);
        setTimeout(() => {
          setCopied(false);
        }, 1500);
      })
      .catch(() => {
        // Clipboard writes reject on an insecure origin, when permission is
        // denied, or on some in-app browsers. Without this the tap looked like
        // it did nothing at all — surface it and tell the user to copy by hand.
        toast.error(t("copyFailed"));
      });
  };
  return (
    <button
      type="button"
      onClick={onCopy}
      aria-label={copied ? t("copied") : `${t("copy")}: ${value}`}
      className="border-border-2 bg-bg hover:border-primary/50 focus-visible:ring-primary/60 rounded-btn group flex w-full items-center gap-3 border px-3.5 py-3 text-left transition focus-visible:outline-none focus-visible:ring-2 active:scale-[0.99]"
    >
      <code className="text-foreground min-w-0 flex-1 truncate font-mono text-sm font-semibold">
        {value}
      </code>
      <span
        className={`inline-flex shrink-0 items-center gap-1.5 text-xs font-semibold transition-colors ${
          copied ? "text-primary" : "text-tx-dim group-hover:text-tx-mute"
        }`}
      >
        {copied ? <Check size={14} /> : <Copy size={14} />}
        {copied ? t("copied") : t("copy")}
      </span>
    </button>
  );
}

/** Label for a whitelisted artifact key, translated via `web.orders.receipt.*`;
 *  falls back to the raw key only if a key here is ever missing its i18n entry. */
function receiptLabel(t: ReturnType<typeof useTranslations>, key: ArtifactKey): string {
  return t.has(`receipt.${key}`) ? t(`receipt.${key}`) : key;
}

/** Does a deliverable key carry something renderable? `codes` needs a scalar in
 *  its array; the rest need a scalar value. */
function hasDeliverable(key: ArtifactKey, value: unknown): boolean {
  return key === "codes" ? Array.isArray(value) && value.some(isScalar) : isScalar(value);
}

/**
 * The "Ваша выдача" reveal — rendered ONLY when the delivered artifact carries
 * a real deliverable (`code`/`codes`/`key`/`pin`/`serial`). A top-up receipt
 * (only `steam_login`/`fulfillment_data`/`message`) has nothing to hand over,
 * so this returns `null` and the block is absent — the target account and
 * credited amount live in the order composition instead.
 *
 * `code` is skipped whenever `codes` carries more than one value (they overlap —
 * `code` is just `codes[0]`) so a multi-code purchase never shows the first
 * code twice.
 */
export function ArtifactReceipt({ artifact }: { artifact: Record<string, unknown> }) {
  const t = useTranslations("web.orders");
  const codesValue = artifact.codes;
  const multiCode = Array.isArray(codesValue) && codesValue.length > 1;
  const deliverable = DELIVERABLE_KEYS.filter((key) => {
    if (!(key in artifact)) return false;
    if (key === "code" && multiCode) return false;
    if (key === "codes" && !multiCode) return false;
    return hasDeliverable(key, artifact[key]);
  });

  // No real code/key to reveal → no prize block at all (top-up receipts, or an
  // artifact whose only surviving whitelisted keys are the target account /
  // free-text note).
  if (deliverable.length === 0) return null;

  const notes = NOTE_KEYS.filter(
    (key) => isScalar(artifact[key]) && String(artifact[key]).trim() !== "",
  );

  return (
    <div className="border-primary/25 bg-primary/[0.05] rounded-xl border p-4">
      <h3 className="text-primary mb-3 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.08em]">
        <Gift size={13} aria-hidden="true" />
        {t("receiptTitle")}
      </h3>
      <dl className="flex flex-col gap-3">
        {deliverable.map((key) => (
          <DeliverableRow key={key} artifactKey={key} value={artifact[key]} t={t} />
        ))}
        {notes.map((key) => (
          <div key={key} className="flex flex-col gap-1.5">
            <dt className="text-tx-dim text-[11px] font-semibold uppercase tracking-[0.08em]">
              {receiptLabel(t, key)}
            </dt>
            <dd className="text-foreground text-sm leading-snug">{String(artifact[key])}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

/** One deliverable row: `codes` is a list of copyable chips, everything else a
 *  single copyable chip. */
function DeliverableRow({
  artifactKey,
  value,
  t,
}: {
  artifactKey: ArtifactKey;
  value: unknown;
  t: ReturnType<typeof useTranslations>;
}) {
  const dt = (
    <dt className="text-tx-dim text-[11px] font-semibold uppercase tracking-[0.08em]">
      {receiptLabel(t, artifactKey)}
    </dt>
  );

  if (artifactKey === "codes" && Array.isArray(value)) {
    const codes = value.filter(isScalar);
    if (codes.length === 0) return null;
    return (
      <div className="flex flex-col gap-1.5">
        {dt}
        <dd className="flex flex-col gap-1.5">
          {codes.map((code, i) => (
            <CopyChip key={i} value={String(code)} />
          ))}
        </dd>
      </div>
    );
  }

  if (!isScalar(value)) return null;
  return (
    <div className="flex flex-col gap-1.5">
      {dt}
      <dd>
        <CopyChip value={String(value)} />
      </dd>
    </div>
  );
}
