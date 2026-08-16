/**
 * The request context an order was placed from — IP, browser, language, and
 * the passive hints the browser reported (timezone / locale / screen).
 *
 * It exists for one job: answering an acquirer inside the days they allow when
 * a cardholder disputes a payment (ADR-0044). Everything here is personal data
 * we otherwise refuse to keep, so it follows the same rule the delivered-codes
 * card does — nothing is fetched or shown until the operator asks, and the ask
 * itself is written to the order timeline server-side
 * (`admin.evidence_viewed`). That keeps IPs off the screen during a
 * screen-share and makes "who looked up this customer" answerable.
 */

import { Button } from "@yupay/ui";
import { Check, Copy, Eye, Fingerprint } from "lucide-react";
import { useState } from "react";

import type { EvidencePackOut } from "./types";
import type { UseQueryResult } from "@tanstack/react-query";

import { writeToClipboard } from "@/lib/clipboard";

export interface EvidenceCardProps {
  revealed: boolean;
  onReveal: () => void;
  query: UseQueryResult<EvidencePackOut>;
}

export function EvidenceCard({ revealed, onReveal, query }: EvidenceCardProps) {
  const pack = query.data;

  return (
    <div className="rounded-lg border bg-[var(--bg-surface)] shadow-[var(--shadow-sm)]">
      <header className="flex items-center gap-2 border-b px-4 py-3">
        <Fingerprint className="size-4 text-[var(--text-secondary)]" />
        <h2 className="text-sm font-semibold">Контекст покупателя</h2>
      </header>

      <div className="space-y-3 p-3 text-sm">
        {!revealed && (
          <>
            <p className="text-[var(--text-secondary)]">
              Скрыто: это персональные данные. Просмотр записывается в историю заказа.
            </p>
            <Button variant="ghost" className="h-7 px-2 text-xs" onClick={onReveal}>
              <Eye className="size-3.5" />
              Показать контекст
            </Button>
          </>
        )}

        {revealed && query.isLoading && <p className="text-[var(--text-secondary)]">Загружаем…</p>}

        {revealed && query.isError && (
          <div role="alert">
            <p className="text-[var(--danger)]">Не удалось загрузить контекст.</p>
            <button
              type="button"
              onClick={() => void query.refetch()}
              className="mt-1 text-xs text-[var(--text-secondary)] underline-offset-2 hover:text-[var(--text-primary)] hover:underline"
            >
              Повторить
            </button>
          </div>
        )}

        {/* A pack with no capture is expected, not broken: orders placed before
            the capture shipped have none, and the capture is best-effort by
            design — it must never be the reason a sale fails. Saying so beats
            an empty card the operator reads as a bug. */}
        {revealed && pack && !pack.capture && (
          <p className="text-[var(--text-secondary)]">
            Контекст не записан — заказ оформлен до появления этой фичи, либо захват не удался.
          </p>
        )}

        {revealed && pack?.capture && (
          <>
            <dl className="space-y-2">
              <Row label="IP" value={pack.capture.ip} mono />
              <Row label="Язык" value={pack.capture.accept_language} />
              <Row label="Часовой пояс" value={hint(pack.capture.client_hints, "timezone")} />
              <Row label="Локаль" value={hint(pack.capture.client_hints, "locale")} />
              <Row label="Экран" value={hint(pack.capture.client_hints, "screen")} />
              <Row label="Браузер" value={pack.capture.user_agent} mono wrap />
              <Row label="Собрано" value={formatDate(pack.capture.created_at)} />
              <Row label="Удалится" value={formatDate(pack.capture.purge_after)} />
            </dl>
            {/* The whole pack, not just what is on screen: answering an acquirer
                means handing over the capture *and* the timeline together. */}
            <CopyPackButton pack={pack} />
          </>
        )}
      </div>
    </div>
  );
}

/** One `<dt>/<dd>` pair, rendered only when there is something to show — a
 *  field the browser never reported is noise in a dispute pack. */
function Row({
  label,
  value,
  mono = false,
  wrap = false,
}: {
  label: string;
  value: string | null | undefined;
  mono?: boolean;
  wrap?: boolean;
}) {
  if (!value) return null;
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="flex-shrink-0 text-xs uppercase text-[var(--text-secondary)]">{label}</dt>
      <dd
        className={[
          "min-w-0 text-right",
          mono ? "font-mono text-xs" : "text-sm",
          wrap ? "break-all" : "truncate",
        ].join(" ")}
      >
        {value}
      </dd>
    </div>
  );
}

/** Milliseconds the confirmation tick stays up after a copy. */
const FEEDBACK_MS = 1400;

function CopyPackButton({ pack }: { pack: EvidencePackOut }) {
  const [copied, setCopied] = useState(false);
  return (
    <Button
      variant="ghost"
      className="h-7 px-2 text-xs"
      onClick={() => {
        void writeToClipboard(JSON.stringify(pack, null, 2)).then((ok) => {
          if (!ok) return;
          setCopied(true);
          setTimeout(() => {
            setCopied(false);
          }, FEEDBACK_MS);
        });
      }}
    >
      {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
      {copied ? "Скопировано" : "Скопировать пакет (JSON)"}
    </Button>
  );
}

/** `client_hints` is free-form JSON from the browser, so a value is only
 *  rendered when it really is a string. */
function hint(hints: Record<string, unknown>, key: string): string | null {
  const value = hints[key];
  return typeof value === "string" ? value : null;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString("ru");
}
