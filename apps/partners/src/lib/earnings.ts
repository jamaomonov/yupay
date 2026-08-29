/**
 * What a partner would earn, given some assumptions.
 *
 * Split out from the component so the arithmetic can be tested without a DOM,
 * and so the defaults sit in one place where they can be checked against
 * reality rather than being tuned to make the number look good.
 */

/**
 * Defaults for the calculator, each traceable to a measurement rather than to
 * what reads well.
 *
 * ``AVERAGE_ORDER_UZS`` is the shape of a real order on this storefront, not a
 * flattering round number. ``ORDERS_PER_BUYER`` is measured: 37% of buyers
 * return and the mean is 1.97 orders each — which is the whole reason lifetime
 * attribution is worth anything, and also the reason it is worth about double
 * the first order rather than ten times it.
 *
 * A calculator that overpromises is the fastest way to lose a partner after
 * their first payout, so these numbers stay honest even where a larger one
 * would recruit better.
 */
export const DEFAULTS = {
  // 20k rather than the 5k this started at. The calculator opens on this
  // number, and 5k produced 23,640 so'm — under half the 50,000 withdrawal
  // floor the FAQ states two bands below. The first figure on a page that
  // promises honesty must not be one that cannot be paid out.
  audience: 20_000,
  conversionPercent: 1,
  averageOrderUzs: 12_000,
  ordersPerBuyer: 1.97,
  commissionPercent: 2,
} as const;

export interface EarningsInput {
  audience: number;
  conversionPercent: number;
  averageOrderUzs: number;
  ordersPerBuyer: number;
  commissionPercent: number;
}

export interface Earnings {
  /** How many people from the audience are assumed to buy at all. */
  buyers: number;
  /** Orders those buyers place, over their lifetime. */
  orders: number;
  /** What the partner earns on them, in UZS. */
  earnedUzs: number;
}

/**
 * Estimate lifetime earnings from one campaign.
 *
 * Deliberately lifetime rather than monthly. A monthly figure would need an
 * assumed campaign cadence this cannot know, and quoting one implies a partner
 * earns it again every month — which is true only if they keep bringing new
 * buyers at the same rate.
 *
 * Args:
 *     input: The five assumptions. Negative or non-finite values are clamped
 *         to zero rather than producing a negative estimate.
 *
 * Returns:
 *     Buyers, orders and earnings. Earnings are rounded to whole so'm, which
 *     is the smallest unit anyone is ever paid in.
 */
export function estimateEarnings(input: EarningsInput): Earnings {
  const clamp = (n: number): number => (Number.isFinite(n) && n > 0 ? n : 0);

  const audience = clamp(input.audience);
  const conversion = clamp(input.conversionPercent) / 100;
  const average = clamp(input.averageOrderUzs);
  const perBuyer = clamp(input.ordersPerBuyer);
  const commission = clamp(input.commissionPercent) / 100;

  const buyers = audience * conversion;
  const orders = buyers * perBuyer;
  const earnedUzs = Math.round(orders * average * commission);

  return { buyers: Math.round(buyers), orders: Math.round(orders), earnedUzs };
}
