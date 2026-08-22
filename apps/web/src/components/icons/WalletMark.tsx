/**
 * The wallet mark.
 *
 * Drawn rather than taken from the icon set: lucide's `Wallet` is a literal
 * billfold with a clasp, which reads as cash next to a storefront that sells
 * nothing physical. This is the same idea reduced to the shapes the brand
 * already uses — the rounded rectangle of the payment marks, and the coin as a
 * filled dot, the way the balance chip and the pack tiles use a filled accent.
 *
 * `currentColor` throughout so it inherits whatever the control around it is
 * doing, including the accent when the wallet is the selected payment method.
 */
export function WalletMark({ size = 16, className }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      className={className}
    >
      {/* The body: the same corner radius family as the payment marks. */}
      <rect x="2.5" y="5.5" width="19" height="13" rx="3.5" />
      {/* The pocket the card slots into — one straight line, no clasp. */}
      <path d="M2.5 10.5h19" />
      {/* The coin. Filled, because an outline at 16px turns to mush. */}
      <circle cx="17" cy="14.5" r="1.4" fill="currentColor" stroke="none" />
    </svg>
  );
}
