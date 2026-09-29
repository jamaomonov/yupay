/**
 * The customer card's CS2 skins section: the Steam account of the saved trade link, every
 * account their skin orders went to, and their last trades, each opening its order. Nothing
 * at all for a customer who never touched skins.
 */

import { useQuery } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import { Link } from "react-router-dom";

import { fill, shortWhen, T, usd } from "./api";
import { fetchCustomerSkins, type SteamAccount } from "./customer-api";

import { StatusChip } from "@/components/StatusChip";
import { qk } from "@/lib/queryKeys";

const C = T.customer;

function Account({ account, note }: { account: SteamAccount; note?: string }) {
  return (
    <li className="flex items-center justify-between gap-3 text-sm">
      <a
        href={account.profile_url}
        target="_blank"
        rel="noreferrer"
        className="inline-flex items-center gap-1 font-mono text-[13px] text-[var(--accent)]"
      >
        {account.steam_id}
        <ExternalLink size={12} aria-hidden />
      </a>
      {note && <span className="text-xs text-[var(--text-secondary)]">{note}</span>}
    </li>
  );
}

export function CustomerSkins({ userId }: { userId: string }) {
  const { data } = useQuery({
    queryKey: qk.skinCustomer(userId),
    queryFn: () => fetchCustomerSkins(userId),
  });
  if (!data || (!data.saved && data.accounts.length === 0 && data.trades.length === 0)) {
    return null;
  }
  return (
    <section className="space-y-3">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-[var(--text-secondary)]">
        {C.title}
      </h2>
      <div className="grid gap-3 rounded-lg border border-[var(--border-default)] p-3 sm:grid-cols-2">
        {data.saved && (
          <div className="space-y-1">
            <p className="text-xs text-[var(--text-secondary)]">{C.saved}</p>
            <ul>
              <Account account={data.saved} note={shortWhen(data.saved.updated_at)} />
            </ul>
          </div>
        )}
        {data.accounts.length > 0 && (
          <div className="space-y-1">
            <p className="text-xs text-[var(--text-secondary)]">{C.accounts}</p>
            <ul className="space-y-1">
              {data.accounts.map((a) => (
                <Account
                  key={a.steam_id}
                  account={a}
                  note={fill(C.orders, { n: String(a.orders) })}
                />
              ))}
            </ul>
          </div>
        )}
      </div>
      {data.trades.length > 0 && <p className="text-xs text-[var(--text-secondary)]">{C.trades}</p>}
      {data.trades.length > 0 && (
        <ul className="divide-y divide-[var(--border-subtle)] rounded-lg border border-[var(--border-default)]">
          {data.trades.map((t) => (
            <li key={t.id}>
              <Link
                to={`/orders/${t.order_id}`}
                className="flex items-center justify-between gap-3 px-3 py-2 text-sm hover:bg-[var(--bg-muted)]"
              >
                <span className="min-w-0 truncate">
                  {t.market_hash_name}
                  {t.phase && <span className="text-[var(--text-secondary)]"> {t.phase}</span>}
                </span>
                <span className="flex shrink-0 items-center gap-2">
                  <span className="tabular-nums">{usd(t.sold_usd)}</span>
                  <StatusChip domain="skinTradeState" value={t.state} />
                  <span className="text-xs text-[var(--text-secondary)]">
                    {shortWhen(t.created_at)}
                  </span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
