"use client";

import { Check, CheckCircle2, Copy, Gift } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

/**
 * Top-level artifact keys the API's customer-facing whitelist ever emits
 * (mirrors `_CUSTOMER_SAFE_ARTIFACT_KEYS` in `fulfillment/routes.py`).
 * Rendering only these — never a raw `Object.entries(artifact)` dump — is
 * defense-in-depth: even if the server-side whitelist ever regressed, this
 * component still could not surface an internal field (`source`, `sku_id`,
 * `external_order_id`, …).
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

/** Keys whose scalar value is a copyable deliverable — rendered as a
 *  monospace chip with a copy button instead of plain text. */
const COPYABLE_KEYS = new Set<ArtifactKey>([
  "code",
  "codes",
  "key",
  "pin",
  "serial",
  "login",
  "steam_login",
]);

function isScalar(v: unknown): v is string | number {
  return typeof v === "string" || typeof v === "number";
}

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

/** Turn a `fulfillment_data` field name (`player_id`, `steam-login`, an
 *  admin-defined per-product checkout field with no fixed i18n entry) into a
 *  readable "Player Id" label. */
function humanizeFieldName(key: string): string {
  return key
    .replace(/[_-]+/g, " ")
    .trim()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/** One copyable deliverable rendered as a monospace chip with a copy button. */
function CopyChip({ value }: { value: string }) {
  const t = useTranslations("web.orders");
  const [copied, setCopied] = useState(false);
  const onCopy = () => {
    void navigator.clipboard.writeText(value).then(() => {
      setCopied(true);
      setTimeout(() => {
        setCopied(false);
      }, 1500);
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

/** Whether a whitelisted key's value actually produces visible content in
 *  `ArtifactRow` — a key can be *present* (`key in artifact`) while its
 *  value renders nothing, e.g. a `message: null` game top-up receipt or an
 *  empty `fulfillment_data: {}`. Presence alone must never be mistaken for
 *  something to show. */
function isRenderableValue(key: ArtifactKey, value: unknown): boolean {
  if (key === "codes") {
    return Array.isArray(value) && value.some(isScalar);
  }
  if (key === "fulfillment_data") {
    return isPlainObject(value) && Object.values(value).some(isScalar);
  }
  return isScalar(value);
}

/**
 * Clean, translated reveal of a delivered order's artifact — every key here
 * comes from the customer-facing whitelist, so all of it is safe to show (no
 * raw JSON dump, no internal fields). `code` is skipped whenever `codes`
 * carries more than one value (the two overlap — `code` is just
 * `codes[0]`) so a multi-item voucher purchase doesn't show the first code
 * twice.
 */
export function ArtifactReceipt({ artifact }: { artifact: Record<string, unknown> }) {
  const t = useTranslations("web.orders");
  const codesValue = artifact.codes;
  const multiCode = Array.isArray(codesValue) && codesValue.length > 1;
  const keys = ARTIFACT_KEYS.filter((key) => {
    if (!(key in artifact)) return false;
    if (key === "code" && multiCode) return false;
    if (key === "codes" && !multiCode) return false;
    return true;
  });
  const renderableKeys = keys.filter((key) => isRenderableValue(key, artifact[key]));
  // A key can survive the whitelist and still have nothing to show (`message:
  // null`, `fulfillment_data: {}`, an empty `codes`) — an empty bordered card
  // under "Доставлено" reads as broken, so fall back to a plain confirmation
  // line instead of rendering a shell with no content.
  if (renderableKeys.length === 0) {
    return (
      <div className="border-border bg-card-2/60 flex items-center gap-2.5 rounded-xl border p-4">
        <CheckCircle2 className="text-primary shrink-0" size={16} />
        <p className="text-foreground text-sm">{t("receipt.deliveredNote")}</p>
      </div>
    );
  }
  // Dead today (no whitelisted key name matches this pattern), kept only so
  // a future supplier adding a wallet-credit artifact key doesn't also need
  // to touch this banner.
  const walletCredited = renderableKeys.some((k) => /wallet|balance|credit/i.test(k));

  return (
    <div className="border-primary/25 bg-primary/[0.05] rounded-xl border p-4">
      <h3 className="text-primary mb-3 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.08em]">
        <Gift size={13} aria-hidden="true" />
        {t("receiptTitle")}
      </h3>
      {walletCredited && (
        <p className="text-primary mb-3 flex items-center gap-2 text-sm font-semibold">
          <CheckCircle2 size={16} />
          {t("walletCredited")}
        </p>
      )}
      <dl className="flex flex-col gap-3">
        {renderableKeys.map((key) => (
          <ArtifactRow key={key} artifactKey={key} value={artifact[key]} t={t} />
        ))}
      </dl>
    </div>
  );
}

/** One labeled row inside `ArtifactReceipt` — shape depends on the key:
 *  `codes` is a list of copyable chips, `fulfillment_data` is the customer's
 *  own checkout answers as labeled rows, everything else is a single
 *  scalar (copyable chip or plain text). */
function ArtifactRow({
  artifactKey,
  value,
  t,
}: {
  artifactKey: ArtifactKey;
  value: unknown;
  t: ReturnType<typeof useTranslations>;
}) {
  const label = receiptLabel(t, artifactKey);
  const dt = (
    <dt className="text-tx-dim text-[11px] font-semibold uppercase tracking-[0.08em]">{label}</dt>
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

  if (artifactKey === "fulfillment_data" && isPlainObject(value)) {
    const rows = Object.entries(value).filter((entry): entry is [string, string | number] =>
      isScalar(entry[1]),
    );
    if (rows.length === 0) return null;
    return (
      <div className="flex flex-col gap-1.5">
        {dt}
        <dd className="flex flex-col gap-1.5">
          {rows.map(([field, fieldValue]) => (
            <div key={field} className="flex items-center justify-between gap-3 text-sm">
              <span className="text-tx-mute">{humanizeFieldName(field)}</span>
              <span className="text-foreground font-mono">{String(fieldValue)}</span>
            </div>
          ))}
        </dd>
      </div>
    );
  }

  if (!isScalar(value)) return null;
  const str = String(value);

  return (
    <div className="flex flex-col gap-1.5">
      {dt}
      <dd>
        {COPYABLE_KEYS.has(artifactKey) ? (
          <CopyChip value={str} />
        ) : (
          <span className="text-foreground font-mono text-sm">{str}</span>
        )}
      </dd>
    </div>
  );
}
