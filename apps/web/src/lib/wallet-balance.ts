/**
 * What the "pay from balance" tile should say, decided away from React.
 *
 * The three states a customer can be in are not obvious from a boolean, and
 * getting them wrong is expensive in both directions: offering a payment that
 * will be refused, or hiding one they could have used. So the decision is a
 * single exhaustive function with tests, and the component only renders what
 * it returns.
 *
 * Amounts are the charge currency's major units (soum), matching
 * `order.total_charged` and `BalanceOut.balance`, both of which the API sends
 * as decimal strings.
 */

/** Balances as `GET /api/v1/wallet` returns them. */
export interface WalletBalance {
  account_id: string;
  kind: string;
  currency: string;
  balance: string;
}

export type WalletTile =
  /** Not signed in — the wallet needs an account, so offer the way in. */
  | { state: "guest" }
  /** Signed in, balance covers the order. */
  | { state: "ready"; balance: number }
  /** Signed in, balance is short by `missing`. */
  | { state: "short"; balance: number; missing: number }
  /** Balance not known yet: the query is in flight, or the customer has not
   *  chosen what they are buying, so there is no total to compare against. */
  | { state: "unknown" };

/**
 * The spendable balance in `currency`, or `null` when it is not loaded.
 *
 * Only `user_wallet` counts. Cashback and promo credit sit in the same
 * response and in the same ledger, but nothing spends them yet — counting
 * them here would offer a payment the gateway then refuses.
 */
export function spendableBalance(
  balances: WalletBalance[] | null | undefined,
  currency: string,
): number | null {
  if (!balances) return null;
  const row = balances.find((b) => b.kind === "user_wallet" && b.currency === currency);
  if (!row) return 0;
  const parsed = Number.parseFloat(row.balance);
  return Number.isFinite(parsed) ? parsed : 0;
}

/**
 * Decide the tile.
 *
 * `total` is what the order will be charged, or `null` before the customer has
 * picked a package — the tile then shows the balance without a verdict rather
 * than guessing one.
 */
export function walletTile(input: {
  isLoggedIn: boolean;
  balance: number | null;
  total: number | null;
}): WalletTile {
  if (!input.isLoggedIn) return { state: "guest" };
  if (input.balance === null) return { state: "unknown" };
  if (input.total === null || input.total <= 0) return { state: "unknown" };
  if (input.balance >= input.total) return { state: "ready", balance: input.balance };
  return {
    state: "short",
    balance: input.balance,
    // Rounded up to the soum: an acquirer will not take a fraction of one, and
    // asking for 44 999.6 would leave the customer a hair short after paying.
    missing: Math.ceil(input.total - input.balance),
  };
}

/** Whether the tile can be selected as the payment method. */
export function canPayFromBalance(tile: WalletTile): boolean {
  return tile.state === "ready";
}
