/**
 * One skin trade in full, beside the list: what ops looks up on Waxpeer (project id,
 * Waxpeer id), the Steam offer, the money both ways, the dates, the reason in words and
 * as Waxpeer wrote it — the refund and retry buttons (`TradeActions`), and the way to mark
 * it settled, with what was done.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "@yupay/ui";
import { ExternalLink, X } from "lucide-react";
import { useRef, useState } from "react";
import { Link } from "react-router-dom";

import {
  boughtUsd,
  fill,
  marginText,
  reasonText,
  resolveTrade,
  T,
  usd,
  type AdminSkinTradeOut,
} from "./api";
import { TradeActions } from "./TradeActions";

import { CopyId } from "@/components/CopyId";
import { StatusChip } from "@/components/StatusChip";
import { useDialog } from "@/lib/useDialog";

const D = T.trades.drawer;

const when = (iso: string | null) =>
  iso
    ? new Intl.DateTimeFormat("ru", { dateStyle: "short", timeStyle: "short" }).format(
        new Date(iso),
      )
    : "—";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[minmax(0,11rem)_1fr] gap-3 py-1.5 text-sm">
      <dt className="text-[var(--text-secondary)]">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  );
}

export function TradeDrawer({ trade, onClose }: { trade: AdminSkinTradeOut; onClose: () => void }) {
  const containerRef = useRef<HTMLDivElement>(null);
  useDialog({ open: true, onClose, containerRef });
  const qc = useQueryClient();
  const [note, setNote] = useState("");
  const resolve = useMutation({
    mutationFn: () => resolveTrade(trade.id, note.trim()),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["admin", "skins", "trades"] });
      onClose();
    },
  });
  const why = reasonText(trade);

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-black/40"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={containerRef}
        role="dialog"
        aria-modal="true"
        aria-label={D.title}
        className="flex h-full w-full max-w-xl flex-col overflow-y-auto border-l border-[var(--border-default)] bg-[var(--bg-surface)] shadow-[var(--shadow-md)]"
      >
        <header className="sticky top-0 z-10 flex items-start justify-between gap-3 border-b border-[var(--border-default)] bg-[var(--bg-surface)] px-5 py-3">
          <div className="flex min-w-0 items-center gap-3">
            {trade.image_url && (
              <img src={trade.image_url} alt="" className="h-12 w-16 shrink-0 object-contain" />
            )}
            <div className="min-w-0">
              <p className="font-semibold">
                {trade.market_hash_name}
                {trade.phase && (
                  <span className="text-[var(--text-secondary)]"> {trade.phase}</span>
                )}
              </p>
              <StatusChip domain="skinTradeState" value={trade.state} />
            </div>
          </div>
          <button type="button" onClick={onClose} aria-label={D.close} className="p-1">
            <X size={18} aria-hidden />
          </button>
        </header>

        <div className="space-y-5 px-5 py-4">
          <div className="flex flex-wrap gap-2">
            <Link
              to={`/orders/${trade.order_id}`}
              className="rounded-md border border-[var(--border-default)] px-3 py-1.5 text-sm font-medium"
            >
              {D.openOrder}
            </Link>
            {trade.offer_url && (
              <a
                href={trade.offer_url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 rounded-md border border-[var(--border-default)] px-3 py-1.5 text-sm font-medium"
              >
                {D.openOffer}
                <ExternalLink size={14} aria-hidden />
              </a>
            )}
          </div>

          <dl className="divide-y divide-[var(--border-subtle)]">
            {why && (
              <Row label={D.reason}>
                <span className={trade.attention ? "font-medium text-[var(--danger)]" : ""}>
                  {why}
                </span>
                {trade.reason && why !== trade.reason && (
                  <span className="block text-xs text-[var(--text-secondary)]">
                    {fill(D.raw, { text: trade.reason })}
                  </span>
                )}
              </Row>
            )}
            <Row label={D.sold}>{usd(trade.sold_usd)}</Row>
            <Row label={D.bought}>{usd(boughtUsd(trade))}</Row>
            <Row label={D.margin}>{marginText(trade)}</Row>
            <Row label={D.seller}>{trade.seller_name ?? "—"}</Row>
            <Row label={D.created}>{when(trade.created_at)}</Row>
            {trade.state === "offer_sent" && trade.send_until && (
              <Row label={D.sendUntil}>{when(trade.send_until)}</Row>
            )}
            {trade.accepted_at && <Row label={D.acceptedAt}>{when(trade.accepted_at)}</Row>}
            {trade.release_date && <Row label={D.releaseDate}>{when(trade.release_date)}</Row>}
            <Row label={D.lastChecked}>{when(trade.last_checked_at)}</Row>
            <Row label={D.waxpeerStatus}>{trade.waxpeer_status ?? "—"}</Row>
            <Row label={D.projectId}>
              <CopyId value={trade.project_id} chars={64} />
            </Row>
            <Row label={D.waxpeerId}>{trade.waxpeer_id ?? "—"}</Row>
            <Row label={D.tradeId}>{trade.trade_id ?? "—"}</Row>
            <Row label={D.order}>
              <CopyId value={trade.order_id} chars={64} />
            </Row>
          </dl>

          <TradeActions trade={trade} onDone={onClose} />

          {trade.resolved_at ? (
            <p className="rounded-md bg-[var(--bg-muted)] p-3 text-sm">
              {fill(D.resolvedBy, { date: when(trade.resolved_at) })}
              {trade.resolved_note && (
                <span className="mt-1 block text-[var(--text-secondary)]">
                  {trade.resolved_note}
                </span>
              )}
            </p>
          ) : (
            trade.attention && (
              <section className="space-y-2 rounded-md border border-[var(--border-default)] p-3">
                <h3 className="text-sm font-semibold">{D.resolveTitle}</h3>
                <label className="block text-sm">
                  <span className="sr-only">{D.noteLabel}</span>
                  <textarea
                    value={note}
                    onChange={(e) => {
                      setNote(e.target.value);
                    }}
                    rows={3}
                    maxLength={500}
                    placeholder={D.notePlaceholder}
                    className="w-full rounded-md border border-[var(--border)] bg-transparent p-2 text-sm"
                  />
                </label>
                <Button
                  disabled={resolve.isPending}
                  onClick={() => {
                    resolve.mutate();
                  }}
                >
                  {D.resolve}
                </Button>
                {resolve.isError && (
                  <p role="alert" className="text-sm text-[var(--danger)]">
                    {T.trades.resolveError}
                  </p>
                )}
              </section>
            )
          )}
        </div>
      </div>
    </div>
  );
}
