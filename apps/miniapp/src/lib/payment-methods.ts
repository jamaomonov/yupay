/**
 * Canonical list of external payment acquirers — the single source of truth
 * shared by the order checkout (``TopUp``) and the wallet top-up
 * (``WalletTopUp``) pages so the two never drift apart again.
 *
 * Each entry maps a UI method id to a backend ``payments.gateways`` provider
 * slug. Whether a method is actually usable right now is decided at render time
 * from ``GET /payments/providers`` (``useAvailableProviders``) — not here.
 *
 * The wallet ("pay from balance") option is intentionally NOT in this list: it
 * only applies to order checkout and is rendered as its own card in ``TopUp``.
 */

import type { MessageKey } from "@/lib/i18n";

import clickIcon from "@/assets/payments/click.png";
import paymeIcon from "@/assets/payments/payme.png";
import usdtIcon from "@/assets/payments/usdt.png";
import uzumIcon from "@/assets/payments/uzum.png";

export interface PaymentMethod {
  /** UI id (also the selected-method key on both pages). */
  id: string;
  /** Brand display name (not translated). */
  name: string;
  /** Catalog key for the short subtitle / hint, resolved at render. */
  subKey: MessageKey;
  /** Backend provider slug in ``payments.gateways`` REGISTRY. */
  provider: string;
  /** Currency the acquirer charges in. */
  currency: string;
  /** Brand logo, imported as a URL by Vite. */
  icon: string;
}

export const PAYMENT_METHODS: PaymentMethod[] = [
  {
    id: "click",
    name: "Click",
    subKey: "payment.click.sub",
    provider: "click",
    currency: "UZS",
    icon: clickIcon,
  },
  {
    id: "payme",
    name: "Payme",
    subKey: "payment.payme.sub",
    provider: "payme",
    currency: "UZS",
    icon: paymeIcon,
  },
  {
    id: "uzum",
    name: "Uzum",
    subKey: "payment.uzum.sub",
    provider: "uzum",
    currency: "UZS",
    icon: uzumIcon,
  },
  {
    id: "usdt",
    name: "USDT",
    subKey: "payment.usdt.sub",
    provider: "crypto",
    currency: "USDT",
    icon: usdtIcon,
  },
];

/** method id → backend provider slug. */
export const PROVIDER_BY_METHOD: Record<string, string> = Object.fromEntries(
  PAYMENT_METHODS.map((m) => [m.id, m.provider]),
);

export interface AcquirerInfo {
  label: string;
  currency: string;
}

/** method id → what the customer sees on their statement (label + currency). */
export const ACQUIRER_BY_METHOD: Record<string, AcquirerInfo> = Object.fromEntries(
  PAYMENT_METHODS.map((m) => [m.id, { label: m.name, currency: m.currency }]),
);
