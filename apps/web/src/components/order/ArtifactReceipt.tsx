"use client";

import { Check, CheckCircle2, Copy } from "lucide-react";
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
      className="border-border bg-bg hover:border-tx-dim group flex w-full items-center gap-3 rounded-lg border px-3 py-2.5 text-left transition"
    >
      <code className="text-foreground min-w-0 flex-1 truncate font-mono text-sm font-semibold">
        {value}
      </code>
      <span
        className={`inline-flex shrink-0 items-center gap-1.5 text-xs font-semibold ${
          copied ? "text-emerald-400" : "text-tx-dim group-hover:text-tx-mute"
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
  if (keys.length === 0) return null;
  // Dead today (no whitelisted key name matches this pattern), kept only so
  // a future supplier adding a wallet-credit artifact key doesn't also need
  // to touch this banner.
  const walletCredited = keys.some((k) => /wallet|balance|credit/i.test(k));

  return (
    <div className="border-border bg-muted/40 mt-4 rounded-xl border p-4">
      {walletCredited && (
        <p className="mb-3 flex items-center gap-2 text-sm font-semibold text-emerald-400">
          <CheckCircle2 size={16} />
          {t("walletCredited")}
        </p>
      )}
      <dl className="flex flex-col gap-3">
        {keys.map((key) => (
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
