import type { P2PDeposit, Transaction } from "./types";

export type FeedEntry =
  | { type: "movement"; row: Transaction; index: number; at: string }
  | { type: "request"; deposit: P2PDeposit; at: string };

/**
 * One feed, newest first: the ledger's movements and the card top-up requests that did
 * not become one.
 *
 * Top-ups used to be their own block above the statement, and on a busy account the
 * statement — the point of the screen — started below the fold, where nobody knew to look.
 * A paid request is already in the ledger as «Пополнение депозита» (noted «P2P · T-…»), so
 * only the others join it: the one waiting for a transfer, and the expired or cancelled
 * ones, muted. While older movements are still unloaded, requests older than the last
 * loaded one wait for them, so a request never lands below movements it predates.
 */
export function mergeFeed(rows: Transaction[], requests: P2PDeposit[], more: boolean): FeedEntry[] {
  const oldest = rows.at(-1)?.created_at;
  const feed: FeedEntry[] = rows.map((row, index) => ({
    type: "movement",
    row,
    index,
    at: row.created_at,
  }));
  for (const deposit of requests) {
    if (deposit.status === "paid") continue;
    if (more && oldest !== undefined && deposit.created_at < oldest) continue;
    feed.push({ type: "request", deposit, at: deposit.created_at });
  }
  return feed.sort((a, b) => (a.at < b.at ? 1 : a.at > b.at ? -1 : 0));
}
