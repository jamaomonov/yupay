/** Who actually redeemed a promo code.
 *
 * The list page shows "3 / 10" and nothing about who, which is the question an
 * operator has the moment a campaign code starts moving. Rendered as faces and
 * names rather than user ids: a row of UUIDs is technically the same answer and
 * useless for recognising anyone.
 */

import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useRef } from "react";
import { Link } from "react-router-dom";

import type { PromoRedemptionListOut, PromoRedemptionOut } from "./types";

import { Spinner } from "@/components/States";
import { apiGet } from "@/lib/api";
import { useDialog } from "@/lib/useDialog";

/** The server's own ceiling. A code handed out in a campaign can have plenty
 *  of uses; past this the modal is the wrong tool and the wallet ledger is the
 *  right one. */
const LIMIT = 200;

interface Props {
  promoId: string;
  code: string;
  onClose: () => void;
}

export function PromoRedemptionsModal({ promoId, code, onClose }: Props) {
  const dialogRef = useRef<HTMLDivElement | null>(null);
  useDialog({ open: true, onClose, containerRef: dialogRef });

  const query = useQuery<PromoRedemptionListOut>({
    queryKey: ["admin", "promo", promoId, "redemptions"],
    queryFn: () =>
      apiGet<PromoRedemptionListOut>(
        `/api/v1/admin/promo/${promoId}/redemptions?limit=${String(LIMIT)}`,
      ),
  });

  const items = query.data?.items ?? [];
  const total = query.data?.total ?? 0;

  return (
    <div
      ref={dialogRef}
      role="dialog"
      aria-modal="true"
      aria-label={`Активации промокода ${code}`}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
    >
      <div className="flex max-h-[80vh] w-full max-w-md flex-col rounded-lg border bg-[var(--bg-surface)] shadow-[var(--shadow-lg)]">
        <header className="flex items-center justify-between gap-3 border-b px-4 py-3">
          <div className="min-w-0">
            <h2 className="text-sm font-semibold">Кто активировал</h2>
            <code className="font-mono text-xs text-[var(--text-secondary)]">{code}</code>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Закрыть"
            className="rounded-md p-1 text-[var(--text-secondary)] hover:bg-[var(--bg-muted)] hover:text-[var(--text-primary)]"
          >
            <X className="size-4" />
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          {query.isPending && <Spinner label="Загружаем…" />}
          {query.isError && (
            <p role="alert" className="p-3 text-sm text-[var(--danger)]">
              Не удалось загрузить список.
            </p>
          )}
          {query.data && items.length === 0 && (
            <p className="p-3 text-sm text-[var(--text-secondary)]">
              Код ещё никто не активировал.
            </p>
          )}

          <ul>
            {items.map((r) => (
              <RedemptionRow key={`${r.user_id}-${r.redeemed_at}`} row={r} onNavigate={onClose} />
            ))}
          </ul>

          {total > items.length && (
            <p className="p-3 text-xs text-[var(--text-secondary)]">
              Показаны последние {items.length} из {total}.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

function RedemptionRow({ row, onNavigate }: { row: PromoRedemptionOut; onNavigate: () => void }) {
  // Whatever the account actually has: a Telegram account carries a name, an
  // email-only one does not, and "—" beats an empty row that looks broken.
  const name = row.display_name ?? (row.tg_username ? `@${row.tg_username}` : null) ?? row.email;

  return (
    <li>
      <Link
        to={`/customers/${row.user_id}`}
        onClick={onNavigate}
        className="flex items-center gap-3 rounded-md px-2 py-2 transition-colors hover:bg-[var(--bg-muted)]"
      >
        <Avatar url={row.photo_url} name={name} />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium">{name ?? "Без имени"}</span>
          <span className="block truncate text-xs text-[var(--text-secondary)]">
            {new Date(row.redeemed_at).toLocaleString("ru")}
          </span>
        </span>
      </Link>
    </li>
  );
}

function Avatar({ url, name }: { url: string | null; name: string | null }) {
  if (url) {
    return (
      <img
        src={url}
        alt=""
        className="size-9 shrink-0 rounded-full border border-[var(--border-default)] object-cover"
      />
    );
  }
  return (
    <div
      className="flex size-9 shrink-0 items-center justify-center rounded-full border border-[var(--border-default)] text-xs font-semibold text-[var(--text-secondary)]"
      style={{ background: "var(--bg-muted)" }}
    >
      {(name?.replace(/^@/, "")[0] ?? "?").toUpperCase()}
    </div>
  );
}
